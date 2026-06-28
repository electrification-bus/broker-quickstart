"""
Optional Mosquitto bridge to a remote broker (BQ-2l8).

A bridge forwards the local broker's eBus topic space to (and/or from) a REMOTE
broker, so a locally discovered publisher can reach a broker that is not on the
same LAN. It sits behind the local broker: it does not change the local
listeners or the mDNS advertisement.

This is the generic, vendor-neutral capability. HOW the remote address becomes
reachable (direct WAN TLS, a VPN, or an SSH tunnel mapping remote:8883 to
localhost) is a deployment transport concern, not a broker feature; the bridge
only needs a reachable `host:port`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BRIDGE_NAME = "ebus-remote"
DEFAULT_TOPIC = "ebus/#"
# Default to 'in' (pull remote -> local): the common case is bringing a remote
# broker's eBus topics onto this broker (e.g. a SPAN panel's broker onto the
# laptop). 'in' never publishes to the remote, so it is the safe default.
DEFAULT_DIRECTION = "in"
DIRECTIONS = ("out", "in", "both")
DEFAULT_QOS = 1


PROTOCOL_VERSIONS = ("mqttv31", "mqttv311", "mqttv50")


@dataclass(frozen=True)
class Bridge:
    """A Mosquitto bridge connection to a remote broker."""

    name: str
    host: str
    port: int
    topic: str
    direction: str  # out (local -> remote) | in | both
    qos: int
    cafile: Path | None = None  # CA validating the REMOTE broker (enables TLS to remote)
    certfile: Path | None = None  # client cert the remote trusts (mTLS to remote)
    keyfile: Path | None = None
    username: str | None = None  # username/password auth to the remote (spec's primary method)
    password: str | None = None
    clientid: str | None = None  # remote_clientid (else Mosquitto derives one)
    protocol_version: str | None = None  # mqttv31 | mqttv311 | mqttv50 (else Mosquitto default)
    insecure: bool = False  # skip remote-hostname check (e.g. reached via IP/tunnel)


def parse_address(address: str, on_error=None) -> tuple[str, int]:
    """Parse 'host:port' into (host, port), failing via on_error/ValueError."""

    def fail(msg: str):
        if on_error is not None:
            on_error(msg)
        raise ValueError(msg)

    host, sep, port_str = address.rpartition(":")
    if not sep or not host:
        fail(f"expected HOST:PORT, got {address!r}")
    try:
        return host, int(port_str)
    except ValueError:
        fail(f"port is not a number: {port_str!r}")
        raise  # pragma: no cover (fail raises)


def build_bridge(
    address: str | None,
    *,
    name: str = DEFAULT_BRIDGE_NAME,
    topic: str = DEFAULT_TOPIC,
    direction: str = DEFAULT_DIRECTION,
    qos: int = DEFAULT_QOS,
    cafile: Path | None = None,
    certfile: Path | None = None,
    keyfile: Path | None = None,
    username: str | None = None,
    password: str | None = None,
    protocol_version: str | None = None,
    insecure: bool = False,
    on_error=None,
) -> Bridge | None:
    """Parse `--bridge host:port` (+ options) into a Bridge, or None if unset.

    `on_error(msg)` is called for invalid input (e.g. argparse's `parser.error`);
    if not supplied, a ValueError is raised.
    """
    if address is None:
        return None

    def fail(msg: str):
        if on_error is not None:
            on_error(msg)
        raise ValueError(msg)

    host, port = parse_address(address, on_error=lambda m: fail(f"--bridge {m}"))

    if direction not in DIRECTIONS:
        fail(f"--bridge-direction must be one of {DIRECTIONS}, got {direction!r}")
    if (certfile is None) != (keyfile is None):
        fail("--bridge-certfile and --bridge-keyfile must be given together")
    if certfile is not None and cafile is None:
        fail("--bridge-certfile/--bridge-keyfile (mTLS to remote) require --bridge-cafile")
    if (password is not None) != (username is not None):
        fail("--bridge-username and a password (--bridge-password-file) must be given together")
    if protocol_version is not None and protocol_version not in PROTOCOL_VERSIONS:
        fail(f"--bridge-protocol-version must be one of {PROTOCOL_VERSIONS}")

    return Bridge(
        name=name,
        host=host,
        port=port,
        topic=topic,
        direction=direction,
        qos=qos,
        cafile=cafile,
        certfile=certfile,
        keyfile=keyfile,
        username=username,
        password=password,
        protocol_version=protocol_version,
        insecure=insecure,
    )


def add_bridge_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the --bridge* options to an argparse parser (shared by broker + run)."""
    group = parser.add_argument_group("remote-broker bridge (optional)")
    group.add_argument(
        "--bridge",
        metavar="HOST:PORT",
        default=None,
        help="Bridge the eBus topic space to a remote broker at HOST:PORT.",
    )
    group.add_argument(
        "--bridge-topic",
        default=DEFAULT_TOPIC,
        help=f"Topic pattern to bridge (default: {DEFAULT_TOPIC}).",
    )
    group.add_argument(
        "--bridge-direction",
        choices=DIRECTIONS,
        default=DEFAULT_DIRECTION,
        help=f"in=remote->local (pull), out=local->remote, both (default: {DEFAULT_DIRECTION}).",
    )
    group.add_argument(
        "--bridge-qos", type=int, default=DEFAULT_QOS, help=f"Bridge QoS (default: {DEFAULT_QOS})."
    )
    group.add_argument("--bridge-cafile", type=Path, default=None, help="CA validating the remote broker (TLS).")
    group.add_argument("--bridge-certfile", type=Path, default=None, help="Client cert for mTLS to the remote.")
    group.add_argument("--bridge-keyfile", type=Path, default=None, help="Client key for mTLS to the remote.")
    group.add_argument("--bridge-username", default=None, help="Username for username/password auth to the remote.")
    group.add_argument(
        "--bridge-password-file",
        type=Path,
        default=None,
        help="File containing the remote password (avoids exposing it on the command line).",
    )
    group.add_argument(
        "--bridge-protocol-version",
        choices=PROTOCOL_VERSIONS,
        default=None,
        help="MQTT version for the bridge connection (else Mosquitto's default).",
    )
    group.add_argument(
        "--bridge-insecure",
        action="store_true",
        help="Skip the remote-hostname check (e.g. when reaching the remote by IP or a tunnel).",
    )


def bridge_from_args(args: argparse.Namespace, on_error=None) -> Bridge | None:
    """Build a Bridge from parsed args (the names added by add_bridge_arguments)."""
    password = None
    if args.bridge_password_file is not None:
        password = Path(args.bridge_password_file).read_text().strip()
    return build_bridge(
        args.bridge,
        topic=args.bridge_topic,
        direction=args.bridge_direction,
        qos=args.bridge_qos,
        cafile=args.bridge_cafile,
        certfile=args.bridge_certfile,
        keyfile=args.bridge_keyfile,
        username=args.bridge_username,
        password=password,
        protocol_version=args.bridge_protocol_version,
        insecure=args.bridge_insecure,
        on_error=on_error,
    )
