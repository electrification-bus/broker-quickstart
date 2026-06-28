"""
Dev TLS material for the laptop broker (Mac MVP).

Mints a self-signed dev CA, a Mosquitto server certificate, and client
certificates into user-writable paths with no root required. The X.509 shapes
(EC P-256 keys, the server SAN + SERVER_AUTH EKU, the CA basic-constraints /
key-usage) mirror the upstream `tls-certificate-manager` so the trust surface a
publisher sees against this laptop broker is identical to a real eBus broker
host. The laptop specialization is only: an explicit hostname (the host's
Bonjour `<name>.local` rather than `socket.gethostname()`), user-writable paths,
and no systemd / netifaces / root.

The server cert SAN MUST include the advertised `<host>.local` name or the
publisher's TLS validation of the mDNS-discovered broker fails (see BQ-zu8).

Generic cert-minting is meant to live upstream (BQ-w1k). When
`tls-certificate-manager` is packaged importable and path-parameterized, this
module should shrink to a thin caller.
"""

from __future__ import annotations

import datetime
import ipaddress
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# Validity periods (days). Generous CA, short-ish leaf certs; all dev-only.
CA_VALIDITY_DAYS = 3650
SERVER_VALIDITY_DAYS = 825
CLIENT_VALIDITY_DAYS = 397

# Shared issuer/subject organization fields, matching the upstream dev CA style.
_ORG = "eBus Laptop Dev"


def default_local_hostname() -> str:
    """Return the `<name>.local` name Bonjour publishes for this host.

    On macOS the authoritative source is `scutil --get LocalHostName`; Bonjour
    advertises `<LocalHostName>.local` regardless of what `socket.gethostname()`
    happens to return (which may be a DHCP-assigned or truncated name). Fall back
    to `socket.gethostname()` on non-Mac hosts or if scutil is unavailable.
    """
    try:
        out = subprocess.run(
            ["scutil", "--get", "LocalHostName"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        name = out.stdout.strip()
        if out.returncode == 0 and name:
            return f"{name}.local"
    except (OSError, subprocess.SubprocessError):
        pass

    name = socket.gethostname()
    if not name.endswith(".local"):
        name = f"{name}.local"
    return name


def local_ip_addresses() -> list[ipaddress._BaseAddress]:
    """Return this host's routable IPv4/IPv6 addresses for the server cert SAN.

    Prefers `ifaddr` (cross-platform, already a transitive dep via python-zeroconf
    for the mDNS advertiser); falls back to stdlib if it is unavailable. Loopback,
    link-local, unspecified, and multicast addresses are filtered out: loopback is
    added to the SAN unconditionally, and the rest are not useful to a client. A
    client that connects to the broker by IP (rather than by `<host>.local`) can
    then still validate the cert.
    """
    found: set[str] = set()
    try:
        import ifaddr

        for adapter in ifaddr.get_adapters():
            for ip in adapter.ips:
                found.add(ip.ip if ip.is_IPv4 else ip.ip[0])
    except Exception:  # noqa: BLE001 - any ifaddr failure falls back to stdlib
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                found.add(info[4][0])
        except OSError:
            pass
        # Primary outbound IPv4: a UDP "connect" assigns a source address without
        # sending any packets.
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("192.0.2.1", 53))  # TEST-NET-1, never actually reached
            found.add(sock.getsockname()[0])
            sock.close()
        except OSError:
            pass

    result: list[ipaddress._BaseAddress] = []
    for raw in found:
        try:
            obj = ipaddress.ip_address(raw.split("%")[0])  # strip IPv6 zone id
        except ValueError:
            continue
        if obj.is_loopback or obj.is_link_local or obj.is_unspecified or obj.is_multicast:
            continue
        result.append(obj)
    return sorted(set(result), key=str)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _new_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _write_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    path.chmod(0o644)


def _load_key(path: Path) -> ec.EllipticCurvePrivateKey:
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def _load_cert(path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(path.read_bytes())


@dataclass(frozen=True)
class CertPaths:
    """User-writable layout for the laptop broker's TLS material."""

    root: Path

    @property
    def ca_cert(self) -> Path:
        return self.root / "ca" / "ca.crt"

    @property
    def ca_key(self) -> Path:
        return self.root / "ca" / "ca.key"

    @property
    def server_cert(self) -> Path:
        return self.root / "server" / "server.crt"

    @property
    def server_key(self) -> Path:
        return self.root / "server" / "server.key"

    def client_cert(self, client_id: str) -> Path:
        return self.root / "clients" / client_id / "client.crt"

    def client_key(self, client_id: str) -> Path:
        return self.root / "clients" / client_id / "client.key"


def ensure_ca(paths: CertPaths, *, regenerate: bool = False) -> x509.Certificate:
    """Create the dev CA if absent (idempotent). Returns the CA certificate."""
    if paths.ca_cert.exists() and paths.ca_key.exists() and not regenerate:
        return _load_cert(paths.ca_cert)

    key = _new_key()
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, _ORG),
            x509.NameAttribute(NameOID.COMMON_NAME, "eBus Laptop Dev CA"),
        ]
    )
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now())
        .not_valid_after(_now() + datetime.timedelta(days=CA_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(ski, critical=False)
        .sign(key, hashes.SHA256())
    )
    _write_key(paths.ca_key, key)
    _write_cert(paths.ca_cert, cert)
    return cert


def ensure_server_cert(
    paths: CertPaths,
    hostname: str,
    *,
    regenerate: bool = False,
) -> x509.Certificate:
    """Create the server cert (SAN includes `hostname` + local IPs) if absent or stale.

    Regenerates when the existing cert's SAN does not contain `hostname` (the
    laptop moved to a different `.local` name) or when a current routable IP is
    not yet covered (the laptop joined a new network), so the broker never serves
    a cert the publisher will reject. A SAN IP that has since disappeared is left
    in place: harmless, and avoids needless churn.
    """
    ca_cert = ensure_ca(paths)
    ca_key = _load_key(paths.ca_key)

    current_ips = local_ip_addresses()
    if paths.server_cert.exists() and paths.server_key.exists() and not regenerate:
        existing = _load_cert(paths.server_cert)
        san = existing.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        dns_ok = hostname in san.get_values_for_type(x509.DNSName)
        cert_ips = set(san.get_values_for_type(x509.IPAddress))
        if dns_ok and set(current_ips) <= cert_ips:
            return existing

    key = _new_key()
    san_list: list[x509.GeneralName] = [
        x509.DNSName(hostname),
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        x509.IPAddress(ipaddress.ip_address("::1")),
    ]
    san_list.extend(x509.IPAddress(ip) for ip in current_ips)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, _ORG),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now())
        .not_valid_after(_now() + datetime.timedelta(days=SERVER_VALIDITY_DAYS))
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=True,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(paths.server_key, key)
    _write_cert(paths.server_cert, cert)
    return cert


