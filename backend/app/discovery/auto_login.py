"""Auto-login on discovery: trying stored credentials against a host the scan just found, so a human
never has to type a hostname in twice (once into discovery, once into an Integration).

Two credential sources feed this, tried in this order for a given host:

1. `NetworkCredentialBinding` - an ordered list of credentials bound to a *network*, tried only against
   that network's SSH-open hosts (`attempt_ssh_auto_login`). SSH-only, unchanged from how this worked
   before the credential wallet existed - see docs/decisions.md "Auto-login on discovery".
2. The credential wallet - any Integration saved with a credential but no host (see
   docs/credentials.md's "Credential wallet" section). Unlike network bindings, a wallet credential
   isn't scoped to one network: it's tried against any host, on any network, that this scan thinks
   looks like the matching plugin's kind of service (`attempt_wallet_login`, driven by
   `fingerprint.suggest_integration_type`'s port/banner guess). Works for every plugin that both takes a
   credential and has a `probe_credential` method (generic_ssh, proxmox, adguard_home, homebridge, omada,
   windows_winrm) - see base.py.

On the first credential that authenticates, a real (host-bound) Integration is auto-provisioned and the
Device is promoted to managed - no human step either way.

**This is credential spraying against your own LAN, and the docs say so plainly rather than softening
it.** Trying every stored credential against every host that looks like it might accept that kind of
credential is acceptable only because this is a trusted single-admin home network with a small number of
hosts/credentials - see docs/decisions.md and docs/credentials.md. Bounded by the same per-host
concurrency the scanner already applies and a short per-attempt timeout, so a run of this can't become a
lockout storm.

Only `generic_ssh` gets the host-key trust gate (`_host_key_trusted`): it's the one plugin with a concept
of pinning a host's identity before any secret is sent. The other plugins have no equivalent today, so
their wallet probing is bounded only by the timeout and the fact that the attempted credential's secret
is sent over TLS that the probe deliberately does not verify (there's no pinned certificate for a host
discovery hasn't configured yet) - the same trade-off docs/integrations.md already documents for each of
those plugins' own `verify_tls` setting, just applied at probe time instead of poll time.
"""

from typing import Any

import asyncssh
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.credentials.crypto import get_secret_box
from app.credentials.service import CredentialNotFoundError, CredentialService
from app.db.session import Databases
from app.domain.bootstrap import ensure_default_discovery_settings
from app.domain.enums import DeviceType, EventSeverity
from app.domain.models import Device, Event, Integration, NetworkCredentialBinding, SshHostKey
from app.integrations import registry
from app.integrations.generic_ssh import hostkey
from app.logging_setup import get_logger

logger = get_logger(__name__)

SSH_LOGIN_TIMEOUT_SECONDS = 5.0

# No dedicated DeviceType exists for these vendor appliances; OTHER is the same fallback the rest of the
# domain model uses for anything without a specific type.
_WALLET_DEVICE_TYPE: dict[str, DeviceType] = {
    "generic_ssh": DeviceType.LINUX,
    "windows_winrm": DeviceType.WINDOWS,
    "proxmox": DeviceType.PROXMOX_NODE,
}


def _is_wallet_integration(integration: Integration) -> bool:
    return integration.credential_id is not None and not integration.config.get("host")


async def _wallet_integrations(session: AsyncSession, integration_type: str) -> list[Integration]:
    """Enabled integrations of this type with no host - i.e. saved as a credential-wallet entry
    (see docs/credentials.md). Disabling one, like any other Integration, is how a user pauses it
    without deleting the stored credential."""
    result = await session.execute(
        select(Integration)
        .where(Integration.integration_type == integration_type, Integration.enabled.is_(True))
        .order_by(Integration.id)
    )
    return [i for i in result.scalars().all() if _is_wallet_integration(i)]


async def attempt_ssh_auto_login(
    databases: Databases, network_id: int | None, ip: str, device_id: int, port: int = 22
) -> None:
    async with databases.app_session_factory() as session:
        device = await session.get(Device, device_id)
        if device is None or device.managed:
            return  # already provisioned (or gone) - don't re-spray credentials every scan cycle

        bindings = []
        if network_id is not None:
            result = await session.execute(
                select(NetworkCredentialBinding)
                .where(NetworkCredentialBinding.network_id == network_id)
                .order_by(NetworkCredentialBinding.priority)
            )
            bindings = list(result.scalars().all())
        wallet = await _wallet_integrations(session, "generic_ssh")

    binding_credential_ids = [b.credential_id for b in bindings]
    wallet_credential_ids = [i.credential_id for i in wallet if i.credential_id is not None]
    if not binding_credential_ids and not wallet_credential_ids:
        return

    # Learn the host's key first, without sending anything secret; credentials only go to a host whose key
    # is trusted (approved by a human, or pinned on first use when approval is switched off).
    try:
        line = hostkey.key_line(await hostkey.scan_host_key(ip, port, SSH_LOGIN_TIMEOUT_SECONDS))
    except (asyncssh.Error, OSError, TimeoutError):
        return
    if not await _host_key_trusted(databases, ip, port, line):
        return

    credential_service = CredentialService(get_secret_box())

    # Network-bound credentials first (priority order), then the wallet, oldest first.
    for credential_id in [*binding_credential_ids, *wallet_credential_ids]:
        try:
            async with databases.credentials_session_factory() as cred_session:
                credential = await credential_service.get_decrypted(cred_session, credential_id)
        except CredentialNotFoundError:
            continue

        username = credential.get("username")
        if not username or not (credential.get("private_key") or credential.get("password")):
            continue  # not an SSH-shaped credential (e.g. api_token/basic_auth bound by mistake)

        ok = await _try_ssh_login(ip, port, credential, line)
        logger.info("auto_login_attempt", ip=ip, credential_id=credential_id, success=ok)
        if ok:
            await _provision_integration(
                databases, device_id, ip, port, "generic_ssh", credential_id, extra_config={"host_key": line}
            )
            return


