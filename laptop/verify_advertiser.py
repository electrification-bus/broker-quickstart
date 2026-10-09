"""
Prove the BQ-a6r acceptance criterion: single-host self-discovery.

Starts the advertiser, then browses `_secure-mqtt._tcp` and `_ebus._tcp` on the
same host and asserts the broker record is found, resolves to the host, and
carries the framework.md TXT keys (txtvers / protocol / broker / device_id), and
that the `_ebus._tcp` record names this host a `broker-host`. Exits 0 on success.

This complements `dns-sd -B _secure-mqtt._tcp`, which can be run by hand to see
the same advertisement from Bonjour's side.
"""

from __future__ import annotations

import sys

from ebus_service_discovery import ebus, mdns

from .advertiser import advertise, default_device_id, instance_name
from .certs import default_local_hostname

_REQUIRED_TXT = {"txtvers", "protocol", "broker", "device_id"}


def _mine(instances, name: str):
    return next((i for i in instances if i.instance_name == name), None)


def verify(hostname: str, device_id: str, timeout: float = 8.0) -> bool:
    name = instance_name(device_id)
    with advertise(hostname, device_id):
        broker = _mine(mdns.browse(ebus.SECURE_MQTT_SERVICE, timeout), name)
        entity = _mine(mdns.browse(ebus.EBUS_SERVICE, timeout), name)
    if broker is None:
        print(f"✗ no {ebus.SECURE_MQTT_SERVICE} record {name!r} discovered within {timeout}s", file=sys.stderr)
        return False
    txt = broker.txt
    addrs = [a.address for a in broker.addresses]

    txt_ok = _REQUIRED_TXT <= set(txt)
    broker_ok = txt.get("broker") == hostname
    proto_ok = txt.get("protocol") == "mqtt-v5"
    ver_ok = txt.get("txtvers") == "1"
    dev_ok = txt.get("device_id") == device_id
    server_ok = broker.server.rstrip(".") == hostname
    addr_ok = bool(addrs)
    roles = (entity.txt.get("roles", "") if entity else "").split(",")
    entity_ok = ebus.ROLE_BROKER_HOST in roles

    ok = all([txt_ok, broker_ok, proto_ok, ver_ok, dev_ok, server_ok, addr_ok, entity_ok])
    mark = "✓" if ok else "✗"
    print(f"{mark} discovered {broker.instance_name}.{broker.service_type}", file=sys.stderr)
    print(f"    server -> {broker.server} (host match: {server_ok})", file=sys.stderr)
    print(f"    addresses: {addrs} (resolvable: {addr_ok})", file=sys.stderr)
    print(f"    port: {broker.port}", file=sys.stderr)
    print(f"    TXT: {txt}", file=sys.stderr)
    print(
        f"    TXT keys present: {txt_ok}; broker={broker_ok} protocol={proto_ok} "
        f"txtvers={ver_ok} device_id={dev_ok}",
        file=sys.stderr,
    )
    print(f"    {ebus.EBUS_SERVICE} roles: {roles} (broker-host: {entity_ok})", file=sys.stderr)
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
