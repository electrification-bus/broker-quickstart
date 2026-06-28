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


@dataclass(frozen=True)
class Bridge:
    """A Mosquitto bridge connection to a remote broker."""

    name: str
    host: str
    port: int
    topic: str
    direction: str  # out (local -> remote) | in | both
    qos: int
    cafile: Path | None  # CA validating the REMOTE broker (enables TLS to remote)
    certfile: Path | None  # client cert the remote trusts (mTLS to remote)
    keyfile: Path | None


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

    host, sep, port_str = address.rpartition(":")
    if not sep or not host:
        fail(f"--bridge expects HOST:PORT, got {address!r}")
    try:
        port = int(port_str)
    except ValueError:
        fail(f"--bridge port is not a number: {port_str!r}")
        return None  # pragma: no cover (fail raises)

    if direction not in DIRECTIONS:
        fail(f"--bridge-direction must be one of {DIRECTIONS}, got {direction!r}")
    if (certfile is None) != (keyfile is None):
        fail("--bridge-certfile and --bridge-keyfile must be given together")
    if certfile is not None and cafile is None:
        fail("--bridge-certfile/--bridge-keyfile (mTLS to remote) require --bridge-cafile")

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


def bridge_from_args(args: argparse.Namespace, on_error=None) -> Bridge | None:
    """Build a Bridge from parsed args (the names added by add_bridge_arguments)."""
    return build_bridge(
        args.bridge,
        topic=args.bridge_topic,
        direction=args.bridge_direction,
        qos=args.bridge_qos,
        cafile=args.bridge_cafile,
        certfile=args.bridge_certfile,
        keyfile=args.bridge_keyfile,
        on_error=on_error,
    )
