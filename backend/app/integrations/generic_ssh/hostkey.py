"""SSH host-key pinning. The first connection to a host learns its key (trust on first use, like OpenSSH);
from then on the connection is made against that exact key, so a different machine answering on the same
address cannot be talked to and never receives a password or signs a poll result."""

import asyncio

import asyncssh


class HostKeyChanged(Exception):
    pass


async def scan_host_key(host: str, port: int, timeout: float) -> asyncssh.SSHKey:
    """Reads the server's host key without authenticating, so no credential is sent to learn it."""
    key = await asyncio.wait_for(asyncssh.get_server_host_key(host, port), timeout)
    if key is None:
        raise OSError(f"{host}:{port} did not present an SSH host key")
    return key


def key_line(key: asyncssh.SSHKey) -> str:
    """`ssh-ed25519 AAAA...`: the public key in the format stored in known_hosts files."""
    return key.export_public_key("openssh").decode().strip()


def fingerprint(line: str) -> str:
    return asyncssh.import_public_key(line).get_fingerprint()


def known_hosts_for(host: str, port: int, line: str) -> asyncssh.SSHKnownHosts:
    """A known_hosts that trusts exactly this key for exactly this host and port."""
    name = host if port == 22 else f"[{host}]:{port}"
    return asyncssh.import_known_hosts(f"{name} {line}\n")


def changed_message(line: str) -> str:
    return (
        f"SSH host key does not match the pinned key ({fingerprint(line)}). If the host was reinstalled, "
        "forget the pinned key on the Integrations page; otherwise someone may be impersonating it."
    )
