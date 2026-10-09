"""
Advertise the laptop broker over mDNS host-native on macOS (BQ-a6r, BQ-q2y).

Advertising is ebus-service-discovery's `Advertiser`: one record per listener
the profile advertises (`_secure-mqtt._tcp`, `_mqtt._tcp`) with the TXT records
framework.md §"MQTT Broker Advertisement" requires, plus the `_ebus._tcp` and
`_device-info._tcp` records every eBus entity advertises, with
`roles=broker-host`. All share the instance name `eBus broker <device id>`.

The SRV target is the host's own `<host>.local`, and no address records are
published under it: mDNSResponder already answers for that name, with each
interface's own address, so a LAN client and a container on the Mac each get
an address they can reach. A `--hostname` other than the host's own is published
with this host's addresses, since nothing else answers for it.

The advertiser deregisters cleanly on Ctrl-C / SIGTERM so the one-command runner
(BQ-x8v) can tear it down and the mDNS records disappear.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading

from ebus_service_discovery import ebus, mdns

from .certs import default_local_hostname, local_ip_addresses
from .profiles import DEFAULT_PROFILE, PROFILES, advertised_listeners


def default_device_id(hostname: str | None = None) -> str:
    """Stable per-laptop device id: the host's `.local` label (e.g. 'dcj-mbp')."""
    hostname = hostname or default_local_hostname()
    return hostname[: -len(".local")] if hostname.endswith(".local") else hostname


def instance_name(device_id: str) -> str:
    # Not the bare host label: on macOS that collides with the TXT record
    # mDNSResponder publishes at `<host label>._device-info._tcp`.
    return f"eBus broker {device_id}"


def advertiser_config(
    hostname: str | None = None,
    device_id: str | None = None,
    profile: str = DEFAULT_PROFILE,
) -> tuple[ebus.Identity, dict]:
    """The identity and `mdns.Advertiser` keyword arguments for the profile."""
    hostname = hostname or default_local_hostname()
    device_id = device_id or default_device_id(hostname)
    identity = ebus.Identity(
        device_ids=[device_id],
        roles=[ebus.ROLE_BROKER_HOST],
        manufacturer="Electrification Bus",
        model="broker-quickstart laptop broker",
        serial_number=device_id,
    )
    brokers = [
        ebus.BrokerService(listener_.service_type, port=listener_.port, broker=hostname)
        for listener_ in advertised_listeners(profile)
    ]
    own_name = hostname == default_local_hostname()
    return identity, {
        "brokers": brokers,
        "instance_name": instance_name(device_id),
        "server": f"{hostname}.",
        "addresses": None if own_name else [str(ip) for ip in local_ip_addresses()],
    }


def advertise(
    hostname: str | None = None,
    device_id: str | None = None,
    profile: str = DEFAULT_PROFILE,
) -> mdns.Advertiser:
    """An Advertiser, used as a context manager, for every service the profile enables."""
    identity, kwargs = advertiser_config(hostname, device_id, profile)
    return mdns.Advertiser(identity, **kwargs)


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
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())

    with advertise(args.hostname, args.device_id, args.profile) as advertiser:
        for info in advertiser.infos:
            txt = {k.decode(): v.decode() for k, v in info.properties.items() if v is not None}
            print(f"Advertising {info.name}", file=sys.stderr)
            print(f"  port {info.port}  TXT {txt}", file=sys.stderr)
        print(f"  server:  {(advertiser.server or '').rstrip('.')}", file=sys.stderr)
        print("  Ctrl-C to stop (deregisters the records).", file=sys.stderr)
        stop.wait()
    print("Advertisement withdrawn.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
