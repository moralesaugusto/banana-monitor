"""Registers built-in integration plugins as a side effect of importing this package.

Anything under app.integrations.* (e.g. `from app.integrations import registry`)
triggers this file first, so no explicit wiring is needed elsewhere. Adding a new
plugin means a new module here plus one register() call - no other core changes.
"""

from app.integrations.adguard_home.plugin import AdGuardHomePlugin
from app.integrations.dhcp_check.plugin import DhcpCheckPlugin
from app.integrations.dns_check.plugin import DnsCheckPlugin
from app.integrations.generic_ssh.plugin import GenericSshPlugin
from app.integrations.homebridge.plugin import HomebridgePlugin
from app.integrations.http_tcp.plugin import HttpTcpPlugin
from app.integrations.omada.plugin import OmadaPlugin
from app.integrations.proxmox.plugin import ProxmoxPlugin
from app.integrations.registry import register
from app.integrations.virustotal.plugin import VirusTotalPlugin
from app.integrations.windows_winrm.plugin import WindowsWinrmPlugin

register(HttpTcpPlugin())
register(GenericSshPlugin())
register(ProxmoxPlugin())
register(DnsCheckPlugin())
register(DhcpCheckPlugin())
register(AdGuardHomePlugin())
register(HomebridgePlugin())
register(OmadaPlugin())
register(WindowsWinrmPlugin())
register(VirusTotalPlugin())
