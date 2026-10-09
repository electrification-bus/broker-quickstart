"""
Bring up Mosquitto host-native on the laptop with the eBus mTLS profile (BQ-zu8).

Ensures the dev CA + server cert exist (SAN = the host's `<name>.local`), renders
the Mosquitto config from `mosquitto.conf.j2`, and execs `mosquitto` in the
foreground on port 8883 requiring client certs. No root; everything lives under a
user-writable state dir (default `./state/laptop`).

This module brings up the broker alone. The one-command runner that also starts
the mDNS advertiser (BQ-x8v) composes `prepare()` + the advertiser.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .auth import ensure_acl, ensure_no_users
from .bridge import Bridge, add_bridge_arguments, bridge_from_args
from .certs import CertPaths, default_local_hostname, ensure_server_cert
from .clients import load_registry
from .profiles import DEFAULT_PROFILE, PROFILES, listeners
from .span import add_span_bridge_arguments, span_bridge_from_args


def resolve_bridge(args: argparse.Namespace, on_error=None) -> Bridge | None:
    """Resolve the bridge from args: --span-bridge or --bridge (mutually exclusive)."""
    if getattr(args, "span_bridge", None) is not None and args.bridge is not None:
        if on_error is not None:
            on_error("use either --bridge or --span-bridge, not both")
    return span_bridge_from_args(args, on_error=on_error) or bridge_from_args(args, on_error=on_error)

_TEMPLATE_DIR = Path(__file__).resolve().parent


def profile_ports(profile: str) -> set[int]:
    """The ports a profile's (non-debug) listeners bind."""
    return {listener_.port for listener_ in listeners(profile)}


def _validate_debug_port(profile: str, debug_port: int | None, parser: argparse.ArgumentParser) -> None:
    if debug_port is not None and debug_port in profile_ports(profile):
        parser.error(
            f"--debug-port {debug_port} collides with a {profile} listener on the same port; "
            "choose a different port."
        )


def listener_summary(profile: str, hostname: str) -> str:
    parts = []
    for listener_ in listeners(profile):
        host = "0.0.0.0" if listener_.bind is None else listener_.bind
        if not listener_.tls:
            kind = "plaintext anon read-only" if listener_.acl else "plaintext anonymous"
            svc = " [_mqtt._tcp]" if listener_.advertised else " [not advertised]"
        else:
            kind = "mTLS, client cert required"
            host = hostname
            svc = " [_secure-mqtt._tcp]"
        parts.append(f"{host}:{listener_.port} ({kind}){svc}")
    return "; ".join(parts)


def render_config(
    state_dir: Path,
    paths: CertPaths,
    profile: str = DEFAULT_PROFILE,
    debug_port: int | None = None,
    acl_file: Path | None = None,
    bridge: Bridge | None = None,
    acl_plugin: Path | None = None,
    no_users_file: Path | None = None,
) -> Path:
    """Render mosquitto.conf for `profile` into the state dir and return its path.

    With `acl_plugin` (Mosquitto 2.1+), the ACL is the mosquitto_acl_file plugin,
    attached only to the listeners that use it. Without it (2.0), `acl_file` is
    scoped by `per_listener_settings`, which 2.1 deprecates.
    """
    listener_set = listeners(profile, debug_port)
    # per_listener_settings is needed only when listeners disagree on a global
    # security setting (ACL on the real listeners vs none on the debug tap).
    # The plaintext ACL listener (the anonymous read window) refuses any client that
    # presents a username: with no password backend, a claimed username would
    # otherwise match the ACL's per-username grants. An empty password file does it.
    anon_window = any(listener_.acl and not listener_.tls for listener_ in listener_set)
    per_listener = acl_plugin is None and (
        anon_window
        or (
            any(listener_.acl for listener_ in listener_set)
            and any(not listener_.acl for listener_ in listener_set)
        )
    )
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    rendered = env.get_template("mosquitto.conf.j2").render(
        profile=profile,
        listeners=listener_set,
        ca_cert=paths.ca_cert,
        server_cert=paths.server_cert,
        server_key=paths.server_key,
        state_dir=state_dir,
        acl_file=acl_file,
        acl_plugin=acl_plugin if acl_file is not None else None,
        password_plugin=password_plugin_for(acl_plugin) if acl_file is not None else None,
        no_users_file=no_users_file if anon_window else None,
        per_listener=per_listener,
        bridge=bridge,
    )
    conf_path = state_dir / "mosquitto.conf"
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    conf_path.write_text(rendered)
    # The rendered config embeds the bridge's remote_password; keep it owner-only.
    if bridge is not None and bridge.password:
        conf_path.chmod(0o600)
    return conf_path


def resolve_mosquitto(explicit: str | None = None) -> str | None:
    """Return the mosquitto binary path (explicit override, else search PATH)."""
    return explicit or shutil.which("mosquitto")


