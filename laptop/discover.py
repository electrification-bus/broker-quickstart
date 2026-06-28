"""
Reusable mDNS broker discovery (BQ-8sp): the consumer-side mirror of
`laptop/advertiser.py`.

Browses `_secure-mqtt._tcp`, resolves the broker's advertised hostname (the
`broker` TXT value, which is the `<host>.local` name the server cert SAN covers,
falling back to the SRV target), its port, and its TXT records. This is the
generic eBus discovery capability that downstream integrations consume instead of
reimplementing mDNS (see BQ-w1k and the eBus framework's broker-discovery flow).

    python -m laptop.discover            # prints: <host> <port>
    python -m laptop.discover --json     # {"host": ..., "port": ..., "txt": {...}}
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

from mdns.constants import SECURE_MQTT_SERVICE_TYPE

_SECURE_MQTT = f"{SECURE_MQTT_SERVICE_TYPE}.local."


@dataclass
class BrokerEndpoint:
    """A discovered broker: where to connect and what it advertised."""

    host: str
    port: int
    txt: dict[str, str] = field(default_factory=dict)
    addresses: list[str] = field(default_factory=list)


class _BrokerFinder(ServiceListener):
    def __init__(self) -> None:
        self.found = threading.Event()
        self.endpoint: BrokerEndpoint | None = None

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=3000)
        if info is None:
            return
        txt = {
            k.decode(): (v.decode() if v is not None else "")
            for k, v in info.properties.items()
        }
        # Prefer the spec `broker` TXT (the .local name) so a TLS client validates
        # the advertised hostname against the cert SAN; fall back to the SRV target.
        host = txt.get("broker") or info.server.rstrip(".")
        self.endpoint = BrokerEndpoint(
            host=host,
            port=info.port or 8883,
            txt=txt,
            addresses=info.parsed_addresses(),
        )
        self.found.set()

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self.add_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass


def discover_broker(timeout: float = 8.0, service_type: str = _SECURE_MQTT) -> BrokerEndpoint | None:
    """Browse mDNS and return the first broker found, or None on timeout."""
    zc = Zeroconf()
    finder = _BrokerFinder()
    ServiceBrowser(zc, service_type, finder)
    try:
        if finder.found.wait(timeout):
            return finder.endpoint
        return None
    finally:
        zc.close()


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--json", action="store_true", help="Emit the endpoint as JSON.")
    args = parser.parse_args(argv)

    endpoint = discover_broker(args.timeout)
    if endpoint is None:
        print(
            f"no _secure-mqtt._tcp broker discovered within {args.timeout}s "
            "(is the broker + advertiser running?)",
            file=sys.stderr,
        )
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "host": endpoint.host,
                    "port": endpoint.port,
                    "txt": endpoint.txt,
                    "addresses": endpoint.addresses,
                }
            )
        )
    else:
        print(f"{endpoint.host} {endpoint.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
