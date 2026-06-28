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
import shutil
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from mdns.constants import MQTT_PLAIN_PORT, MQTTS_PORT

from .auth import ensure_strict_auth_files
from .certs import CertPaths, default_local_hostname, ensure_server_cert
from .profiles import DEFAULT_PROFILE, OPEN, PROFILES, STRICT, is_tls

_TEMPLATE_DIR = Path(__file__).resolve().parent


def main_port(profile: str) -> int:
    """The advertised listener port for a profile (plaintext 1883 vs mTLS 8883)."""
    return MQTT_PLAIN_PORT if profile == OPEN else MQTTS_PORT


def _validate_debug_port(profile: str, debug_port: int | None, parser: argparse.ArgumentParser) -> None:
    if debug_port is not None and debug_port == main_port(profile):
        parser.error(
            f"--debug-port {debug_port} collides with the {profile} listener on the same port; "
            "choose a different port."
        )


def listener_summary(profile: str, hostname: str) -> str:
    if profile == OPEN:
        return f"0.0.0.0:{MQTT_PLAIN_PORT} (plaintext, anonymous) [advertised _mqtt._tcp]"
    auth = "mTLS + password + ACL" if profile == STRICT else "mTLS, client cert required"
    return f"{hostname}:{MQTTS_PORT} ({auth}) [advertised _secure-mqtt._tcp]"


def render_config(
    state_dir: Path,
    paths: CertPaths,
    profile: str = DEFAULT_PROFILE,
    debug_port: int | None = None,
    passwd_file: Path | None = None,
    acl_file: Path | None = None,
) -> Path:
    """Render mosquitto.conf for `profile` into the state dir and return its path."""
    # per_listener_settings is only needed when two listeners want different auth,
    # i.e. the strict listener (allow_anonymous false) plus an anonymous debug tap.
    per_listener = profile == STRICT and debug_port is not None
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    rendered = env.get_template("mosquitto.conf.j2").render(
        profile=profile,
        plain_port=MQTT_PLAIN_PORT,
        mqtts_port=MQTTS_PORT,
        ca_cert=paths.ca_cert,
        server_cert=paths.server_cert,
        server_key=paths.server_key,
        state_dir=state_dir,
        debug_port=debug_port,
        passwd_file=passwd_file,
        acl_file=acl_file,
        per_listener=per_listener,
    )
    conf_path = state_dir / "mosquitto.conf"
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    conf_path.write_text(rendered)
    return conf_path


def resolve_mosquitto(explicit: str | None = None) -> str | None:
    """Return the mosquitto binary path (explicit override, else search PATH)."""
    return explicit or shutil.which("mosquitto")


def prepare(
    state_dir: Path,
    hostname: str | None = None,
    profile: str = DEFAULT_PROFILE,
    debug_port: int | None = None,
) -> tuple[Path, str]:
    """Ensure certs/auth + config exist for `profile`. Returns (config_path, hostname).

    Idempotent: reuses existing material unless it no longer matches (e.g. the
    server cert SAN no longer covers `hostname`). The TLS profiles mint a server
    cert; `strict` also ensures the password and ACL files exist; `open` needs
    neither.
    """
    hostname = hostname or default_local_hostname()
    state_dir = state_dir.resolve()
    paths = CertPaths(root=state_dir)

    passwd_file = acl_file = None
    if is_tls(profile):
        ensure_server_cert(paths, hostname)
    if profile == STRICT:
        passwd_file, acl_file = ensure_strict_auth_files(state_dir)

    conf_path = render_config(state_dir, paths, profile, debug_port, passwd_file, acl_file)
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
        "open=plaintext/anonymous; discovery=mTLS; strict=mTLS+password+ACL.",
    )
    parser.add_argument(
        "--debug-port",
        type=int,
        default=None,
        metavar="PORT",
        help="Add an unadvertised localhost-only plaintext listener on PORT "
        "(a local tap that needs no client cert).",
    )
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
    conf_path, hostname = prepare(args.state_dir, args.hostname, args.profile, args.debug_port)
    print(f"eBus laptop broker prepared for {hostname} [profile: {args.profile}]", file=sys.stderr)
    print(f"  config: {conf_path}", file=sys.stderr)
    print(f"  listener: {listener_summary(args.profile, hostname)}", file=sys.stderr)
    if args.debug_port:
        print(f"  debug:    127.0.0.1:{args.debug_port} (plaintext, unadvertised)", file=sys.stderr)

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
