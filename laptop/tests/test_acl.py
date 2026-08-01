"""
Fast structural checks on the shared broker ACL (laptop/auth.py). No broker needed.

These guard the two properties the ACL's grant *forms* have to satisfy. They do not
prove the ACL behaves correctly — Mosquitto's matching rules decide that, and
test_acl_live.py exercises them against a real broker.
"""

from __future__ import annotations

from laptop.auth import DEFAULT_ACL

WRITE_VERBS = {"write", "readwrite"}


def _grants() -> list[str]:
    return [
        line.strip()
        for line in DEFAULT_ACL.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_no_bare_topic_grants():
    """Every grant must be `pattern`.

    Both ACL-bearing listeners set `use_identity_as_username`, so every client has
    a username. Mosquitto applies unprefixed `topic` lines only to clients that do
    not, meaning a `topic` grant in this file can never reach an authenticated
    client — never the intent for an ACL shared by both listeners.
    """
    bare = [line for line in _grants() if line.split()[0] == "topic"]
    assert not bare, (
        f"bare `topic` grants can only match anonymous clients: {bare!r}; use `pattern` instead"
    )


def test_lifecycle_reads_are_granted_to_every_client():
    """Lifecycle topics are world-readable, per docs/security-profiles.md."""
    grants = _grants()
    assert "pattern read ebus/5/+/$state" in grants
    assert "pattern read ebus/5/+/$description" in grants


def test_every_write_grant_is_username_scoped():
    """The plaintext window stays read-only.

    Anonymous clients have no username, so a write grant containing `%u` cannot
    match them. A write grant without `%u` would silently hand anonymous clients
    publish rights on the `discovery` profile.
    """
    writes = [line for line in _grants() if line.split()[1] in WRITE_VERBS]
    assert writes, "expected at least one write grant"
    unscoped = [line for line in writes if "%u" not in line]
    assert not unscoped, (
        f"write grants must be username-scoped, else anonymous matches: {unscoped!r}"
    )
