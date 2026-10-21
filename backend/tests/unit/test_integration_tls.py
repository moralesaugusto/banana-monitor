import datetime
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.integrations.adguard_home.client import AdGuardHomeClient
from app.integrations.adguard_home.plugin import AdGuardHomeConfig
from app.integrations.omada.plugin import OmadaConfig
from app.integrations.tls import httpx_verify, normalize_pem


def _pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "device")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_certificates_are_verified_by_default() -> None:
    assert AdGuardHomeConfig(host="h").verify_tls is True
    assert OmadaConfig(host="h").verify_tls is True


def test_adguard_stays_plain_http_on_its_own_port_but_uses_https_when_asked() -> None:
    assert AdGuardHomeClient("h", 3000, "u", "p")._base_url == "http://h:3000"
    assert AdGuardHomeClient("h", 443, "u", "p")._base_url == "https://h:443"
    assert AdGuardHomeClient("h", 3000, "u", "p", use_https=True)._base_url == "https://h:3000"
    assert AdGuardHomeClient("h", 3000, "u", "p", ca_pem=_pem())._base_url == "https://h:3000"


def test_a_pasted_certificate_survives_losing_its_line_breaks() -> None:
    pem = _pem()
    one_line = pem.replace("\n", " ")
    assert normalize_pem(one_line) == pem
    assert normalize_pem("junk\n" + pem + "\nmore junk") == pem


def test_something_that_is_not_a_certificate_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_pem("hello")
    with pytest.raises(ValueError):
        AdGuardHomeConfig(host="h", tls_ca_pem="hello")
    with pytest.raises(ValueError):
        OmadaConfig(host="h", tls_ca_pem="-----BEGIN CERTIFICATE-----!!!-----END CERTIFICATE-----")


def test_a_pinned_certificate_becomes_the_only_trusted_root() -> None:
    assert httpx_verify(True) is True
    assert httpx_verify(False) is False
    context = httpx_verify(False, _pem())  # the pin wins over the on/off switch
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is False


def test_an_untrusted_certificate_error_says_what_to_do_about_it() -> None:
    from app.integrations.tls import explain

    message = explain(
        Exception("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate")
    )
    assert "tls_ca_pem" in message and "verify_tls" in message
    assert explain(Exception("connection refused")) == "connection refused"


def test_proxmox_can_pin_a_certificate_too() -> None:
    from app.integrations.proxmox.plugin import ProxmoxConfig

    assert ProxmoxConfig(host="h", token_id="t", tls_ca_pem=_pem()).tls_ca_pem
    with pytest.raises(ValueError):
        ProxmoxConfig(host="h", token_id="t", tls_ca_pem="nope")
