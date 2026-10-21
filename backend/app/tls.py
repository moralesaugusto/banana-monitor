"""Local self-signed TLS certificate for HTTPS, on by default (see
`Settings.https_enabled` in `app.config`). This is a trusted-LAN-only app
(see AGENTS.md): the point of a self-signed cert here is transport
encryption without standing up a CA, not identity verification - browsers
will show a one-time warning to accept it.

Also runnable standalone (`python -m app.tls`) to ensure the cert exists
without starting the server - used by `make dev-backend` so the plain
`uvicorn --reload` CLI (which needs --ssl-certfile/--ssl-keyfile paths that
already exist) can serve HTTPS too, not just the `python -m app.main` /
`uv run banana` entrypoint.
"""

import asyncio
import datetime
import ipaddress
import ssl
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CERT_FILENAME = "cert.pem"
KEY_FILENAME = "key.pem"

# 825 days is the longest leaf-certificate lifetime modern browsers/OSes will
# still accept without complaint (the ~2018 CA/Browser Forum limit).
CERT_VALIDITY_DAYS = 825


def ensure_self_signed_certificate(cert_dir: Path, common_name: str = "localhost") -> tuple[Path, Path]:
    """Returns (cert_path, key_path) under `cert_dir`, generating a self-signed
    EC (P-384) certificate/key pair there first if one doesn't already exist.

    Idempotent: if both files are already present, they're returned as-is,
    untouched - regenerating a cert every start would invalidate any
    previously-accepted browser exception for no reason.
    """
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / CERT_FILENAME
    key_path = cert_dir / KEY_FILENAME

    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    key = ec.generate_private_key(ec.SECP384R1())

    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.UTC)

    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=CERT_VALIDITY_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(common_name),
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.IPAddress(ipaddress.ip_address("::1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_agreement=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(key, hashes.SHA384())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)

    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))

    return cert_path, key_path


ALLOWED_CURVES = {"secp256r1", "secp384r1", "secp521r1"}
REQUIRED_CIPHER = "TLS_AES_256_GCM_SHA384"


class TlsConfigError(RuntimeError):
    pass


def validate_ec_certificate(cert_path: Path) -> None:
    """Only elliptic-curve certificates are served: an RSA (or any other) certificate is refused."""
    certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
    public_key = certificate.public_key()
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or public_key.curve.name not in ALLOWED_CURVES:
        raise TlsConfigError(
            f"{cert_path} is not an ECDSA certificate on P-256, P-384 or P-521; "
            "Banana serves only elliptic-curve certificates"
        )


def build_ssl_context(cert_path: Path, key_path: Path) -> ssl.SSLContext:
    """TLS 1.3 only. The key-exchange groups are left at OpenSSL 3.5's defaults on purpose: they start with
    the hybrid X25519MLKEM768 (post-quantum ML-KEM plus classical X25519), which any client that supports it
    uses, and fall back to classical elliptic-curve groups for clients that do not. Calling set_ecdh_curve
    here would replace that list with a single classical curve."""
    validate_ec_certificate(cert_path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    context.options |= ssl.OP_NO_COMPRESSION | ssl.OP_CIPHER_SERVER_PREFERENCE
    context.load_cert_chain(cert_path, key_path)
    return context


def aes256_only(base: type[asyncio.Protocol]) -> type[asyncio.Protocol]:
    """Python's ssl module cannot remove TLS 1.3 cipher suites, so the server prefers AES-256-GCM (it is first
    in OpenSSL's list and the server's order wins) and this closes any connection that negotiated another
    suite (AES-128, ChaCha20) before a single request is read."""

    class Aes256Only(base):  # type: ignore[valid-type, misc]
        def connection_made(self, transport: asyncio.Transport) -> None:
            cipher = transport.get_extra_info("cipher")
            if not cipher or cipher[0] != REQUIRED_CIPHER:
                transport.abort()
                return
            super().connection_made(transport)

    return Aes256Only


def hardened_uvicorn_config(app: Any, host: str, port: int, cert_path: Path, key_path: Path) -> Any:
    import uvicorn
    from uvicorn.protocols.http.auto import AutoHTTPProtocol

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        http=aes256_only(AutoHTTPProtocol),
    )
    config.load()
    config.ssl = build_ssl_context(cert_path, key_path)  # replaces uvicorn's default TLS 1.2+ context
    return config


if __name__ == "__main__":
    from app.config import get_settings

    cert_path, key_path = ensure_self_signed_certificate(get_settings().cert_dir)
    print(f"cert: {cert_path}\nkey:  {key_path}")
