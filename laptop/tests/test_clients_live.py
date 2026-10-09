"""
Live tests for the client registry's per-client grants (laptop/clients.py).

Like test_acl_live.py, these run a real Mosquitto broker: what matters is how
Mosquitto matches `user` sections against `pattern` lines, which the ACL text
cannot show. Marked `live`; run with `pytest -m live`.
"""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path

import pytest

from laptop.auth import ensure_acl
from laptop.certs import CertPaths, ensure_server_cert, mint_client_cert
from laptop.clients import Client
from laptop.tests.test_acl_live import (  # noqa: F401  (mosquitto_bin is a fixture)
    BROKER_CONF,
    _connect,
    _free_port,
    _settle,
    _wait_for_port,
    mosquitto_bin,
)

pytestmark = pytest.mark.live

CONTROLLER = "ctl"
ROOT = "root-dev"
CHILD = "root-dev-child"
DEVICE = "pub-device"
OTHER = "consumer-device"
SET_TOPIC = f"ebus/5/{DEVICE}/node/prop/set"
REGISTRY = {CONTROLLER: Client("controller"), ROOT: Client("sensor", (CHILD,))}


@pytest.fixture
def broker(tmp_path: Path, mosquitto_bin: str):  # noqa: F811
    paths = CertPaths(root=tmp_path / "state")
    ensure_server_cert(paths, "localhost")
    for client_id in (CONTROLLER, ROOT, DEVICE, OTHER):
        mint_client_cert(paths, client_id)
    acl = ensure_acl(tmp_path / "acl", REGISTRY)

    tls_port, plain_port = _free_port(), _free_port()
    conf = tmp_path / "mosquitto.conf"
    conf.write_text(
        BROKER_CONF.format(
            tls_port=tls_port,
            plain_port=plain_port,
            ca=paths.ca_cert,
            server_crt=paths.server_cert,
            server_key=paths.server_key,
            acl=acl,
            log=tmp_path / "mosquitto.log",
        )
    )
    proc = subprocess.Popen([mosquitto_bin, "-c", str(conf)])
    try:
        _wait_for_port(plain_port, proc)
        yield paths, tls_port, plain_port, acl, proc
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _delivered(paths, tls_port, sender, topic, port=None, sender_paths=True) -> bool:
    """True if `sender` publishing `topic` reaches a subscriber."""
    watcher = _connect(OTHER, tls_port, paths)
    watcher.subscribe(topic, qos=1)
    _settle(0.5)
    client = _connect(sender, port or tls_port, paths if sender_paths else None)
    client.publish(topic, "x", qos=1)
    _settle()
    for c in (client, watcher):
        c.loop_stop()
        c.disconnect()
    return any(t == topic for t, _ in watcher.received)


def test_controller_can_set_another_device(broker):
    paths, tls_port, *_ = broker
    assert _delivered(paths, tls_port, CONTROLLER, SET_TOPIC)


def test_device_without_a_role_cannot_set_another_device(broker):
    paths, tls_port, *_ = broker
    assert not _delivered(paths, tls_port, ROOT, SET_TOPIC)


def test_controller_cannot_write_another_devices_lifecycle(broker):
    paths, tls_port, *_ = broker
    assert not _delivered(paths, tls_port, CONTROLLER, f"ebus/5/{DEVICE}/$state")


def test_anonymous_client_cannot_set(broker):
    paths, tls_port, plain_port, *_ = broker
    assert not _delivered(paths, tls_port, "anon", SET_TOPIC, port=plain_port, sender_paths=False)


def test_root_device_writes_its_childs_subtree(broker):
    paths, tls_port, *_ = broker
    assert _delivered(paths, tls_port, ROOT, f"ebus/5/{CHILD}/$state")


def test_other_device_cannot_write_the_childs_subtree(broker):
    paths, tls_port, *_ = broker
    assert not _delivered(paths, tls_port, DEVICE, f"ebus/5/{CHILD}/$state")


def test_registry_change_applies_on_reload(broker):
    paths, tls_port, _, acl, proc = broker
    assert not _delivered(paths, tls_port, ROOT, SET_TOPIC)
    ensure_acl(acl, {**REGISTRY, ROOT: Client("controller", (CHILD,))})
    proc.send_signal(signal.SIGHUP)
    _settle()
    assert _delivered(paths, tls_port, ROOT, SET_TOPIC)
