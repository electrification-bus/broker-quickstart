"""
Client registry: what each authenticated client may write beyond its own subtree (BQ-02i, #9).

Every authenticated client (cert CN = MQTT username) reads the whole tree and
writes its own `ebus/5/<cn>/#` subtree (laptop/auth.py). The registry, kept at
`<state-dir>/clients.json`, adds per-client grants rendered into the ACL as
`user <cn>` sections:

- a role from framework.md's role taxonomy (§"Authorization (Broker-Side ACLs)"):
  `controller` and `automation` may publish `/set` commands to any device and
  Homie `$broadcast` messages; `admin` may write the whole tree; `observer` and
  `sensor` get nothing beyond the baseline;
- child device ids: children share their root's MQTT connection
  (framework.md §"Device Topology"), so a root device writes each child's
  `ebus/5/<child>/#` subtree.

A controller's grant is `/set` topics only, so it cannot overwrite another
device's `$state` or `$description`. Anonymous clients have no username, so no
`user` section applies to them.

    python -m laptop.clients set my-controller --role controller
    python -m laptop.clients set my-panel --child my-panel-circuit-1 --child my-panel-circuit-2
    python -m laptop.clients list
    python -m laptop.clients remove my-controller

Each change rewrites the ACL and, when the broker is running, signals it to
reload (SIGHUP), so it takes effect without a restart.
"""

from __future__ import annotations

import json
import os
import re
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROLES = ("observer", "sensor", "controller", "automation", "admin")
DEFAULT_ROLE = "sensor"

# Cert CNs become MQTT usernames on an ACL `user` line; device ids are Homie 5 ids.
_CLIENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DEVICE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class Client:
    role: str = DEFAULT_ROLE
    children: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"unknown role {self.role!r}; expected one of {', '.join(ROLES)}")
        for child in self.children:
            if not _DEVICE_ID.match(child):
                raise ValueError(f"invalid device id {child!r}: lowercase letters, digits and '-'")


def validate_client_id(client_id: str) -> str:
    if not _CLIENT_ID.match(client_id):
        raise ValueError(f"invalid client id {client_id!r}: letters, digits, '.', '_' and '-'")
    return client_id


def registry_path(state_dir: Path) -> Path:
    return Path(state_dir) / "clients.json"


def load_registry(state_dir: Path) -> dict[str, Client]:
    path = registry_path(state_dir)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {
        validate_client_id(cn): Client(
            entry.get("role", DEFAULT_ROLE), tuple(entry.get("children", ()))
        )
        for cn, entry in raw.items()
    }


def save_registry(state_dir: Path, registry: dict[str, Client]) -> Path:
    path = registry_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        cn: {"role": c.role, "children": list(c.children)} for cn, c in sorted(registry.items())
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def acl_sections(registry: dict[str, Client]) -> str:
    """The `user <cn>` ACL sections for the registry's extra grants."""
    out = []
    for cn, client in sorted(registry.items()):
        grants = []
        if client.role in ("controller", "automation"):
            grants += ["topic write ebus/5/+/+/+/set", "topic write ebus/5/$broadcast/#"]
        elif client.role == "admin":
            grants.append("topic readwrite ebus/#")
        grants += [f"topic readwrite ebus/5/{child}/#" for child in client.children]
        if grants:
            out.append(
                f"# {cn}: role {client.role}"
                + (f", children {', '.join(client.children)}" if client.children else "")
            )
            out.append(f"user {cn}")
            out += grants
            out.append("")
    return "\n".join(out)


def reload_broker(state_dir: Path) -> bool:
    """Signal a running broker (by its pid file) to reload the ACL; True if signalled."""
    pid_file = Path(state_dir) / "mosquitto.pid"
    try:
        os.kill(int(pid_file.read_text().strip()), signal.SIGHUP)
    except (OSError, ValueError):
        return False
    return True


def _apply(state_dir: Path, registry: dict[str, Client]) -> None:
    from .auth import ensure_acl

    save_registry(state_dir, registry)
    acl = Path(state_dir) / "acl"
    if acl.exists():
        ensure_acl(acl, registry)
        print(
            "broker reloaded"
            if reload_broker(state_dir)
            else "broker not running; applies at next start"
        )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--state-dir", type=Path, default=Path("state/laptop"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_set = sub.add_parser("set", help="Add or replace a client's role and children.")
    p_set.add_argument("client_id")
    p_set.add_argument("--role", choices=ROLES, default=DEFAULT_ROLE)
    p_set.add_argument("--child", action="append", default=[], metavar="DEVICE_ID")
    p_rm = sub.add_parser("remove", help="Remove a client's extra grants.")
    p_rm.add_argument("client_id")
    sub.add_parser("list", help="Show the registry.")
    args = parser.parse_args(argv)

    state_dir = args.state_dir.resolve()
    try:
        registry = load_registry(state_dir)
        if args.cmd == "list":
            for cn, c in sorted(registry.items()):
                print(f"{cn}\trole={c.role}\tchildren={','.join(c.children) or '-'}")
            return 0
        client_id = validate_client_id(args.client_id)
        if args.cmd == "set":
            registry[client_id] = Client(args.role, tuple(args.child))
        elif registry.pop(client_id, None) is None:
            print(f"{client_id} is not in the registry", file=sys.stderr)
            return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _apply(state_dir, registry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
