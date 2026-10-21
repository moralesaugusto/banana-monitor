"""TLS verification for integrations that talk to devices with self-signed certificates: instead of switching
verification off, the device's own certificate (or its CA) is pinned as the only trusted root."""

import base64
import re
import ssl

_PEM = re.compile(r"-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----", re.DOTALL)


def normalize_pem(text: str) -> str:
    """Accepts a pasted certificate even when its line breaks were lost (a single-line text field) and
    returns a clean PEM. Raises ValueError when it is not a certificate."""
    match = _PEM.search(text)
    if match is None:
        raise ValueError("tls_ca_pem must be a PEM certificate (-----BEGIN CERTIFICATE-----)")
    body = re.sub(r"\s+", "", match.group(1))
    try:
        base64.b64decode(body, validate=True)
    except ValueError as exc:
        raise ValueError("tls_ca_pem is not valid base64") from exc
    lines = [body[i : i + 64] for i in range(0, len(body), 64)]
    return "-----BEGIN CERTIFICATE-----\n" + "\n".join(lines) + "\n-----END CERTIFICATE-----\n"


def httpx_verify(verify_tls: bool, ca_pem: str = "") -> bool | ssl.SSLContext:
    """What to pass as httpx's `verify`. A pinned certificate wins over the on/off switch: only that
    certificate is trusted, and the host name is not checked (devices are reached by IP address)."""
    if ca_pem:
        context = ssl.create_default_context(cadata=normalize_pem(ca_pem))
        context.check_hostname = False
        context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        return context
    return verify_tls


def explain(exc: Exception) -> str:
    """The error text, with what to do about it when the cause is an untrusted device certificate."""
    text = str(exc)
    if "CERTIFICATE_VERIFY_FAILED" in text:
        return (
            f"{text}. The device's certificate is not trusted: paste its certificate into tls_ca_pem "
            "(`openssl s_client -connect host:port </dev/null | openssl x509`), or set verify_tls to false "
            "to accept it without checking."
        )
    return text
