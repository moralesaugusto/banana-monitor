from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509

from app.tls import ensure_self_signed_certificate


def test_generates_ec_cert_and_key(tmp_path: Path) -> None:
    cert_dir = tmp_path / "certificates"
    cert_path, key_path = ensure_self_signed_certificate(cert_dir, common_name="example.local")

    assert cert_path == cert_dir / "cert.pem"
    assert key_path == cert_dir / "key.pem"
    assert cert_path.exists()
    assert key_path.exists()
    assert (key_path.stat().st_mode & 0o777) == 0o600

    certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
    assert certificate.subject.rfc4514_string() == "CN=example.local"
    assert certificate.not_valid_after_utc > datetime.now(UTC)

    san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "example.local" in san.get_values_for_type(x509.DNSName)
    assert "localhost" in san.get_values_for_type(x509.DNSName)

    basic_constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert basic_constraints.ca is False


def test_is_idempotent(tmp_path: Path) -> None:
    cert_dir = tmp_path / "certificates"
    cert_path, key_path = ensure_self_signed_certificate(cert_dir)
    first_cert_bytes = cert_path.read_bytes()
    first_key_bytes = key_path.read_bytes()

    ensure_self_signed_certificate(cert_dir)

    assert cert_path.read_bytes() == first_cert_bytes
    assert key_path.read_bytes() == first_key_bytes
