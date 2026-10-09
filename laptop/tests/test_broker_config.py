"""Fast tests for the rendered mosquitto.conf in its 2.1 (plugin) and 2.0 forms."""

from __future__ import annotations

from pathlib import Path

import pytest

from laptop import broker
from laptop.certs import CertPaths
from laptop.profiles import DISCOVERY, OPEN, STRICT

PLUGIN = Path("/opt/mosquitto/lib/mosquitto_acl_file.so")
PASSWORD_PLUGIN = PLUGIN.with_name("mosquitto_password_file.so")


@pytest.fixture(autouse=True)
def _password_plugin_installed(monkeypatch):
    monkeypatch.setattr(broker, "password_plugin_for", lambda p: PASSWORD_PLUGIN if p else None)


def _render(tmp_path: Path, profile: str, *, plugin: Path | None, debug_port: int | None = 1884) -> list[str]:
    acl = tmp_path / "acl"
    acl_file = acl if profile != OPEN else None
    conf = broker.render_config(
        tmp_path, CertPaths(root=tmp_path), profile, debug_port, acl_file, None, plugin,
        tmp_path / "no-users",
    )
    return [line for line in conf.read_text().splitlines() if line and not line.startswith("#")]


def _listener_blocks(lines: list[str]) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    current = None
    for line in lines:
        if line.startswith("listener "):
            current = line.split()[1]
            blocks[current] = []
        elif current and not line.startswith(("persistence", "pid_file", "log_")):
            blocks[current].append(line)
    return blocks


def test_plugin_form_scopes_the_acl_to_acl_listeners(tmp_path):
    lines = _render(tmp_path, DISCOVERY, plugin=PLUGIN)
    assert f"plugin_load acl {PLUGIN}" in lines
    assert f"plugin_opt_acl_file {tmp_path / 'acl'}" in lines
    assert not any(line.startswith(("per_listener_settings", "acl_file", "allow_anonymous")) for line in lines)
    blocks = _listener_blocks(lines)
    assert "plugin_use acl" in blocks["8883"]
    assert "plugin_use acl" in blocks["1883"]
    assert "plugin_use acl" not in blocks["1884"]
    assert all("listener_allow_anonymous true" in b for b in blocks.values())


def test_plugin_form_without_an_acl_loads_no_plugin(tmp_path):
    lines = _render(tmp_path, OPEN, plugin=PLUGIN)
    assert not any(line.startswith("plugin") for line in lines)


@pytest.mark.parametrize("profile", [DISCOVERY, STRICT])
def test_legacy_form_uses_acl_file(tmp_path, profile):
    lines = _render(tmp_path, profile, plugin=None)
    assert not any(line.startswith("plugin") for line in lines)
    assert "per_listener_settings true" in lines  # the debug tap has no ACL
    blocks = _listener_blocks(lines)
    assert f"acl_file {tmp_path / 'acl'}" in blocks["8883"]
    assert not any(line.startswith("acl_file") for line in blocks["1884"])


def test_acl_plugin_needs_2_1(monkeypatch, tmp_path):
    (tmp_path / "sbin").mkdir()
    (tmp_path / "lib").mkdir()
    binary = tmp_path / "sbin" / "mosquitto"
    binary.touch()
    (tmp_path / "lib" / "mosquitto_acl_file.so").touch()
    monkeypatch.undo()  # the real password_plugin_for: no password plugin installed yet
    monkeypatch.setattr(broker, "mosquitto_version", lambda _: (2, 1))
    assert broker.acl_plugin_for(str(binary)) is None
    (tmp_path / "lib" / "mosquitto_password_file.so").touch()
    monkeypatch.setattr(broker, "mosquitto_version", lambda _: (2, 0))
    assert broker.acl_plugin_for(str(binary)) is None
    monkeypatch.setattr(broker, "mosquitto_version", lambda _: (2, 1))
    assert broker.acl_plugin_for(str(binary)) == tmp_path / "lib" / "mosquitto_acl_file.so"
    assert broker.acl_plugin_for(None) is None


def test_plugin_form_refuses_usernames_on_the_anonymous_window(tmp_path):
    lines = _render(tmp_path, DISCOVERY, plugin=PLUGIN)
    assert f"plugin_load nousers {PASSWORD_PLUGIN}" in lines
    assert f"plugin_opt_password_file {tmp_path / 'no-users'}" in lines
    blocks = _listener_blocks(lines)
    assert "plugin_use nousers" in blocks["1883"]
    assert "plugin_use nousers" not in blocks["8883"]
    assert "plugin_use nousers" not in blocks["1884"]


def test_legacy_form_refuses_usernames_on_the_anonymous_window(tmp_path):
    lines = _render(tmp_path, DISCOVERY, plugin=None, debug_port=None)
    assert "per_listener_settings true" in lines
    blocks = _listener_blocks(lines)
    assert f"password_file {tmp_path / 'no-users'}" in blocks["1883"]
    assert not any(line.startswith("password_file") for line in blocks["8883"])


@pytest.mark.parametrize("plugin", [PLUGIN, None])
def test_strict_has_no_anonymous_window_to_guard(tmp_path, plugin):
    lines = _render(tmp_path, STRICT, plugin=plugin)
    assert not any("nousers" in line or line.startswith("password_file") for line in lines)
