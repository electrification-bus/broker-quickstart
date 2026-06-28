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

from .certs import CertPaths, default_local_hostname, ensure_server_cert

_TEMPLATE_DIR = Path(__file__).resolve().parent
MQTTS_PORT = 8883


def render_config(state_dir: Path, paths: CertPaths) -> Path:
    """Render mosquitto.conf into the state dir and return its path."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    rendered = env.get_template("mosquitto.conf.j2").render(
        mqtts_port=MQTTS_PORT,
        ca_cert=paths.ca_cert,
        server_cert=paths.server_cert,
        server_key=paths.server_key,
        state_dir=state_dir,
    )
    conf_path = state_dir / "mosquitto.conf"
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    conf_path.write_text(rendered)
    return conf_path


def resolve_mosquitto(explicit: str | None = None) -> str | None:
    """Return the mosquitto binary path (explicit override, else search PATH)."""
    return explicit or shutil.which("mosquitto")


def prepare(state_dir: Path, hostname: str | None = None) -> tuple[Path, str]:
    """Ensure certs + config exist. Returns (config_path, hostname).

    Idempotent: reuses existing CA/server cert/config unless the server cert's
    SAN no longer matches `hostname`.
    """
    hostname = hostname or default_local_hostname()
    state_dir = state_dir.resolve()
    paths = CertPaths(root=state_dir)
    ensure_server_cert(paths, hostname)
    conf_path = render_config(state_dir, paths)
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

    conf_path, hostname = prepare(args.state_dir, args.hostname)
    print(f"eBus laptop broker prepared for {hostname}", file=sys.stderr)
    print(f"  config: {conf_path}", file=sys.stderr)
    print(f"  mTLS:   {hostname}:{MQTTS_PORT} (client cert required)", file=sys.stderr)

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
