"""Starts a real HTTPS server with the hardened configuration and probes it with real TLS clients."""

import asyncio
import shutil
import socket
import ssl
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from app.tls import (
    REQUIRED_CIPHER,
    TlsConfigError,
    ensure_self_signed_certificate,
    hardened_uvicorn_config,
    validate_ec_certificate,
)


async def _app(scope, receive, send) -> None:  # noqa: ANN001
    if scope["type"] != "http":
        return
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"2")]})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest_asyncio.fixture
async def server(tmp_path: Path) -> AsyncIterator[int]:
    cert, key = ensure_self_signed_certificate(tmp_path / "certs")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    instance = uvicorn.Server(hardened_uvicorn_config(_app, "127.0.0.1", port, cert, key))
    task = asyncio.create_task(instance.serve())
    while not instance.started:
        await asyncio.sleep(0.01)
    yield port
    instance.should_exit = True
    await task


def _client_context(**versions: ssl.TLSVersion) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    for name, value in versions.items():
        setattr(context, name, value)
    return context


async def _handshake(port: int, context: ssl.SSLContext) -> tuple[str, str]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port, ssl=context)
    try:
        ssl_object = writer.get_extra_info("ssl_object")
        return ssl_object.version(), ssl_object.cipher()[0]
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_tls13_with_aes256_gcm_is_negotiated(server: int) -> None:
    assert await _handshake(server, _client_context()) == ("TLSv1.3", REQUIRED_CIPHER)


@pytest.mark.asyncio
async def test_tls12_and_older_are_refused(server: int) -> None:
    context = _client_context(maximum_version=ssl.TLSVersion.TLSv1_2)
    with pytest.raises((ssl.SSLError, ConnectionError)):
        await _handshake(server, context)


async def _s_client(port: int, *args: str) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "openssl",
        "s_client",
        "-connect",
        f"127.0.0.1:{port}",
        "-tls1_3",
        "-quiet",
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await asyncio.wait_for(
        process.communicate(b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"), 15
    )
    return output


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")
async def test_aes256_gcm_clients_are_served_but_clients_offering_only_another_cipher_are_dropped(
    server: int,
) -> None:
    assert b"HTTP/1.1 200" in await _s_client(server, "-ciphersuites", REQUIRED_CIPHER)
    for suite in ("TLS_AES_128_GCM_SHA256", "TLS_CHACHA20_POLY1305_SHA256"):
        assert b"HTTP/1.1 200" not in await _s_client(server, "-ciphersuites", suite), suite


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")
async def test_a_hybrid_post_quantum_group_is_used_when_the_client_offers_it(server: int) -> None:
    process = await asyncio.create_subprocess_exec(
        "openssl",
        "s_client",
        "-connect",
        f"127.0.0.1:{server}",
        "-tls1_3",
        "-groups",
        "X25519MLKEM768",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await asyncio.wait_for(process.communicate(b""), 15)
    assert b"Negotiated TLS1.3 group: X25519MLKEM768" in output


def _write_cert(path: Path, key: ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey) -> Path:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "t")])
    import datetime

    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA384())
    )
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path


def test_rsa_certificates_are_refused_and_ec_ones_accepted(tmp_path: Path) -> None:
    rsa_cert = _write_cert(tmp_path / "rsa.pem", rsa.generate_private_key(65537, 2048))
    with pytest.raises(TlsConfigError):
        validate_ec_certificate(rsa_cert)
    validate_ec_certificate(_write_cert(tmp_path / "ec.pem", ec.generate_private_key(ec.SECP384R1())))
    weak = _write_cert(tmp_path / "weak.pem", ec.generate_private_key(ec.SECP224R1()))
    with pytest.raises(TlsConfigError):
        validate_ec_certificate(weak)


@pytest.mark.asyncio
async def test_a_pinned_device_certificate_is_trusted_and_any_other_is_not(
    server: int, tmp_path: Path
) -> None:
    from app.integrations.tls import httpx_verify

    pinned = httpx_verify(False, (tmp_path / "certs" / "cert.pem").read_text())
    assert isinstance(pinned, ssl.SSLContext)
    reader, writer = await asyncio.open_connection("127.0.0.1", server, ssl=pinned)
    writer.close()
    await writer.wait_closed()

    other_cert, _ = ensure_self_signed_certificate(tmp_path / "other")
    wrong = httpx_verify(False, other_cert.read_text())
    assert isinstance(wrong, ssl.SSLContext)
    with pytest.raises(ssl.SSLCertVerificationError):
        await asyncio.open_connection("127.0.0.1", server, ssl=wrong)
