"""HTTPS certificates: an internal certificate authority for sites without a company PKI, import of a certificate
issued by IT (.pfx / .p12), and certificate checks (names, expiry).

Files (BI_TLS_DIR, default data/tls):
    ca.crt / ca.key        internal certificate authority (make-cert only) — install ca.crt on the workstations,
                           keep ca.key offline once the server certificate is made
    server.crt / server.key   certificate presented by the server (point BI_TLS_CERT / BI_TLS_KEY at them)
"""
from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

WARN_DAYS = 30
MAX_SERVER_DAYS = 397  # browsers refuse server certificates valid longer than ~13 months


class TlsError(Exception):
    pass


@dataclass
class CertInfo:
    subject: str
    issuer: str
    names: list[str]
    not_after: datetime
    days_left: int
    self_signed: bool

    def as_dict(self) -> dict:
        return {"subject": self.subject, "issuer": self.issuer, "names": self.names, "expires": self.not_after.isoformat(),
                "days_left": self.days_left, "expiring_soon": self.days_left < WARN_DAYS, "self_signed": self.self_signed}


def _write_private(path: Path, data: bytes) -> None:
    """Private key file readable by the owner only (POSIX); on Windows the data folder ACL applies (see DEPLOYMENT.md)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _key_pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def default_names() -> tuple[list[str], list[str]]:
    """This computer's host name, full name and IPv4 addresses."""
    dns, ips = set(), set()
    try:
        hn = socket.gethostname()
        dns.update({hn.lower(), socket.getfqdn().lower()})
        for info in socket.getaddrinfo(hn, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    dns.discard("")
    dns.discard("localhost")
    return sorted(dns), sorted(ips)


def _san(dns: list[str], ips: list[str]) -> x509.SubjectAlternativeName:
    entries: list[x509.GeneralName] = [x509.DNSName(d) for d in dns]
    for ip in ips:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError as e:
            raise TlsError(f"Not an IP address: {ip}") from e
    if not entries:
        raise TlsError("At least one DNS name or IP address is required")
    return x509.SubjectAlternativeName(entries)


def make_ca(tls_dir: Path, org: str = "Blasting Intelligence (site)", days: int = 3650) -> Path:
    """Internal CA (EC P-256, 10 years). Not overwritten if it exists."""
    crt, key_path = tls_dir / "ca.crt", tls_dir / "ca.key"
    if crt.exists() and key_path.exists():
        return crt
    if crt.exists():
        raise TlsError(f"{crt} exists but its key ca.key is not in {tls_dir} (kept offline?) — copy it back to sign a new "
                       "server certificate. Making a new CA would require re-installing ca.crt on every workstation.")
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, org),
                      x509.NameAttribute(NameOID.COMMON_NAME, f"{org} — internal CA")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=days))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _write_private(key_path, _key_pem(key))
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return crt


def make_server_cert(tls_dir: Path, dns: list[str], ips: list[str], days: int = 365) -> tuple[Path, Path]:
    """Server certificate signed by the internal CA (created if needed) for the given names."""
    if days > MAX_SERVER_DAYS:
        raise TlsError(f"Validity limited to {MAX_SERVER_DAYS} days (browser rule)")
    make_ca(tls_dir)
    ca_key = serialization.load_pem_private_key((tls_dir / "ca.key").read_bytes(), None)
    ca = x509.load_pem_x509_certificate((tls_dir / "ca.crt").read_bytes())
    key = ec.generate_private_key(ec.SECP256R1())
    cn = (dns or ips)[0]
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
            .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=days))
            .add_extension(_san(dns, ips), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, content_commitment=False,
                                         data_encipherment=False, key_agreement=True, key_cert_sign=False, crl_sign=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    crt_path, key_path = tls_dir / "server.crt", tls_dir / "server.key"
    _write_private(key_path, _key_pem(key))
    crt_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM))
    return crt_path, key_path


def import_pfx(tls_dir: Path, pfx: Path, password: str | None) -> tuple[Path, Path]:
    """Certificate issued by the company PKI (.pfx/.p12) → server.crt (with chain) and server.key (PEM)."""
    try:
        key, cert, extra = pkcs12.load_key_and_certificates(pfx.read_bytes(), password.encode() if password else None)
    except ValueError as e:
        raise TlsError(f"Cannot open {pfx.name}: wrong password or not a PKCS#12 file") from e
    if key is None or cert is None:
        raise TlsError(f"{pfx.name} must contain the certificate and its private key")
    if not isinstance(key, (rsa.RSAPrivateKey, ec.EllipticCurvePrivateKey)):
        raise TlsError("Unsupported key type (RSA or EC expected)")
    chain = cert.public_bytes(serialization.Encoding.PEM) + b"".join(c.public_bytes(serialization.Encoding.PEM) for c in (extra or []))
    crt_path, key_path = tls_dir / "server.crt", tls_dir / "server.key"
    _write_private(key_path, _key_pem(key))
    crt_path.write_bytes(chain)
    return crt_path, key_path


def cert_info(path: Path | str) -> CertInfo:
    try:
        cert = x509.load_pem_x509_certificates(Path(path).read_bytes())[0]
    except (OSError, ValueError) as e:
        raise TlsError(f"Cannot read certificate {path}: {e}") from e
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = [*san.get_values_for_type(x509.DNSName), *(str(i) for i in san.get_values_for_type(x509.IPAddress))]
    except x509.ExtensionNotFound:
        names = []
    end = cert.not_valid_after_utc
    return CertInfo(subject=cert.subject.rfc4514_string(), issuer=cert.issuer.rfc4514_string(), names=names, not_after=end,
                    days_left=(end - datetime.now(UTC)).days, self_signed=cert.subject == cert.issuer)


def check_pair(cert_path: str, key_path: str, password: str | None = None) -> CertInfo:
    """The certificate and key exist, match and the certificate is currently valid."""
    info = cert_info(cert_path)
    try:
        key = serialization.load_pem_private_key(Path(key_path).read_bytes(), password.encode() if password else None)
    except (OSError, ValueError, TypeError) as e:
        raise TlsError(f"Cannot read private key {key_path}: {e}") from e
    cert = x509.load_pem_x509_certificates(Path(cert_path).read_bytes())[0]
    pub = lambda k: k.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)  # noqa: E731
    if pub(cert.public_key()) != pub(key.public_key()):
        raise TlsError("The private key does not belong to the certificate")
    if info.days_left < 0:
        raise TlsError(f"Certificate expired on {info.not_after:%Y-%m-%d}")
    return info
