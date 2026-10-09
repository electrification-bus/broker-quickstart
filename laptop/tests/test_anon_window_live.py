"""
Live tests of the rendered `discovery` config: the plaintext anonymous window
refuses clients that present a username.

With no password backend, a username a client merely claims would otherwise
match the ACL's per-username grants: its own `ebus/5/<name>/#` subtree, or a
registered controller's `/set`. Runs the broker's own rendered config (both the
Mosquitto 2.1 plugin form and the 2.0 `acl_file` form) on ephemeral ports.
Marked `live`; run with `pytest -m live`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from laptop import broker as broker_mod
from laptop import profiles
from laptop.certs import CertPaths, mint_client_cert
from laptop.clients import Client, save_registry
from laptop.tests.test_acl_live import (  # noqa: F401  (mosquitto_bin is a fixture)
    _connect,
    _free_port,
    _settle,
    _wait_for_port,
    mosquitto_bin,
    mqtt,
)

pytestmark = pytest.mark.live

CONTROLLER = "ctl"
WATCHER = "watcher"
SET_TOPIC = "ebus/5/meter-1/meter/x/set"


@pytest.fixture(params=["plugin", "acl_file"])
def broker(request, tmp_path: Path, mosquitto_bin: str, monkeypatch):  # noqa: F811
    tls_port, plain_port = _free_port(), _free_port()
    monkeypatch.setattr(profiles, "MQTTS_PORT", tls_port)
    monkeypatch.setattr(profiles, "MQTT_PLAIN_PORT", plain_port)
    if request.param == "acl_file":
        monkeypatch.setattr(broker_mod, "acl_plugin_for", lambda _: None)
    elif broker_mod.acl_plugin_for(mosquitto_bin) is None:
        pytest.skip("this mosquitto has no acl-file / password-file plugins (pre-2.1)")

    state = tmp_path / "state"
    save_registry(state, {CONTROLLER: Client("controller")})
    conf, _ = broker_mod.prepare(state, "localhost", profiles.DISCOVERY, mosquitto=mosquitto_bin)
    paths = CertPaths(root=state.resolve())
    for client_id in (CONTROLLER, WATCHER):
        mint_client_cert(paths, client_id)

    proc = subprocess.Popen([mosquitto_bin, "-c", str(conf)])
    try:
        _wait_for_port(plain_port, proc)
        yield paths, tls_port, plain_port
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _plain_connect(port: int, username: str | None):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"plain-{username}")
    client.rc = None  # type: ignore[attr-defined]

    def on_connect(_c, _u, _f, reason_code, _p):
        client.rc = reason_code

    client.on_connect = on_connect
    if username is not None:
        client.username_pw_set(username, "anything")
    client.connect("127.0.0.1", port, keepalive=30)
    client.loop_start()
    _settle(0.5)
    return client


def _delivered_via_plain(paths, tls_port, plain_port, username, topic) -> bool:
    watcher = _connect(WATCHER, tls_port, paths)
    watcher.subscribe(topic, qos=1)
    _settle(0.5)
    client = _plain_connect(plain_port, username)
    client.publish(topic, "x", qos=0)
    _settle()
    for c in (client, watcher):
        c.loop_stop()
        c.disconnect()
    return any(t == topic for t, _ in watcher.received)


def test_claimed_username_is_refused(broker):
    _, _, plain_port = broker
    client = _plain_connect(plain_port, CONTROLLER)
    client.loop_stop()
    client.disconnect()
    assert client.rc is not None and client.rc.is_failure


def test_claimed_controller_cannot_set(broker):
    paths, tls_port, plain_port = broker
    assert not _delivered_via_plain(paths, tls_port, plain_port, CONTROLLER, SET_TOPIC)


def test_claimed_device_cannot_write_its_subtree(broker):
    paths, tls_port, plain_port = broker
    assert not _delivered_via_plain(paths, tls_port, plain_port, "esp-1", "ebus/5/esp-1/$state")


def test_anonymous_client_still_connects_and_reads(broker):
    paths, tls_port, plain_port = broker
    reader = _plain_connect(plain_port, None)
    assert reader.rc is not None and not reader.rc.is_failure
    reader.received = []  # type: ignore[attr-defined]
    reader.on_message = lambda _c, _u, msg: reader.received.append(msg.topic)
    reader.subscribe("ebus/#", qos=1)
    _settle(0.5)
    publisher = _connect(WATCHER, tls_port, paths)
    publisher.publish(f"ebus/5/{WATCHER}/$state", "ready", qos=1).wait_for_publish(timeout=10)
    _settle()
    for c in (publisher, reader):
        c.loop_stop()
        c.disconnect()
    assert f"ebus/5/{WATCHER}/$state" in reader.received


def test_mtls_controller_still_sets(broker):
    paths, tls_port, _ = broker
    watcher = _connect(WATCHER, tls_port, paths)
    watcher.subscribe(SET_TOPIC, qos=1)
    _settle(0.5)
    controller = _connect(CONTROLLER, tls_port, paths)
    controller.publish(SET_TOPIC, "x", qos=1).wait_for_publish(timeout=10)
    _settle()
    for c in (controller, watcher):
        c.loop_stop()
        c.disconnect()
    assert any(t == SET_TOPIC for t, _ in watcher.received)
