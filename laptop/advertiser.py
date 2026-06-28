"""
Advertise the laptop broker over mDNS host-native on macOS (BQ-a6r).

On macOS, mDNSResponder/Bonjour owns mDNS and Avahi (the Pi path's backend)
cannot run, so the laptop path uses python-zeroconf, which coexists with
mDNSResponder. For the MVP this advertises `_secure-mqtt._tcp` on 8883 with the
TXT records framework.md §"MQTT Broker Advertisement" requires:

    txtvers=1, protocol=mqtt-v5, broker=<host>.local, device_id=<stable id>

It rides the host's existing `<host>.local` (the SRV target points at the name
Bonjour already publishes) rather than claiming a new `.local` A-record. The
profile-aware service type (open vs discovery vs strict) is a later concern; this
targets the mTLS advertisement the publisher needs to discover the broker.

The advertiser deregisters cleanly on Ctrl-C / SIGTERM so the one-command runner
(BQ-x8v) can tear it down and the mDNS record disappears.
"""

from __future__ import annotations

import argparse
import contextlib
import signal
import sys
import threading
from collections.abc import Iterator

from zeroconf import ServiceInfo, Zeroconf

from mdns.constants import (
    MQTT_PLAIN_PORT,
    MQTT_PROTOCOL_V5,
    MQTTS_PORT,
    PLAIN_MQTT_SERVICE_TYPE,
    SECURE_MQTT_SERVICE_TYPE,
    TXTVERS,
)

from .certs import default_local_hostname, local_ip_addresses
from .profiles import DEFAULT_PROFILE, OPEN, PROFILES


def default_device_id(hostname: str | None = None) -> str:
    """Stable per-laptop device id: the host's `.local` label (e.g. 'dcj-mbp')."""
    hostname = hostname or default_local_hostname()
    return hostname[: -len(".local")] if hostname.endswith(".local") else hostname


def _service_for_profile(profile: str) -> tuple[str, int, str]:
    """Return (fully-qualified service type, port, instance-label tag) for a profile.

    open advertises plaintext `_mqtt._tcp` on 1883; the TLS profiles advertise
    `_secure-mqtt._tcp` on 8883.
    """
    if profile == OPEN:
        return f"{PLAIN_MQTT_SERVICE_TYPE}.local.", MQTT_PLAIN_PORT, "[OPEN] "
    return f"{SECURE_MQTT_SERVICE_TYPE}.local.", MQTTS_PORT, ""


def build_service_info(
    hostname: str | None = None,
    device_id: str | None = None,
    profile: str = DEFAULT_PROFILE,
    port: int | None = None,
) -> ServiceInfo:
    """Build the ServiceInfo for `profile` with framework.md-compliant TXT records.

    `_secure-mqtt._tcp` carries txtvers/protocol/broker/device_id; plain
    `_mqtt._tcp` carries only txtvers/protocol per the spec.
    """
    hostname = hostname or default_local_hostname()
    device_id = device_id or default_device_id(hostname)
    service_type, default_port, tag = _service_for_profile(profile)
    port = default_port if port is None else port

    if profile == OPEN:
        properties = {"txtvers": TXTVERS, "protocol": MQTT_PROTOCOL_V5}
    else:
        properties = {
            "txtvers": TXTVERS,
            "protocol": MQTT_PROTOCOL_V5,
            "broker": hostname,
            "device_id": device_id,
        }
    return ServiceInfo(
        type_=service_type,
        name=f"eBus broker {tag}{device_id}.{service_type}",
        addresses=[ip.packed for ip in local_ip_addresses()],
        port=port,
        properties=properties,
        # Ride the host's existing <host>.local rather than claim a new A-record.
        server=f"{hostname}.",
    )


@contextlib.contextmanager
def advertise(
    hostname: str | None = None,
    device_id: str | None = None,
    profile: str = DEFAULT_PROFILE,
    port: int | None = None,
) -> Iterator[ServiceInfo]:
    """Register the broker advertisement for the duration of the context."""
    info = build_service_info(hostname, device_id, profile, port)
    zc = Zeroconf()
    zc.register_service(info)
    try:
        yield info
    finally:
        zc.unregister_service(info)
        zc.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--hostname",
        default=None,
        help="Broker hostname to advertise (default: this host's Bonjour <name>.local).",
    )
    parser.add_argument(
        "--device-id",
        default=None,
        help="Stable device id for the TXT record (default: the host's .local label).",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default=DEFAULT_PROFILE,
        help=f"Which service to advertise (default: {DEFAULT_PROFILE}). "
        "open advertises _mqtt._tcp:1883; the TLS profiles advertise _secure-mqtt._tcp:8883.",
    )
    parser.add_argument("--port", type=int, default=None, help="Override the advertised port.")
    args = parser.parse_args(argv)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    with advertise(args.hostname, args.device_id, args.profile, args.port) as info:
        txt = {k.decode(): v.decode() for k, v in info.properties.items() if v is not None}
        print(f"Advertising {info.name}", file=sys.stderr)
        print(f"  service: {info.type.rstrip('.')} on port {info.port}", file=sys.stderr)
        print(f"  server:  {info.server.rstrip('.')}", file=sys.stderr)
        print(f"  TXT:     {txt}", file=sys.stderr)
        print("  Ctrl-C to stop (deregisters the record).", file=sys.stderr)
        stop.wait()
    print("Advertisement withdrawn.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
