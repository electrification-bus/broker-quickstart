"""
Password + ACL auth layer for the laptop broker's `strict` profile (BQ-06f).

`strict` adds two files on top of the mTLS listener:

- a Mosquitto `password_file` (managed via `mosquitto_passwd`), so a username and
  password are required in addition to the client cert;
- an `acl_file` that authorizes per-topic access, keyed off the username (which,
  with `use_identity_as_username`, is the client cert's CN).

The bring-up ensures both files exist; add users with the CLI:

    python -m laptop.auth add-user alice            # prompts for the password
    python -m laptop.auth add-user alice --password s3cret
"""

from __future__ import annotations

import argparse
import getpass
import shutil
import subprocess
import sys
from pathlib import Path

# Deny-by-default ACL. `pattern` substitutes the username (%u); `topic` lines
# apply to every authenticated client. Patterns without %u/%c make Mosquitto
# warn, so non-user-specific grants use `topic`.
DEFAULT_ACL = """\
# eBus laptop broker ACL (strict profile). Deny by default.
# Identity is the client-cert CN (use_identity_as_username).

# Each authenticated client owns its own device subtree:
pattern readwrite ebus/5/%u/#

# Lifecycle topics are readable by any authenticated client:
topic read ebus/5/+/$state
topic read ebus/5/+/$description
"""


def ensure_acl(acl_path: Path) -> Path:
    """Write the default ACL if absent (0600). Returns the path."""
    acl_path = Path(acl_path)
    if not acl_path.exists():
        acl_path.parent.mkdir(parents=True, exist_ok=True)
        acl_path.write_text(DEFAULT_ACL)
    acl_path.chmod(0o600)
    return acl_path


def ensure_strict_auth_files(state_dir: Path) -> tuple[Path, Path]:
    """Ensure the password_file and acl_file exist for the strict profile.

    The password file starts empty (no users); Mosquitto starts fine but, with
    `allow_anonymous false`, nobody can connect until a user is added. Returns
    (passwd_path, acl_path).
    """
    state_dir = Path(state_dir)
    passwd = state_dir / "passwd"
    acl = state_dir / "acl"
    ensure_acl(acl)
    if not passwd.exists():
        passwd.parent.mkdir(parents=True, exist_ok=True)
        passwd.touch()
    passwd.chmod(0o600)
    return passwd, acl


def add_user(passwd_path: Path, username: str, password: str) -> None:
    """Add or update a user in the Mosquitto password file via mosquitto_passwd."""
    binary = shutil.which("mosquitto_passwd")
    if not binary:
        raise RuntimeError(
            "mosquitto_passwd not found on PATH (install Mosquitto: 'brew install mosquitto')."
        )
    passwd_path = Path(passwd_path)
    passwd_path.parent.mkdir(parents=True, exist_ok=True)
    # An empty placeholder file (created so the broker can start with zero users)
    # is not a valid passwd file: mosquitto_passwd refuses -c on an existing file
    # but cannot append to an empty one, so drop the placeholder and create fresh.
    if passwd_path.exists() and passwd_path.stat().st_size == 0:
        passwd_path.unlink()
    # -b: batch (password on argv); -c creates the file when absent.
    args = [binary, "-b"]
    if not passwd_path.exists():
        args.append("-c")
    args += [str(passwd_path), username, password]
    subprocess.run(args, check=True)
    passwd_path.chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", type=Path, default=Path("state/laptop"))
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add-user", help="Add or update a broker user (strict profile).")
    p_add.add_argument("username")
    p_add.add_argument("--password", default=None, help="Password (omit to be prompted securely).")

    sub.add_parser("init", help="Create the password_file and acl_file (no users yet).")

    args = parser.parse_args(argv)
    state_dir = args.state_dir.resolve()
    passwd, acl = ensure_strict_auth_files(state_dir)

    if args.command == "init":
        print(f"passwd: {passwd}\nacl:    {acl}", file=sys.stderr)
        print("Add a user with: python -m laptop.auth add-user <name>", file=sys.stderr)
        return 0

    if args.command == "add-user":
        password = args.password or getpass.getpass(f"Password for {args.username!r}: ")
        if not password:
            print("error: empty password.", file=sys.stderr)
            return 1
        add_user(passwd, args.username, password)
        print(f"✓ user {args.username!r} added to {passwd}", file=sys.stderr)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
