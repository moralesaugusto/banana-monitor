import asyncio
import contextlib
import ssl

from cryptography import x509
from cryptography.x509.oid import NameOID


async def probe_tls(host: str, port: int, timeout: float = 3.0) -> dict[str, str] | None:
    """Cert CN and expiry, without validating the chain (many home services self-sign)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx), timeout=timeout
        )
    except (OSError, TimeoutError, ssl.SSLError):
        return None

    try:
        ssl_object = writer.get_extra_info("ssl_object")
        der = ssl_object.getpeercert(binary_form=True) if ssl_object else None
        if not der:
            return None
        cert = x509.load_der_x509_certificate(der)
        common_names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return {
            "common_name": str(common_names[0].value) if common_names else "",
            "not_after": cert.not_valid_after_utc.isoformat(),
        }
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
