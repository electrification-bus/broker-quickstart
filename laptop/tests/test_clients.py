"""Fast tests for the client registry and its ACL sections (no broker)."""

from __future__ import annotations

import pytest

from laptop import clients
from laptop.auth import DEFAULT_ACL, render_acl
from laptop.clients import Client


def test_empty_registry_renders_the_shared_acl():
    assert render_acl({}) == DEFAULT_ACL


def test_controller_gets_set_and_broadcast_only():
    sections = clients.acl_sections({"ctl": Client("controller")})
    assert "user ctl" in sections
    grants = [line for line in sections.splitlines() if line.startswith("topic")]
    assert grants == ["topic write ebus/5/+/+/+/set", "topic write ebus/5/$broadcast/#"]


@pytest.mark.parametrize("role", ["observer", "sensor"])
def test_roles_without_extra_grants_render_nothing(role):
    assert clients.acl_sections({"x": Client(role)}) == ""


def test_admin_writes_the_whole_tree():
    assert "topic readwrite ebus/#" in clients.acl_sections({"a": Client("admin")})


def test_children_are_granted_to_their_root():
    sections = clients.acl_sections({"root": Client("sensor", ("child-1", "child-2"))})
    assert "topic readwrite ebus/5/child-1/#" in sections
    assert "topic readwrite ebus/5/child-2/#" in sections


def test_user_sections_follow_the_patterns():
    acl = render_acl({"ctl": Client("controller")})
    assert acl.index("pattern readwrite ebus/5/%u/#") < acl.index("user ctl")


@pytest.mark.parametrize("bad", ["a b", "#", "x/y", "-x", ""])
def test_client_ids_that_would_break_the_acl_are_rejected(bad):
    with pytest.raises(ValueError):
        clients.validate_client_id(bad)


@pytest.mark.parametrize("bad", ["Upper", "a/b", "+", "a b", "-x"])
def test_child_ids_must_be_homie_ids(bad):
    with pytest.raises(ValueError):
        Client("sensor", (bad,))


def test_unknown_role_is_rejected():
    with pytest.raises(ValueError):
        Client("superuser")


def test_registry_round_trips(tmp_path):
    registry = {"ctl": Client("controller"), "root": Client("sensor", ("c-1",))}
    clients.save_registry(tmp_path, registry)
    assert clients.load_registry(tmp_path) == registry


def test_cli_set_list_remove(tmp_path, capsys):
    assert clients.main(["--state-dir", str(tmp_path), "set", "ctl", "--role", "controller"]) == 0
    assert clients.main(["--state-dir", str(tmp_path), "list"]) == 0
    assert "ctl\trole=controller" in capsys.readouterr().out
    assert clients.main(["--state-dir", str(tmp_path), "remove", "ctl"]) == 0
    assert clients.load_registry(tmp_path) == {}
    assert clients.main(["--state-dir", str(tmp_path), "remove", "ctl"]) == 1
