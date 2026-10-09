"""
Broker authorization (ACL) for the laptop broker (BQ-9j9).

Authentication is by client certificate (the cert CN becomes the MQTT username
via `use_identity_as_username`); there is no password backend. This module owns
the one shared ACL used by the `discovery` and `strict` profiles. Its grants,
combined with each profile's listener (cert optional vs required), produce the
profile semantics in docs/security-profiles.md:

- The whole tree is world-readable, so a consumer can read device data without
  per-device credentials. In `discovery` an anonymous (certless) client reads
  everything; use `strict` (no anonymous listener) to close reads.
- Each authenticated client (cert CN = username) owns (may publish) its
  `ebus/5/<user>/#` subtree.

`pattern` lines apply to every client, substituting the username (`%u`) where
present; unprefixed `topic` lines apply only to clients with no username, i.e.
anonymous ones. The world-readable grants must therefore be `pattern`, even
though a `pattern` without `%u`/`%c` makes Mosquitto log a startup warning.
"""

from __future__ import annotations

import os
from pathlib import Path

from .clients import Client, acl_sections

DEFAULT_ACL = """\
# eBus laptop broker ACL. Authentication is by client cert (CN = username).

# There are no read restrictions: any client may read the whole tree. This is a
# `pattern` (not `topic`): Mosquitto applies an unprefixed `topic` line to clients
# with no username only, so a `topic` grant reaches the anonymous plaintext window
# but never an authenticated (mTLS) client. On `discovery` this read grant also
# covers the anonymous window; use `strict` (no anonymous listener) to close reads.
pattern read ebus/#

# Each authenticated client owns (may publish) its own device subtree. Grants
# beyond it (a controller's `/set`, a root device's children) are per-client
# `user` sections below, rendered from the client registry (laptop/clients.py).
pattern readwrite ebus/5/%u/#
"""


def render_acl(registry: dict[str, Client] | None = None) -> str:
    """The shared ACL plus the registry's per-client `user` sections."""
    sections = acl_sections(registry or {})
    return DEFAULT_ACL + ("\n" + sections if sections else "")


def ensure_acl(acl_path: Path, registry: dict[str, Client] | None = None) -> Path:
    """Write the ACL (0600) for `registry` and return the path.

    Rewritten on every bring-up, the same way laptop/broker.py re-renders
    mosquitto.conf: the ACL is a generated, tool-owned artifact with no
    machine-local content, so there is nothing on disk worth preserving and a
    stale copy from an earlier version must not survive. (Writing only when the
    file was absent left brokers created before an ACL fix pinned to the old ACL.)
    """
    acl_path = Path(acl_path)
    acl_path.parent.mkdir(parents=True, exist_ok=True)
    acl_path.write_text(render_acl(registry))
    acl_path.chmod(0o600)
    # A new file takes its directory's group (wheel under /tmp on macOS);
    # Mosquitto 2.1 warns, and later versions refuse, unless it is our own group.
    os.chown(acl_path, -1, os.getgid())
    return acl_path
