"""
Prove the BQ-6gv acceptance criterion: the self-contained single-laptop loop.

A discovering publisher, entirely on one machine, with no Docker / Pi / panel:

  1. discover the broker via mDNS (browse `_secure-mqtt._tcp`, read the `broker`
     hostname + port from the advertisement) instead of hardcoding a host;
  2. mint a client cert from the dev CA;
  3. connect over mTLS to the *discovered* `<host>.local:8883`, validating the
     server cert against the dev CA (so the SAN must contain `<host>.local`);
  4. publish a retained Homie `$state` and read it back, confirming the round
     trip.

Run it after `python -m laptop.run` is up. This is a validation stand-in for a
real eBus publisher: the production utility-meter simulator
(python-sdk/examples/utility-meter) gets its own mDNS-discovery change in the
python-sdk repo, not here; see python-sdk/examples/simple-span-controller for the
same discovery pattern.
"""

from __future__ import annotations

import argparse
import ssl
import sys
import threading
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

from .certs import CertPaths, mint_client_cert

_SERVICE_TYPE = "_secure-mqtt._tcp.local."


class _BrokerFinder(ServiceListener):
    def __init__(self) -> None:
        self.found = threading.Event()
        self.hostname: str | None = None
        self.port: int | None = None

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=3000)
        if info is None:
            return
        # Prefer the spec `broker` TXT (the .local name) so TLS validates the
        # advertised hostname; fall back to the SRV target.
        broker = info.properties.get(b"broker")
        self.hostname = broker.decode() if broker else info.server.rstrip(".")
        self.port = info.port or 8883
        self.found.set()

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self.add_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass


def discover_broker(timeout: float = 8.0) -> tuple[str, int] | None:
    zc = Zeroconf()
    finder = _BrokerFinder()
    ServiceBrowser(zc, _SERVICE_TYPE, finder)
    try:
        if finder.found.wait(timeout) and finder.hostname and finder.port:
            return finder.hostname, finder.port
        return None
    finally:
        zc.close()


def publish_and_readback(
    state_dir: Path,
    hostname: str,
    port: int,
    client_id: str,
    timeout: float = 10.0,
) -> bool:
    paths = CertPaths(root=state_dir.resolve())
    cert_path, key_path = mint_client_cert(paths, client_id)
    topic = f"ebus/5/{client_id}/$state"
    payload = b"ready"

    done = threading.Event()
    result = {"connected": False, "readback": False, "reason": None}

    client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id=client_id)
    client.tls_set(
        ca_certs=str(paths.ca_cert),
        certfile=str(cert_path),
        keyfile=str(key_path),
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    client.tls_insecure_set(False)  # validate <host>.local against the cert SAN

    def on_connect(c, userdata, flags, reason_code, properties):
        result["reason"] = str(reason_code)
        if reason_code == 0 or getattr(reason_code, "is_failure", True) is False:
            result["connected"] = True
            c.subscribe(topic)
            c.publish(topic, payload, qos=1, retain=True)
        else:
            done.set()

    def on_message(c, userdata, msg):
        result["readback"] = msg.topic == topic and msg.payload == payload
        done.set()

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(hostname, port, keepalive=30)
    except Exception as exc:  # noqa: BLE001 - surface any TLS/connect failure
        result["reason"] = f"{type(exc).__name__}: {exc}"
        done.set()

    if not done.is_set():
        client.loop_start()
        done.wait(timeout)
        client.loop_stop()
    try:
        client.disconnect()
    except Exception:  # noqa: BLE001 - teardown best-effort
        pass

    ok = result["connected"] and result["readback"]
    mark = "✓" if ok else "✗"
    print(f"{mark} mTLS publish to discovered {hostname}:{port} as '{client_id}'", file=sys.stderr)
    print(f"    connected (CONNACK): {result['connected']} (reason: {result['reason']})", file=sys.stderr)
    print(f"    published + read back {topic!r}={payload.decode()!r}: {result['readback']}", file=sys.stderr)
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", type=Path, default=Path("state/laptop"))
    parser.add_argument("--client-id", default="laptop-loop")
    parser.add_argument("--discover-timeout", type=float, default=8.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)

    print("Discovering broker via mDNS (_secure-mqtt._tcp)...", file=sys.stderr)
    discovered = discover_broker(args.discover_timeout)
    if discovered is None:
        print("✗ no broker discovered. Is `python -m laptop.run` running?", file=sys.stderr)
        return 1
    hostname, port = discovered
    print(f"✓ discovered broker: {hostname}:{port}", file=sys.stderr)

    ok = publish_and_readback(args.state_dir, hostname, port, args.client_id, args.timeout)
    if not ok:
        print(
            "    loop failed: confirm the broker is up and the discovered hostname "
            "matches the server cert SAN.",
            file=sys.stderr,
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
