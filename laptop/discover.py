"""
Find an mTLS eBus broker over mDNS: the consumer-side mirror of
`laptop/advertiser.py` (BQ-8sp, BQ-q2y).

A thin wrapper over ebus-service-discovery's `find_broker`, restricted to
`_secure-mqtt._tcp` (a TLS config's credentials never go to a plain broker).
The returned endpoint's `host` is the `broker` TXT value, the `<host>.local`
name the server cert SAN covers, else the SRV target.

    python -m laptop.discover            # prints: <host> <port>
    python -m laptop.discover --json     # {"host": ..., "port": ..., "txt": {...}, "addresses": [...]}
"""

from __future__ import annotations

import math
import sys

from ebus_service_discovery import ebus, mdns
from ebus_service_discovery.ebus import BrokerEndpoint

__all__ = ["BrokerEndpoint", "discover_broker"]


def discover_broker(timeout: float = 8.0) -> BrokerEndpoint | None:
    """Browse until an mTLS broker is found, or None after about `timeout` seconds."""
    interval = mdns.DEFAULT_BROWSE_TIMEOUT
    return mdns.find_broker(
        ebus.BrokerMode.DISCOVERY_ONLY,
        base_cfg={"use_tls": True},
        schedule=ebus.RetrySchedule(
            fast_attempts=math.ceil(timeout / interval),
            fast_interval=0.0,
            max_attempts=math.ceil(timeout / interval),
        ),
        browse_timeout=interval,
    )


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
                    "addresses": [a.address for a in endpoint.addresses],
                }
            )
        )
    else:
        print(f"{endpoint.host} {endpoint.port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
