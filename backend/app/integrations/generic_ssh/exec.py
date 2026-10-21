"""Runs one command on a host that already has a pinned SSH key. Callers decide which commands are allowed
(see `app.llm.inspect_policy`); this module only connects safely."""

from typing import Any

import asyncssh

from app.integrations.generic_ssh import hostkey
from app.integrations.generic_ssh.plugin import GenericSshConfig, ssh_auth_kwargs


class SshExecError(RuntimeError):
    pass


async def run_command(
    config: dict[str, Any], credential: dict[str, Any], command: str, timeout: float | None = None
) -> tuple[int | None, str, str]:
    """Returns (exit status, stdout, stderr). Refuses a host whose key was never pinned: an agent must not
    trust a host on first use."""
    cfg = GenericSshConfig.model_validate(config)
    if not cfg.host_key:
        raise SshExecError("this host's SSH key is not pinned yet; let a poll succeed first")
    assert cfg.host is not None  # a pinned host_key only exists on a host-ful integration
    pinned = cfg.host_key
    try:
        auth_kwargs = ssh_auth_kwargs(credential)
        attempts = 2 if cfg.auto_repin_host_key else 1
        for attempt in range(attempts):
            try:
                async with asyncssh.connect(
                    cfg.host,
                    port=cfg.port,
                    username=credential["username"],
                    known_hosts=hostkey.known_hosts_for(cfg.host, cfg.port, pinned),
                    connect_timeout=cfg.timeout_seconds,
                    **auth_kwargs,
                ) as conn:
                    result = await conn.run(command, check=False, timeout=timeout or cfg.timeout_seconds)
                break
            except asyncssh.HostKeyNotVerifiable:
                if attempt == attempts - 1:
                    raise
                # Same re-pin-and-retry as plugin.py's poll(): on a LAN a changed key usually means
                # this IP now belongs to a different machine, not an attacker. The next regular poll
                # persists the new key to the integration's config; this call just needs it for now.
                scanned = await hostkey.scan_host_key(cfg.host, cfg.port, cfg.timeout_seconds)
                pinned = hostkey.key_line(scanned)
    except asyncssh.HostKeyNotVerifiable as exc:
        raise SshExecError(hostkey.changed_message(pinned)) from exc
    except (asyncssh.Error, OSError, TimeoutError, KeyError, asyncssh.KeyImportError) as exc:
        raise SshExecError(f"ssh failed: {type(exc).__name__}: {exc}") from exc
    return result.exit_status, str(result.stdout or ""), str(result.stderr or "")
