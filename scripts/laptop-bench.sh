#!/usr/bin/env bash
#
# laptop-bench.sh — full single-laptop eBus loop in tmux.
#
# Brings up the whole loop so you can watch a real publisher discover and reach
# the broker, all on one Mac, in three tmux windows:
#
#   broker — broker-quickstart's laptop runner: Mosquitto (mTLS) + the mDNS
#            advertiser + an unadvertised loopback debug port.
#   meter  — the eBus utility-meter reference publisher from the python-sdk,
#            run with --discover so it finds the broker over mDNS and connects
#            over mTLS (no hardcoded host).
#   sub    — mosquitto_sub watching ebus/# on the cert-free debug port, so you
#            can see the published Homie tree without a client cert.
#
# This is generic eBus: nothing here is integration- or vendor-specific.
#
# Teardown:  ./scripts/laptop-bench.sh stop
#
# Required env:
#   SDK_REPO   path to a clone of github.com/electrification-bus/python-sdk
# Optional env:
#   PY         python to use; must have broker-quickstart's deps AND ebus-sdk
#              importable. Easiest: a venv with
#                pip install -e <broker-quickstart>[laptop] -e <python-sdk>[mdns]
#              (default: python3)
#   PROFILE    broker security profile: discovery | strict   (default: discovery)
#   METER_ID   meter id / client-cert CN              (default: laptop-meter-001)
#   METER_CFG  meter config JSON  (default: $SDK_REPO/examples/utility-meter-cfg.example.json)
#   STATE      broker-quickstart state dir            (default: <repo>/state/laptop)
#   DEBUG_PORT loopback plaintext debug port          (default: 1884)
#   SESSION    tmux session name                      (default: ebus-laptop-bench)
#   RUN_ARGS   extra args appended verbatim to the `laptop.run` broker command,
#              e.g. to attach a bridge:
#                RUN_ARGS='--span-bridge SERIAL --span-bridge-address 127.0.0.1:18883'
#              (word-split in the shell; fine for this dev script)
#
set -euo pipefail

# Locate the broker-quickstart repo root from this script's own location.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PY="${PY:-python3}"
PROFILE="${PROFILE:-discovery}"
METER_ID="${METER_ID:-laptop-meter-001}"
STATE="${STATE:-$REPO_ROOT/state/laptop}"
DEBUG_PORT="${DEBUG_PORT:-1884}"
SESSION="${SESSION:-ebus-laptop-bench}"
RUN_ARGS="${RUN_ARGS:-}"   # extra args appended to the laptop.run broker command
BROKER_CFG_JSON="${TMPDIR:-/tmp}/${SESSION}-broker-cfg.json"

case "${1:-}" in
  stop|down|--stop|kill)
    if tmux kill-session -t "$SESSION" 2>/dev/null; then
      echo "killed tmux session '$SESSION'"
    else
      echo "no tmux session '$SESSION' running"
    fi
    rm -f "$BROKER_CFG_JSON"
    exit 0
    ;;
esac

# Preconditions.
command -v tmux      >/dev/null || { echo "tmux not found (brew install tmux)" >&2; exit 1; }
command -v mosquitto >/dev/null || { echo "mosquitto not found (brew install mosquitto)" >&2; exit 1; }
: "${SDK_REPO:?set SDK_REPO to your clone of electrification-bus/python-sdk}"
[ -x "$SDK_REPO/examples/utility-meter" ] || { echo "not found/executable: $SDK_REPO/examples/utility-meter" >&2; exit 1; }
METER_CFG="${METER_CFG:-$SDK_REPO/examples/utility-meter-cfg.example.json}"
[ -f "$METER_CFG" ] || { echo "meter config not found: $METER_CFG" >&2; exit 1; }

# Mint the dev CA, server cert, and the meter's client cert (idempotent).
( cd "$REPO_ROOT" && "$PY" -m laptop.certs --state-dir "$STATE" --client "$METER_ID" )

# The publisher's broker config: --discover fills in host/port from mDNS; this
# only needs to supply the TLS material.
cat > "$BROKER_CFG_JSON" <<EOF
{
  "host": "mdns-discovered",
  "port": 0,
  "use_tls": true,
  "tls_insecure": false,
  "tls_ca_cert": "$STATE/ca/ca.crt",
  "tls_client_cert": "$STATE/clients/$METER_ID/client.crt",
  "tls_client_key": "$STATE/clients/$METER_ID/client.key",
  "homie_domains": ["ebus"]
}
EOF

tmux kill-session -t "$SESSION" 2>/dev/null || true

# broker — laptop runner (broker + advertiser + debug port)
tmux new-session -d -s "$SESSION" -n broker -c "$REPO_ROOT"
tmux send-keys -t "$SESSION:broker" \
  "'$PY' -m laptop.run --state-dir '$STATE' --profile '$PROFILE' --debug-port $DEBUG_PORT $RUN_ARGS" C-m

# meter — the utility-meter, discovering the broker over mDNS
tmux new-window -t "$SESSION" -n meter -c "$SDK_REPO"
tmux send-keys -t "$SESSION:meter" \
  "sleep 2; '$PY' '$SDK_REPO/examples/utility-meter' --config '$METER_CFG' --broker-config '$BROKER_CFG_JSON' --discover --discover-timeout 20" C-m

# sub — cert-free view of the published tree via the debug port
tmux new-window -t "$SESSION" -n sub -c "$REPO_ROOT"
tmux send-keys -t "$SESSION:sub" \
  "sleep 4; mosquitto_sub -h localhost -p $DEBUG_PORT -t 'ebus/#' -v" C-m

tmux select-window -t "$SESSION:broker"

echo "tmux session '$SESSION' ready (broker / meter / sub)."
echo "Stop: ./scripts/laptop-bench.sh stop"

if [ "${TERM_PROGRAM:-}" = "iTerm.app" ]; then
  exec tmux -CC attach -t "$SESSION"
else
  exec tmux attach -t "$SESSION"
fi
