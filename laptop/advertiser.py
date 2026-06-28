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
    MQTT_PROTOCOL_V5,
    MQTTS_PORT,
    SECURE_MQTT_SERVICE_TYPE,
    TXTVERS,
)

from .certs import default_local_hostname, local_ip_addresses

# zeroconf wants the fully qualified service type with the trailing '.local.'.
_SERVICE_TYPE = f"{SECURE_MQTT_SERVICE_TYPE}.local."


def default_device_id(hostname: str | None = None) -> str:
    """Stable per-laptop device id: the host's `.local` label (e.g. 'dcj-mbp')."""
    hostname = hostname or default_local_hostname()
    return hostname[: -len(".local")] if hostname.endswith(".local") else hostname


def build_service_info(
    hostname: str | None = None,
    device_id: str | None = None,
    port: int = MQTTS_PORT,
) -> ServiceInfo:
    """Build the `_secure-mqtt._tcp` ServiceInfo with spec-compliant TXT records."""
    hostname = hostname or default_local_hostname()
    device_id = device_id or default_device_id(hostname)
    label = device_id  # human-readable instance label (no dots, safe for DNS-SD)

    properties = {
        "txtvers": TXTVERS,
        "protocol": MQTT_PROTOCOL_V5,
        "broker": hostname,
        "device_id": device_id,
    }
    return ServiceInfo(
        type_=_SERVICE_TYPE,
        name=f"eBus broker {label}.{_SERVICE_TYPE}",
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
    port: int = MQTTS_PORT,
) -> Iterator[ServiceInfo]:
    """Register the broker advertisement for the duration of the context."""
    info = build_service_info(hostname, device_id, port)
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
    parser.add_argument("--port", type=int, default=MQTTS_PORT)
    args = parser.parse_args(argv)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    with advertise(args.hostname, args.device_id, args.port) as info:
        print(f"Advertising {info.name}", file=sys.stderr)
        print(f"  type:      {SECURE_MQTT_SERVICE_TYPE} on port {args.port}", file=sys.stderr)
        print(f"  broker:    {info.properties[b'broker'].decode()}", file=sys.stderr)
        print(f"  device_id: {info.properties[b'device_id'].decode()}", file=sys.stderr)
        print("  Ctrl-C to stop (deregisters the record).", file=sys.stderr)
        stop.wait()
    print("Advertisement withdrawn.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