async def _host_key_trusted(databases: Databases, ip: str, port: int, line: str) -> bool:
    """Whether credentials may be sent to this host. With approval required, an unseen key is recorded as
    pending (shown in Discovery) and nothing is sent until a human approves it; without it, the first key
    seen is pinned automatically. A later *changed* key is a separate decision, controlled by
    `ssh_hostkey_auto_repin` (default on): re-pin it and keep going - on a LAN a changed key usually means
    this IP was reassigned to a different machine (reimage, new VM), not an attacker - or, with that
    setting off, pause and require approval again, same as an unapproved key."""
    async with databases.app_session_factory() as session:
        settings = await ensure_default_discovery_settings(session)
        required, auto_repin = settings.ssh_hostkey_approval, settings.ssh_hostkey_auto_repin
        row = await session.scalar(select(SshHostKey).where(SshHostKey.host == ip, SshHostKey.port == port))
        shown = hostkey.fingerprint(line)
        if row is None:
            session.add(
                SshHostKey(host=ip, port=port, public_key=line, fingerprint=shown, approved=not required)
            )
            if required:
                _record_event(session, f"SSH host key of {ip}:{port} ({shown}) awaits approval")
            await session.commit()
            return not required
        if row.public_key != line:
            if not auto_repin:
                if row.approved:  # a key a human or an earlier scan trusted has been replaced
                    row.changed = True
                    _record_event(
                        session, f"SSH host key of {ip}:{port} changed to {shown}; auto-login paused"
                    )
                row.public_key, row.fingerprint, row.approved = line, shown, False
                await session.commit()
                return False
            row.public_key, row.fingerprint, row.approved, row.changed = line, shown, True, False
            _record_event(session, f"SSH host key of {ip}:{port} changed to {shown}; re-pinned automatically")
            await session.commit()
            return True
        return row.approved


def _record_event(session: AsyncSession, message: str) -> None:
    session.add(
        Event(source="discovery", severity=EventSeverity.WARNING, category="ssh_host_key", message=message)
    )


async def _try_ssh_login(ip: str, port: int, credential: dict[str, Any], line: str) -> bool:
    """Delegates to generic_ssh's own probe_credential (it owns the actual connect logic, shared with
    non-SSH-specific wallet probing - see base.py). `line` is accepted for backward compatibility with
    callers/tests that already scanned the host key; the plugin re-scans it itself before connecting."""
    plugin = registry.get_plugin("generic_ssh")
    if plugin is None:
        return False
    return bool(await plugin.probe_credential(credential, ip, port))  # type: ignore[attr-defined]


async def attempt_wallet_login(
    databases: Databases, ip: str, device_id: int, port: int, integration_type: str
) -> None:
    """Tries every wallet credential of `integration_type` against ip:port - the non-SSH half of the
    credential wallet (see module docstring). `integration_type` comes from
    `fingerprint.suggest_integration_type`'s best-effort guess at what's listening on this port."""
    if integration_type == "generic_ssh":
        return  # handled by attempt_ssh_auto_login, which also applies the host-key trust gate
    plugin = registry.get_plugin(integration_type)
    probe = getattr(plugin, "probe_credential", None)
    if probe is None:
        return

    async with databases.app_session_factory() as session:
        device = await session.get(Device, device_id)
        if device is None or device.managed:
            return
        wallet = await _wallet_integrations(session, integration_type)
    if not wallet:
        return

    credential_service = CredentialService(get_secret_box())
    for integration in wallet:
        assert integration.credential_id is not None  # guaranteed by _is_wallet_integration
        try:
            async with databases.credentials_session_factory() as cred_session:
                credential = await credential_service.get_decrypted(cred_session, integration.credential_id)
        except CredentialNotFoundError:
            continue

        try:
            ok = await probe(credential, ip, port)
        except Exception as exc:
            # A plugin bug in probe_credential must not abort the rest of the scan.
            logger.warning(
                "wallet_probe_failed", integration_type=integration_type, ip=ip, error=repr(exc)
            )
            ok = False
        logger.info(
            "wallet_login_attempt",
            integration_type=integration_type,
            ip=ip,
            credential_id=integration.credential_id,
            success=ok,
        )
        if ok:
            await _provision_integration(
                databases, device_id, ip, port, integration_type, integration.credential_id
            )
            return


async def _provision_integration(
    databases: Databases,
    device_id: int,
    ip: str,
    port: int,
    integration_type: str,
    credential_id: int,
    extra_config: dict[str, Any] | None = None,
) -> None:
    from app.scheduler.supervisor import get_supervisor  # local import: avoid a circular import

    config: dict[str, Any] = {"host": ip, "port": port, **(extra_config or {})}
    # proxmox enumerates its own targets (one Integration monitors many nodes/VMs/LXCs) and has no
    # single Device to link in config; every other plugin here is one-to-one against the Device found.
    if integration_type != "proxmox":
        config["device_id"] = device_id

    async with databases.app_session_factory() as session:
        device = await session.get(Device, device_id)
        if device is None:
            return
        device.managed = True
        device_type = _WALLET_DEVICE_TYPE.get(integration_type)
        if device_type is not None:
            device.device_type = device_type

        integration = Integration(
            integration_type=integration_type,
            name=f"{device.display_name} (auto)",
            config=config,
            credential_id=credential_id,
            enabled=True,
        )
        session.add(integration)
        await session.commit()
        await session.refresh(integration)

    logger.info(
        "auto_login_provisioned_integration", integration_type=integration_type, device_id=device_id, ip=ip
    )
    await get_supervisor().add_integration(integration)