def mint_client_cert(
    paths: CertPaths,
    client_id: str,
    *,
    regenerate: bool = False,
) -> tuple[Path, Path]:
    """Mint a client cert (CN=client_id, CLIENT_AUTH EKU) signed by the dev CA.

    With Mosquitto's `use_identity_as_username`, the CN becomes the MQTT
    username. Returns (cert_path, key_path).
    """
    cert_path = paths.client_cert(client_id)
    key_path = paths.client_key(client_id)
    if cert_path.exists() and key_path.exists() and not regenerate:
        return cert_path, key_path

    ca_cert = ensure_ca(paths)
    ca_key = _load_key(paths.ca_key)

    key = _new_key()
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, _ORG),
            x509.NameAttribute(NameOID.COMMON_NAME, client_id),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now())
        .not_valid_after(_now() + datetime.timedelta(days=CLIENT_VALIDITY_DAYS))
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=True,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(key_path, key)
    _write_cert(cert_path, cert)
    return cert_path, key_path


def _san_summary(cert: x509.Certificate) -> str:
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    dns = san.get_values_for_type(x509.DNSName)
    ips = [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
    return ", ".join(dns + ips)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Mint dev CA + server (+ optional client) certs for the laptop broker."
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("state/laptop"),
        help="Root for TLS material (default: ./state/laptop).",
    )
    parser.add_argument(
        "--hostname",
        default=None,
        help="Advertised <host>.local name for the server cert SAN "
        "(default: this host's Bonjour LocalHostName).",
    )
    parser.add_argument(
        "--client",
        action="append",
        default=[],
        metavar="CLIENT_ID",
        help="Also mint a client cert with this CN (repeatable).",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Replace the server + client (leaf) certs, keeping the CA.",
    )
    parser.add_argument(
        "--regenerate-ca",
        action="store_true",
        help="Also replace the dev CA. This orphans every previously minted "
        "client cert (they will no longer be trusted) and forces a new server "
        "cert, so re-mint client certs afterward.",
    )
    args = parser.parse_args(argv)

    hostname = args.hostname or default_local_hostname()
    paths = CertPaths(root=args.state_dir.resolve())

    # A fresh CA invalidates every leaf signed by the old one, so re-mint leaves.
    regen_leaf = args.regenerate or args.regenerate_ca

    ensure_ca(paths, regenerate=args.regenerate_ca)
    server = ensure_server_cert(paths, hostname, regenerate=regen_leaf)

    print(f"CA:     {paths.ca_cert}")
    print(f"Server: {paths.server_cert}")
    print(f"  SAN:  {_san_summary(server)}")
    for client_id in args.client:
        cert_path, _ = mint_client_cert(paths, client_id, regenerate=regen_leaf)
        print(f"Client: {cert_path}  (CN={client_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
