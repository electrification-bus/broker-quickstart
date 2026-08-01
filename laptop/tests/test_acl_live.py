"""
Live behavioural tests for the shared broker ACL (laptop/auth.py).

These run a real Mosquitto broker rather than asserting on the ACL text, because
the property under test is a Mosquitto matching behaviour the text cannot show:
the bug they cover was an ACL whose grants read correctly and matched nothing. A
text assertion written against the original code would have asserted the broken
form. test_acl.py covers what *can* be checked structurally.

Requires the `mosquitto` broker binary on PATH (a system package, not a Python
dependency — `brew install mosquitto`, `apt install mosquitto`). Skipped when it
is absent, so a checkout without it stays green.

Marked `live` and deselected by default; run with `pytest -m live`. Each broker
binds an OS-assigned ephemeral port, so these never collide with a broker already
running on 1883/8883.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from laptop.auth import ensure_acl
from laptop.certs import CertPaths, ensure_server_cert, mint_client_cert

mqtt = pytest.importorskip("paho.mqtt.client", reason="paho-mqtt is required for broker tests")

pytestmark = pytest.mark.live

PUBLISHER = "pub-device"
CONSUMER = "consumer-device"
STATE_TOPIC = f"ebus/5/{PUBLISHER}/$state"

# Mirrors the `discovery` profile: an mTLS listener where the cert CN becomes the
# username, plus the plaintext anonymous window.
BROKER_CONF = """\
listener {tls_port}
cafile {ca}
certfile {server_crt}
keyfile {server_key}
require_certificate true
use_identity_as_username true
allow_anonymous true
acl_file {acl}

listener {plain_port}
allow_anonymous true
acl_file {acl}

persistence false
log_dest file {log}
"""


def _free_port() -> int:
    """An OS-assigned ephemeral port, so tests never touch 1883/8883."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def mosquitto_bin() -> str:
    """Locate the broker binary, which commonly lives in an sbin off the user's PATH."""
    found = shutil.which("mosquitto")
    if found:
        return found
    for candidate in (
        "/opt/homebrew/sbin/mosquitto",
        "/usr/local/sbin/mosquitto",
        "/usr/sbin/mosquitto",
    ):
        if Path(candidate).exists():
            return candidate
    pytest.skip("mosquitto broker binary not found; install it to run the live ACL tests")


@pytest.fixture
def broker(tmp_path: Path, mosquitto_bin: str):
    """A running broker using the real DEFAULT_ACL and real minted certs."""
    paths = CertPaths(root=tmp_path / "state")
    ensure_server_cert(paths, "localhost")
    for client_id in (PUBLISHER, CONSUMER):
        mint_client_cert(paths, client_id)

    tls_port, plain_port = _free_port(), _free_port()
    log = tmp_path / "mosquitto.log"
    conf = tmp_path / "mosquitto.conf"
    conf.write_text(
        BROKER_CONF.format(
            tls_port=tls_port,
            plain_port=plain_port,
            ca=paths.ca_cert,
            server_crt=paths.server_cert,
            server_key=paths.server_key,
            acl=ensure_acl(tmp_path / "acl"),
            log=log,
        )
    )

    proc = subprocess.Popen([mosquitto_bin, "-c", str(conf)])
    try:
        _wait_for_port(plain_port, proc)
        yield paths, tls_port, plain_port
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _wait_for_port(port: int, proc: subprocess.Popen, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"broker exited early with {proc.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"broker did not open port {port} within {timeout}s")


def _connect(client_id: str, port: int, paths: CertPaths | None = None):
    """Connect a client, over mTLS as `client_id` when `paths` is given."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    client.received = []  # type: ignore[attr-defined]
    client.on_message = lambda _c, _u, msg: client.received.append((msg.topic, msg.payload))
    if paths is not None:
        client.tls_set(
            ca_certs=str(paths.ca_cert),
            certfile=str(paths.client_cert(client_id)),
            keyfile=str(paths.client_key(client_id)),
        )
    client.connect("127.0.0.1", port, keepalive=30)
    client.loop_start()
    return client


def _settle(seconds: float = 1.0) -> None:
    time.sleep(seconds)


def test_authenticated_client_can_read_another_devices_lifecycle(broker):
    """An mTLS client must receive lifecycle topics published by a *different* device.

    Regression test for the lifecycle grants being `topic` rather than `pattern`:
    Mosquitto applies unprefixed `topic` lines only to clients with no username,
    so every client on this listener matched neither line and received nothing.
    """
    paths, tls_port, _ = broker

    publisher = _connect(PUBLISHER, tls_port, paths)
    publisher.publish(STATE_TOPIC, "ready", qos=1, retain=True).wait_for_publish(timeout=10)

    consumer = _connect(CONSUMER, tls_port, paths)
    consumer.subscribe("ebus/5/#", qos=1)
    _settle()

    topics = [topic for topic, _ in consumer.received]
    for client in (publisher, consumer):
        client.loop_stop()
        client.disconnect()

    assert STATE_TOPIC in topics, (
        f"authenticated client {CONSUMER!r} saw {topics!r}; "
        f"expected the lifecycle topic of {PUBLISHER!r}"
    )


def test_anonymous_client_cannot_publish(broker):
    """The plaintext window stays read-only: no write grant can match a client with no username."""
    paths, tls_port, plain_port = broker

    anonymous = _connect("anon", plain_port)
    anonymous.publish(STATE_TOPIC, "lost", qos=0, retain=True)
    _settle()
    anonymous.loop_stop()
    anonymous.disconnect()

    watcher = _connect(CONSUMER, tls_port, paths)
    watcher.subscribe(STATE_TOPIC, qos=1)
    _settle()
    payloads = [payload for _, payload in watcher.received]
    watcher.loop_stop()
    watcher.disconnect()

    assert b"lost" not in payloads, "anonymous client was able to write a device lifecycle topic"
