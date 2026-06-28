"""
Prove the BQ-zu8 acceptance criterion against a running laptop broker.

Mints a client cert from the dev CA, then connects over mTLS to
`<host>.local:8883` with full server-certificate validation (CERT_REQUIRED,
hostname checking on). A successful CONNACK demonstrates: the broker requires a
client cert, AND the server cert's SAN contains the advertised `<host>.local`
name (otherwise hostname verification would fail the handshake).

Run this in a second terminal after `python -m laptop.broker` is up.
"""

from __future__ import annotations

import argparse
import ssl
import sys
import threading
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from .certs import CertPaths, default_local_hostname, mint_client_cert

MQTTS_PORT = 8883
_TOPIC = "ebus/5/laptop-selftest"


def verify(state_dir: Path, hostname: str, client_id: str, timeout: float = 10.0) -> bool:
    paths = CertPaths(root=state_dir.resolve())
    cert_path, key_path = mint_client_cert(paths, client_id)

    done = threading.Event()
    result: dict[str, object] = {"connected": False, "echo": False, "reason": None}

    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=client_id,
    )
    client.tls_set(
        ca_certs=str(paths.ca_cert),
        certfile=str(cert_path),
        keyfile=str(key_path),
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    # Verify the server hostname against the cert SAN. This is the whole point of
    # BQ-zu8: the SAN must contain <host>.local or this check fails.
    client.tls_insecure_set(False)

    def on_connect(c, userdata, flags, reason_code, properties):
        result["reason"] = str(reason_code)
        if reason_code == 0 or getattr(reason_code, "is_failure", True) is False:
            result["connected"] = True
            c.subscribe(_TOPIC)
            c.publish(_TOPIC, b"hello-ebus")
        else:
            done.set()

    def on_message(c, userdata, msg):
        result["echo"] = msg.payload == b"hello-ebus"
        done.set()

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        # Connect to the advertised name so TLS validates <host>.local.
        client.connect(hostname, MQTTS_PORT, keepalive=30)
    except Exception as exc:  # noqa: BLE001 - surface any TLS/connect failure
        result["reason"] = f"{type(exc).__name__}: {exc}"
        _report(hostname, client_id, result)
        return False

    client.loop_start()
    done.wait(timeout)
    client.loop_stop()
    client.disconnect()

    _report(hostname, client_id, result)
    return bool(result["connected"] and result["echo"])


def _report(hostname: str, client_id: str, result: dict) -> None:
    ok = result["connected"] and result["echo"]
    mark = "✓" if ok else "✗"
    print(f"{mark} mTLS handshake to {hostname}:{MQTTS_PORT} as '{client_id}'", file=sys.stderr)
    print(f"    connected (CONNACK): {result['connected']} (reason: {result['reason']})", file=sys.stderr)
    print(f"    pub/sub round-trip:  {result['echo']}", file=sys.stderr)
    if not ok:
        print(
            "    handshake or round-trip failed: check the broker is up "
            "(`python -m laptop.broker`) and the hostname matches the cert SAN.",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", type=Path, default=Path("state/laptop"))
    parser.add_argument("--hostname", default=None, help="Default: this host's Bonjour name.")
    parser.add_argument("--client-id", default="laptop-selftest")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)

    hostname = args.hostname or default_local_hostname()
    ok = verify(args.state_dir, hostname, args.client_id, args.timeout)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
