"""Best-effort mapping from a scanned port and its HTTP probe result to a
suggested vendor integration type (AdGuard Home, Homebridge, Omada, Proxmox,
Windows/WinRM).

This is only a hint: it's attached to a discovered service candidate's
raw_attributes for a human to see during review (a future frontend pass),
never a hard classification. A missing or wrong guess must never block a
user from manually configuring the candidate as any service/integration type
- see docs/discovery.md. It also drives which credential-wallet entries
(backend/app/discovery/auto_login.py) get tried against a discovered host -
see docs/credentials.md's "Credential wallet" section.

DHCP is deliberately not fingerprinted here - see docs/discovery.md for why
it can't be attributed to an arbitrary discovered host from passive scanning.
"""

_PORT_HINTS: dict[int, str] = {
    22: "generic_ssh",
    3000: "adguard_home",
    8006: "proxmox",
    8043: "omada",
    8843: "omada",
    8581: "homebridge",
    5986: "windows_winrm",
}
"""Port 22 suggests generic_ssh regardless of the host's guessed OS: SSH is a protocol, not a Linux-only
one, and attempt_ssh_auto_login already tries every generic_ssh wallet credential against any port-22 host
with no OS check at all (network_scanner.py). This just makes the Discovery page's suggestion agree with
what auto-login already does, rather than never suggesting SSH at all."""


def suggest_integration_type(port: int, http_info: dict[str, str] | None) -> str | None:
    """Returns a suggested_integration_type value, or None for no confident guess.

    Content signals (page title, Server header) take priority over the port
    number alone, since a title/header match is a stronger signal than "this
    port is commonly used by product X" - but either can produce a guess.
    """
    if http_info:
        title = http_info.get("title", "").lower()
        server = http_info.get("server", "").lower()

        if "adguard" in title or "adguard" in server:
            return "adguard_home"
        if "homebridge" in title:
            return "homebridge"
        if "omada" in title or "omada" in server or "tp-link" in title:
            return "omada"

    return _PORT_HINTS.get(port)
