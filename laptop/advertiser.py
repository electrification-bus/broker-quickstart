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
    SECURE_MQTT_SERVICE_TYPE,
    TXTVERS,
)

from .certs import default_local_hostname, local_ip_addresses
from .profiles import DEFAULT_PROFILE, PROFILES, advertised_listeners


def default_device_id(hostname: str | None = None) -> str:
    """Stable per-laptop device id: the host's `.local` label (e.g. 'dcj-mbp')."""
    hostname = hostname or default_local_hostname()
    return hostname[: -len(".local")] if hostname.endswith(".local") else hostname


def build_service_info(
    service_type: str,
    port: int,
    hostname: str | None = None,
    device_id: str | None = None,
) -> ServiceInfo:
    """Build a ServiceInfo for one listener with framework.md-compliant TXT records.

    `_secure-mqtt._tcp` carries txtvers/protocol/broker/device_id; plain
    `_mqtt._tcp` carries only txtvers/protocol per the spec.
    """
    hostname = hostname or default_local_hostname()
    device_id = device_id or default_device_id(hostname)
    fq_type = f"{service_type}.local."

    if service_type == SECURE_MQTT_SERVICE_TYPE:
        properties = {
            "txtvers": TXTVERS,
            "protocol": MQTT_PROTOCOL_V5,
            "broker": hostname,
            "device_id": device_id,
        }
        label = f"eBus broker {device_id}"
    else:  # plain _mqtt._tcp
        properties = {"txtvers": TXTVERS, "protocol": MQTT_PROTOCOL_V5}
        label = f"eBus broker {device_id} (plaintext)"

    return ServiceInfo(
        type_=fq_type,
        name=f"{label}.{fq_type}",
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
) -> Iterator[list[ServiceInfo]]:
    """Advertise every service the profile enables, for the duration of the context.

    One mDNS record per advertised listener (e.g. discovery advertises both
    `_secure-mqtt._tcp` and `_mqtt._tcp`).
    """
    hostname = hostname or default_local_hostname()
    device_id = device_id or default_device_id(hostname)
    infos = [
        build_service_info(listener_.service_type, listener_.port, hostname, device_id)
        for listener_ in advertised_listeners(profile)
    ]
    zc = Zeroconf()
    for info in infos:
        zc.register_service(info)
    try:
        yield infos
    finally:
        for info in infos:
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
        help=f"Which services to advertise (default: {DEFAULT_PROFILE}). "
        "open advertises _mqtt._tcp; discovery advertises _secure-mqtt._tcp AND "
        "_mqtt._tcp; strict advertises _secure-mqtt._tcp.",
    )
    args = parser.parse_args(argv)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    with advertise(args.hostname, args.device_id, args.profile) as infos:
        for info in infos:
            txt = {k.decode(): v.decode() for k, v in info.properties.items() if v is not None}
            print(f"Advertising {info.name}", file=sys.stderr)
            print(f"  service: {info.type.rstrip('.')} on port {info.port}", file=sys.stderr)
            print(f"  TXT:     {txt}", file=sys.stderr)
        print(f"  server:  {infos[0].server.rstrip('.')}" if infos else "  (nothing to advertise)", file=sys.stderr)
        print("  Ctrl-C to stop (deregisters the records).", file=sys.stderr)
        stop.wait()
    print("Advertisement withdrawn.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
