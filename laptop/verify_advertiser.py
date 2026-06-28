"""
Prove the BQ-a6r acceptance criterion: single-host self-discovery.

Starts the advertiser, then browses `_secure-mqtt._tcp` with a zeroconf
ServiceBrowser on the same host and asserts the record is found, resolves to the
host, and carries the framework.md TXT keys (txtvers / protocol / broker /
device_id). Exits 0 on success.

This complements `dns-sd -B _secure-mqtt._tcp`, which can be run by hand to see
the same advertisement from Bonjour's side.
"""

from __future__ import annotations

import sys
import threading

from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

from .advertiser import advertise, default_device_id
from .certs import default_local_hostname

_SERVICE_TYPE = "_secure-mqtt._tcp.local."
_REQUIRED_TXT = {"txtvers", "protocol", "broker", "device_id"}


class _Collector(ServiceListener):
    def __init__(self) -> None:
        self.found = threading.Event()
        self.info = None

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=3000)
        if info is not None:
            self.info = info
            self.found.set()

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:  # noqa: D102
        self.add_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:  # noqa: D102
        pass


def verify(hostname: str, device_id: str, timeout: float = 8.0) -> bool:
    ok = False
    with advertise(hostname, device_id):
        zc = Zeroconf()
        listener = _Collector()
        ServiceBrowser(zc, _SERVICE_TYPE, listener)
        try:
            if not listener.found.wait(timeout) or listener.info is None:
                print(f"✗ no {_SERVICE_TYPE} record discovered within {timeout}s", file=sys.stderr)
                return False
            info = listener.info
            txt = {k.decode(): (v.decode() if v is not None else None) for k, v in info.properties.items()}
            addrs = info.parsed_addresses()

            txt_ok = _REQUIRED_TXT <= set(txt)
            broker_ok = txt.get("broker") == hostname
            proto_ok = txt.get("protocol") == "mqtt-v5"
            ver_ok = txt.get("txtvers") == "1"
            dev_ok = txt.get("device_id") == device_id
            server_ok = info.server.rstrip(".") == hostname
            addr_ok = bool(addrs)

            ok = all([txt_ok, broker_ok, proto_ok, ver_ok, dev_ok, server_ok, addr_ok])
            mark = "✓" if ok else "✗"
            print(f"{mark} discovered {info.name}", file=sys.stderr)
            print(f"    server -> {info.server} (host match: {server_ok})", file=sys.stderr)
            print(f"    addresses: {addrs} (resolvable: {addr_ok})", file=sys.stderr)
            print(f"    port: {info.port}", file=sys.stderr)
            print(f"    TXT: {txt}", file=sys.stderr)
            print(
                f"    TXT keys present: {txt_ok}; broker={broker_ok} protocol={proto_ok} "
                f"txtvers={ver_ok} device_id={dev_ok}",
                file=sys.stderr,
            )
        finally:
            zc.close()
    return ok


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hostname", default=None)
    parser.add_argument("--device-id", default=None)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args(argv)

    hostname = args.hostname or default_local_hostname()
    device_id = args.device_id or default_device_id(hostname)
    return 0 if verify(hostname, device_id, args.timeout) else 1


if __name__ == "__main__":
    raise SystemExit(main())