def mosquitto_version(mosquitto: str) -> tuple[int, int] | None:
    """(major, minor) from `mosquitto -h`, or None if it cannot be read."""
    try:
        out = subprocess.run(
            [mosquitto, "-h"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"mosquitto version (\d+)\.(\d+)", out.stdout + out.stderr)
    return (int(match[1]), int(match[2])) if match else None


def acl_plugin_for(mosquitto: str | None) -> Path | None:
    """The mosquitto_acl_file plugin to use, or None for the 2.0 `acl_file` form.

    The plugin and the per-listener `plugin_use` it relies on arrived in 2.1. It
    is looked for next to the broker's own install prefix.
    """
    if not mosquitto or (mosquitto_version(mosquitto) or (0, 0)) < (2, 1):
        return None
    prefix = Path(os.path.realpath(mosquitto)).parent.parent
    for candidate in (
        prefix / "lib" / "mosquitto_acl_file.so",
        prefix / "lib" / "mosquitto" / "mosquitto_acl_file.so",
        *sorted(prefix.glob("lib/*/mosquitto/mosquitto_acl_file.so")),
    ):
        if candidate.exists() and password_plugin_for(candidate):
            return candidate
    return None


def password_plugin_for(acl_plugin: Path | None) -> Path | None:
    """The mosquitto_password_file plugin installed beside `acl_plugin`."""
    if acl_plugin is None:
        return None
    candidate = acl_plugin.with_name("mosquitto_password_file.so")
    return candidate if candidate.exists() else None


def prepare(
    state_dir: Path,
    hostname: str | None = None,
    profile: str = DEFAULT_PROFILE,
    debug_port: int | None = None,
    bridge: Bridge | None = None,
    mosquitto: str | None = None,
) -> tuple[Path, str]:
    """Ensure certs/ACL + config exist for `profile`. Returns (config_path, hostname).

    Idempotent: reuses existing material unless it no longer matches (e.g. the
    server cert SAN no longer covers `hostname`). Profiles with a TLS listener
    mint a server cert; profiles with an ACL listener ensure the ACL file exists.
    The bridge (if any) uses externally supplied trust material, so it mints
    nothing.
    """
    hostname = hostname or default_local_hostname()
    state_dir = state_dir.resolve()
    paths = CertPaths(root=state_dir)

    listener_set = listeners(profile, debug_port)
    acl_file = None
    if any(listener_.tls for listener_ in listener_set):
        ensure_server_cert(paths, hostname)
    if any(listener_.acl for listener_ in listener_set):
        acl_file = ensure_acl(state_dir / "acl", load_registry(state_dir))
    no_users_file = None
    if any(listener_.acl and not listener_.tls for listener_ in listener_set):
        no_users_file = ensure_no_users(state_dir / "no-users")

    acl_plugin = acl_plugin_for(mosquitto or resolve_mosquitto())
    conf_path = render_config(
        state_dir, paths, profile, debug_port, acl_file, bridge, acl_plugin, no_users_file
    )
    return conf_path, hostname


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("state/laptop"),
        help="Root for TLS material, config, and persistence (default: ./state/laptop).",
    )
    parser.add_argument(
        "--hostname",
        default=None,
        help="Advertised <host>.local name for the server cert SAN "
        "(default: this host's Bonjour LocalHostName).",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default=DEFAULT_PROFILE,
        help=f"Security profile (default: {DEFAULT_PROFILE}). "
        "open=plaintext/anonymous; discovery=mTLS + plaintext anon-read; strict=mTLS only.",
    )
    parser.add_argument(
        "--debug-port",
        type=int,
        default=None,
        metavar="PORT",
        help="Add an unadvertised localhost-only plaintext listener on PORT "
        "(a local tap that needs no client cert).",
    )
    add_bridge_arguments(parser)
    add_span_bridge_arguments(parser)
    parser.add_argument(
        "--mosquitto",
        default=None,
        help="Path to the mosquitto binary (default: search PATH).",
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="Mint certs and render the config, then exit without starting the broker.",
    )
    args = parser.parse_args(argv)

    _validate_debug_port(args.profile, args.debug_port, parser)
    bridge = resolve_bridge(args, on_error=parser.error)
    conf_path, hostname = prepare(
        args.state_dir, args.hostname, args.profile, args.debug_port, bridge, args.mosquitto
    )
    print(f"eBus laptop broker prepared for {hostname} [profile: {args.profile}]", file=sys.stderr)
    print(f"  config: {conf_path}", file=sys.stderr)
    print(f"  listener: {listener_summary(args.profile, hostname)}", file=sys.stderr)
    if args.debug_port:
        print(f"  debug:    127.0.0.1:{args.debug_port} (plaintext, unadvertised)", file=sys.stderr)
    if bridge:
        print(f"  bridge:   {bridge.topic} {bridge.direction} -> {bridge.host}:{bridge.port}", file=sys.stderr)

    if args.no_run:
        return 0

    mosquitto = resolve_mosquitto(args.mosquitto)
    if not mosquitto:
        print(
            "error: 'mosquitto' not found on PATH. Install it (Mac: 'brew install mosquitto') "
            "or pass --mosquitto.",
            file=sys.stderr,
        )
        return 1

    print(f"  starting: {mosquitto} -c {conf_path}", file=sys.stderr)
    # Replace this process with mosquitto so Ctrl-C / a supervisor's signals go
    # straight to the broker.
    os.execv(mosquitto, [mosquitto, "-c", str(conf_path)])


if __name__ == "__main__":
    raise SystemExit(main())
