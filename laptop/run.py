"""
One-command laptop runner: broker + mDNS advertiser together (BQ-x8v).

Brings up the whole Mac laptop deployment from a single command so the developer
does not juggle terminals:

    python -m laptop.run          # or the `ebus-laptop` console script

It mints certs + renders the config (idempotent), starts Mosquitto host-native on
8883, and advertises `_secure-mqtt._tcp` over mDNS. A single Ctrl-C (or SIGTERM)
tears both down cleanly, withdrawing the mDNS record *before* stopping the broker
so a discovering client never resolves a broker that is already gone.

No Docker, no systemd, no root. A small Python supervisor rather than honcho so
teardown order is explicit and there is no extra dependency.
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import threading
from pathlib import Path

from .advertiser import advertise, default_device_id
from .broker import listener_summary, prepare, profile_ports, resolve_mosquitto
from .profiles import DEFAULT_PROFILE, PROFILES

_TERM_TIMEOUT = 5.0  # seconds to wait for a graceful broker exit before SIGKILL


def _terminate(proc: subprocess.Popen) -> None:
    """Stop the broker subprocess: SIGTERM, then SIGKILL if it lingers."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=_TERM_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--state-dir", type=Path, default=Path("state/laptop"))
    parser.add_argument(
        "--hostname",
        default=None,
        help="Advertised <host>.local (default: this host's Bonjour LocalHostName).",
    )
    parser.add_argument(
        "--device-id",
        default=None,
        help="Stable device id for the TXT record (default: the host's .local label).",
    )
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default=DEFAULT_PROFILE,
        help=f"Security profile (default: {DEFAULT_PROFILE}). "
        "open=plaintext/anonymous; discovery=mTLS; strict=mTLS+password+ACL. "
        "Drives both the broker config and the mDNS advertisement.",
    )
    parser.add_argument(
        "--debug-port",
        type=int,
        default=None,
        metavar="PORT",
        help="Add an unadvertised localhost-only plaintext listener on PORT.",
    )
    parser.add_argument("--mosquitto", default=None, help="Path to the mosquitto binary.")
    args = parser.parse_args(argv)

    if args.debug_port is not None and args.debug_port in profile_ports(args.profile):
        parser.error(
            f"--debug-port {args.debug_port} collides with a {args.profile} listener; "
            "choose a different port."
        )

    mosquitto = resolve_mosquitto(args.mosquitto)
    if not mosquitto:
        print(
            "error: 'mosquitto' not found on PATH. Install it (Mac: 'brew install mosquitto') "
            "or pass --mosquitto.",
            file=sys.stderr,
        )
        return 1

    conf_path, hostname = prepare(args.state_dir, args.hostname, args.profile, args.debug_port)
    device_id = args.device_id or default_device_id(hostname)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    # Start the broker in its own session so a terminal Ctrl-C reaches only this
    # supervisor; we then drive an ordered teardown ourselves.
    proc = subprocess.Popen([mosquitto, "-c", str(conf_path)], start_new_session=True)
    print(f"eBus laptop broker [{args.profile}]: mosquitto pid {proc.pid}", file=sys.stderr)
    print(f"  {listener_summary(args.profile, hostname)}", file=sys.stderr)
    if args.debug_port:
        print(f"  debug tap: 127.0.0.1:{args.debug_port} (plaintext, unadvertised)", file=sys.stderr)

    exit_code = 0
    try:
        with advertise(hostname, device_id, args.profile):
            print("Both up. Ctrl-C to stop (withdraws mDNS, then stops the broker).", file=sys.stderr)
            while not stop.is_set():
                if proc.poll() is not None:
                    print(f"broker exited unexpectedly (code {proc.returncode}); shutting down.", file=sys.stderr)
                    exit_code = proc.returncode or 1
                    break
                stop.wait(0.5)
        # Leaving the context has withdrawn the mDNS record.
        print("mDNS advertisement withdrawn.", file=sys.stderr)
    finally:
        _terminate(proc)
        print("broker stopped.", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
