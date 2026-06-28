"""
Broker authorization (ACL) for the laptop broker (BQ-9j9).

Authentication is by client certificate (the cert CN becomes the MQTT username
via `use_identity_as_username`); there is no password backend. This module owns
the one shared ACL used by the `discovery` and `strict` profiles. Its grants,
combined with each profile's listener (cert optional vs required), produce the
profile semantics in docs/security-profiles.md:

- Lifecycle topics are world-readable, so a discovering consumer can see devices
  without per-device credentials. In `discovery` an anonymous (certless) client
  gets only this; in `strict` there are no anonymous clients (cert required).
- Each authenticated client (cert CN = username) owns its `ebus/5/<user>/#`
  subtree.

`pattern` lines substitute the username (`%u`); `topic` lines apply to every
client (a `pattern` without `%u`/`%c` makes Mosquitto warn, so the
non-user-specific grants use `topic`).
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_ACL = """\
# eBus laptop broker ACL. Authentication is by client cert (CN = username).

# Lifecycle topics are readable by every client (anonymous included, where the
# profile allows anonymous connections):
topic read ebus/5/+/$state
topic read ebus/5/+/$description

# Each authenticated client owns its own device subtree:
pattern readwrite ebus/5/%u/#
"""


def ensure_acl(acl_path: Path) -> Path:
    """Write the default ACL if absent (0600). Returns the path."""
    acl_path = Path(acl_path)
    if not acl_path.exists():
        acl_path.parent.mkdir(parents=True, exist_ok=True)
        acl_path.write_text(DEFAULT_ACL)
    acl_path.chmod(0o600)
    return acl_path
