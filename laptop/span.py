"""
Bridge to a SPAN panel's eBus broker (BQ-hwa).

A public, vendor-neutral-where-possible specialization of the generic remote
broker bridge (laptop/bridge.py) for SPAN panels. It uses only the PUBLIC SPAN
API: the documented credential file `~/.span-auth.json`, the cached per-panel CA
in `~/.span-ca-certs/`, and the panel's unauthenticated CA endpoint
`http://<host>/api/v2/certificate/ca`. No confidential detail lives here; the
panel(s) you target come from your own `~/.span-auth.json`.

The panel's eBus broker (port 8883) uses TLS plus username/password auth, where
the username is the panel serial and the password is `ebus_broker_password` from
the credential file. The default bridge direction is `in` (pull the panel's
`ebus/#` topics onto the local broker); it never publishes to the panel.

How the panel becomes reachable (same LAN, a VPN, or an SSH tunnel) is a
deployment concern, not part of this module: pass `--span-bridge-address` to
point the bridge at a tunnel's local endpoint instead of `<host>:8883`.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509

from .bridge import Bridge, parse_address

DEFAULT_AUTH_FILE = Path.home() / ".span-auth.json"
DEFAULT_CA_DIR = Path.home() / ".span-ca-certs"
PANEL_MQTTS_PORT = 8883
# The panel broker speaks MQTT 3.1.1.
PANEL_PROTOCOL_VERSION = "mqttv311"
# A day of slack, like the SPAN client, so we refresh a CA that is about to lapse.
_CA_RENEW_SLACK_DAYS = 1


@dataclass(frozen=True)
class Panel:
    serial: str
    hostname: str
    password: str


def load_panel(serial: str | None = None, *, auth_file: Path = DEFAULT_AUTH_FILE) -> Panel:
    """Read `~/.span-auth.json` and return the requested (or default) panel."""
    if not auth_file.exists():
        raise FileNotFoundError(
            f"{auth_file} not found. Configure SPAN credentials (e.g. `span-auth setup`) first."
        )
    data = json.loads(auth_file.read_text())
    panels = data.get("panels") or {}
    if not panels:
        raise ValueError(f"no panels in {auth_file}")

    target = serial or data.get("default_panel")
    if target is None:
        if len(panels) == 1:
            target = next(iter(panels))
        else:
            raise ValueError(
                f"no panel specified and no default_panel in {auth_file}; pass a serial."
            )
    if target not in panels:
        raise ValueError(f"panel {target!r} not in {auth_file}")

    creds = panels[target]
    password = creds.get("ebus_broker_password")
    if not password:
        raise ValueError(f"no ebus_broker_password for panel {target!r} in {auth_file}")
    hostname = creds.get("hostname") or f"span-{target}.local"
    return Panel(serial=target, hostname=hostname, password=password)


def _cert_expires_within(cert_path: Path, days: int) -> bool:
    import datetime

    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    cutoff = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
    return cert.not_valid_after_utc <= cutoff


def ensure_panel_ca(panel: Panel, *, ca_dir: Path = DEFAULT_CA_DIR, download: bool = True) -> Path:
    """Return the panel's CA path, (re)downloading from the panel if needed.

    The CA is cached at `<ca_dir>/<serial>.crt` (the SPAN client convention). When
    absent or near expiry, it is fetched from the panel's unauthenticated
    `http://<host>/api/v2/certificate/ca` endpoint.
    """
    ca_path = ca_dir / f"{panel.serial}.crt"
    if ca_path.exists() and not _cert_expires_within(ca_path, _CA_RENEW_SLACK_DAYS):
        return ca_path
    if not download:
        if ca_path.exists():
            return ca_path
        raise FileNotFoundError(f"panel CA not cached at {ca_path} and download disabled")

    url = f"http://{panel.hostname}/api/v2/certificate/ca"
    with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310 - documented panel endpoint
        pem = resp.read()
    ca_dir.mkdir(parents=True, exist_ok=True)
    ca_path.write_bytes(pem)
    return ca_path


def span_bridge(
    serial: str | None = None,
    *,
    address: str | None = None,
    direction: str = "in",
    topic: str = "ebus/#",
    qos: int = 0,
    insecure: bool | None = None,
    auth_file: Path = DEFAULT_AUTH_FILE,
    ca_dir: Path = DEFAULT_CA_DIR,
) -> Bridge:
    """Build a Bridge to a SPAN panel's eBus broker.

    `address` (host:port) overrides the panel's `<host>:8883`, e.g. to bridge
    through a tunnel's local endpoint. When an address override is used the cert
    hostname will not match, so `insecure` defaults to True in that case (the CA
    chain is still validated); otherwise it defaults to False.
    """
    panel = load_panel(serial, auth_file=auth_file)
    ca_path = ensure_panel_ca(panel, ca_dir=ca_dir)

    if address is not None:
        host, port = parse_address(address)
        if insecure is None:
            insecure = True  # reached by IP/tunnel: cert CN won't match
    else:
        host, port = panel.hostname, PANEL_MQTTS_PORT
        if insecure is None:
            insecure = False

    return Bridge(
        name=f"span-{panel.serial}",
        host=host,
        port=port,
        topic=topic,
        direction=direction,
        qos=qos,
        cafile=ca_path,
        username=panel.serial,
        password=panel.password,
        clientid=f"ebus-laptop-{panel.serial}",
        protocol_version=PANEL_PROTOCOL_VERSION,
        insecure=insecure,
    )


def add_span_bridge_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the --span-bridge options (shared by broker + run)."""
    group = parser.add_argument_group("SPAN panel bridge (optional)")
    group.add_argument(
        "--span-bridge",
        nargs="?",
        const="",
        default=None,
        metavar="SERIAL",
        help="Bridge a SPAN panel's eBus broker onto the local broker (pull, direction in). "
        "Omit SERIAL to use the default panel from ~/.span-auth.json.",
    )
    group.add_argument(
        "--span-bridge-address",
        default=None,
        metavar="HOST:PORT",
        help="Reach the panel broker at HOST:PORT instead of <host>:8883 "
        "(e.g. a tunnel's local endpoint).",
    )


def span_bridge_from_args(args: argparse.Namespace, on_error=None) -> Bridge | None:
    """Build a SPAN-panel Bridge from parsed args, or None if --span-bridge unset."""
    if getattr(args, "span_bridge", None) is None:
        return None
    serial = args.span_bridge or None  # "" (bare flag) -> default panel
    try:
        return span_bridge(serial, address=args.span_bridge_address)
    except (OSError, ValueError) as exc:
        if on_error is not None:
            on_error(str(exc))
        raise
