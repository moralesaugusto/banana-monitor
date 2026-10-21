import dns.asyncresolver
import dns.exception
import dns.resolver


async def reverse_dns(ip: str, timeout: float = 2.0, server: str | None = None) -> str | None:
    """The PTR name for `ip`, from `server` when one is configured (a home router or AdGuard Home usually
    knows its DHCP clients) or else from the system resolver."""
    resolver = dns.asyncresolver.Resolver(configure=server is None)
    if server:
        resolver.nameservers = [server]
    try:
        answer = await resolver.resolve_address(ip, lifetime=timeout)
    except (dns.exception.DNSException, OSError):
        return None
    return str(answer[0]).rstrip(".")
