# Laptop quickstart (macOS)

Run a complete eBus loop on a single Mac with no Docker, no Raspberry Pi, and no SPAN panel: a Mosquitto broker with mTLS, a real mDNS advertisement, and a publisher that *discovers* the broker over mDNS and connects the spec-correct way. This is the deployment to reach for when you want to exercise discovery itself, because Docker Desktop on Mac runs its daemon in a LinuxKit VM with no usable LAN multicast, so mDNS broker discovery can only be tested host-native.

Everything here is host-native and user-writable: no `sudo`, and all generated state (the dev CA, the server and client certs, the Mosquitto config) lives under `state/laptop/`, which is gitignored.

## Prerequisites

- macOS (this path is Mac-first; Linux support comes later).
- Mosquitto, from Homebrew: `brew install mosquitto`.
- Python 3.11+. Create a virtualenv and install this package with its laptop extra:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[laptop]'
```

The laptop extra pulls in `python-zeroconf` (for the mDNS advertiser); `cryptography`, `paho-mqtt`, and `jinja2` come from the base dependencies.

## 1. Start the broker and advertiser (one command)

```bash
python -m laptop.run        # or, after install, the `ebus-laptop` console script
```

This single command:

1. mints a dev CA and a Mosquitto server certificate whose SAN includes your host's `<name>.local` (the name Bonjour already publishes) plus its routable LAN IPs;
2. renders `state/laptop/mosquitto.conf`;
3. starts Mosquitto host-native in the default `discovery` profile: an mTLS listener on 8883 where devices authenticate by client certificate (the cert CN becomes the MQTT username), plus a plaintext, read-only anonymous listener on 1883 so a consumer can browse `$state` / `$description` without a cert;
4. advertises both services over mDNS (`_secure-mqtt._tcp` and `_mqtt._tcp`), riding your existing `<name>.local`.

(See [Security profiles](#security-profiles-and-extra-listeners) below to run `strict`, which drops the anonymous listener, or `open`.)

Leave it running. A single Ctrl-C withdraws the mDNS record first and then stops the broker, so a client never resolves a broker that is already gone.

### macOS firewall prompt

The first time Mosquitto (and Python, for mDNS) binds a listening socket, macOS may pop up "Do you want the application to accept incoming network connections?". Click **Allow**. If you miss the prompt or discovery from other devices does not work later, check **System Settings > Network > Firewall**: either turn the firewall off for this dev session, or add `mosquitto` and your Python interpreter to the allowed list. The single-laptop loop in step 3 works over loopback even if you deny the prompt; allowing it is what makes the broker discoverable from other machines on the LAN.

## 2. Verify the mDNS advertisement

Browse for the service, then resolve it, using Bonjour's own command-line tool:

```bash
dns-sd -B _secure-mqtt._tcp
dns-sd -L "eBus broker <your-host-label>" _secure-mqtt._tcp
```

The resolve (`-L`) output should show the broker reachable at `<name>.local.:8883` with TXT records matching `framework.md`:

```
txtvers=1 protocol=mqtt-v5 broker=<name>.local device_id=<your-host-label>
```

You can also confirm self-discovery programmatically (a zeroconf `ServiceBrowser` on the same host):

```bash
python -m laptop.verify_advertiser
```

## 3. Run the discovering publisher (the loop)

In a second terminal, with `laptop.run` still up:

```bash
python -m laptop.verify_loop
```

This is the end-to-end proof. It discovers the broker via mDNS (it does not hardcode a host), mints a client cert from the dev CA, connects over mTLS to the discovered `<name>.local:8883` while validating the server certificate against the dev CA, then publishes a retained Homie `$state` and reads it back. Expected output:

```
✓ discovered broker: <name>.local:8883
✓ mTLS publish to discovered <name>.local:8883 as 'laptop-loop'
    connected (CONNACK): True (reason: Success)
    published + read back 'ebus/5/laptop-loop/$state'='ready': True
```

`verify_loop` is a self-contained validation stand-in for a real eBus publisher. The production utility-meter simulator lives in [`python-sdk/examples/utility-meter`](https://github.com/electrification-bus/python-sdk/tree/main/examples); its change to discover the broker over mDNS rather than a hardcoded host is tracked in the python-sdk repo, not here. See [`python-sdk/examples/simple-span-controller`](https://github.com/electrification-bus/python-sdk/tree/main/examples) for the same mDNS discovery pattern against a real broker.

## 4. Connect a GUI client (MQTT Explorer)

For a quick **read-only** look in the `discovery` profile, point [MQTT Explorer](https://mqtt-explorer.com/) at the plaintext anonymous listener with no certificate at all:

- **Host**: `<name>.local` (or `localhost`), **Port**: `1883`, **Encryption (TLS)**: off.

You will see `$state` / `$description` for every device; publishing or reading property values is denied by the ACL. (The `--debug-port` from [below](#localhost-debug-tap) gives the same cert-free access on localhost with no ACL.)

To **write**, or to read full device data, connect over mTLS with a client certificate. Mint one:

```bash
python -m laptop.certs --client my-explorer
```

Then configure MQTT Explorer:

- **Host**: `<name>.local`, **Port**: `8883`, **Encryption (TLS)**: on, **Validate certificate**: on.
- **CA certificate**: `state/laptop/ca/ca.crt`
- **Client certificate**: `state/laptop/clients/my-explorer/client.crt`
- **Client key**: `state/laptop/clients/my-explorer/client.key`

Validation succeeds because the server certificate chains to the dev CA and its SAN contains `<name>.local`. That client (CN `my-explorer`) can read all lifecycle topics and read/write its own `ebus/5/my-explorer/#` subtree.

## Security profiles and extra listeners

The runner defaults to the `discovery` profile. A single `--profile` flag drives both the broker config and the mDNS advertisement so they never drift. Each profile resolves to a set of listeners (full definition: [`security-profiles.md`](security-profiles.md)):

| Profile | Listeners | Advertised as |
|---------|-----------|---------------|
| `open` | plaintext 1883, anonymous read **and** write | `_mqtt._tcp` |
| `discovery` *(default)* | mTLS 8883 (devices) **plus** a plaintext read-only anonymous listener | `_secure-mqtt._tcp` **and** `_mqtt._tcp` |
| `strict` | mTLS 8883 only (no anonymous access) | `_secure-mqtt._tcp` |

```bash
python -m laptop.run --profile open        # plaintext hello-world; never expose to an untrusted network
python -m laptop.run --profile discovery   # the default: devices use mTLS, consumers can read lifecycle anonymously
python -m laptop.run --profile strict      # mTLS only, no anonymous access
```

Authentication is by client certificate (the cert CN becomes the MQTT username); there is no password. Authorization is one shared ACL: anonymous clients can read `$state` / `$description`, and each cert-authenticated client owns its `ebus/5/<cn>/#` subtree. `discovery` is `strict` plus the advertised plaintext anonymous-read window, so a consumer can browse devices without a cert.

### Localhost debug tap

Add an unadvertised, loopback-only plaintext listener alongside any TLS profile, for a quick `mosquitto_sub` or GUI client without juggling certs:

```bash
python -m laptop.run --profile discovery --debug-port 1884
mosquitto_sub -h localhost -p 1884 -t 'ebus/5/#' -v
```

It binds `127.0.0.1` only (unreachable from the LAN) and is never advertised over mDNS.

## Run the whole loop with a real publisher (the bench)

Sections 1 and 3 bring up the broker and a synthetic check. To watch a real eBus publisher discover and reach the broker, `scripts/laptop-bench.sh` runs the full loop in three tmux windows: the broker (with the debug port), the [utility-meter reference publisher](https://github.com/electrification-bus/python-sdk/tree/main/examples) run with `--discover`, and a cert-free `mosquitto_sub` watching the published tree on the debug port.

You need a clone of [`python-sdk`](https://github.com/electrification-bus/python-sdk) and a Python that can import both this package and `ebus-sdk`. The simplest setup is one venv with both installed:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[laptop]' -e '/path/to/python-sdk[mdns]'
```

Then run the bench, pointing it at your python-sdk clone:

```bash
SDK_REPO=/path/to/python-sdk ./scripts/laptop-bench.sh
```

The `meter` window logs `reason=brokerDiscovered,host=<name>.local,port=8883` followed by `reason=utilityMeterReady`, and the `sub` window shows the device's Homie tree (`ebus/5/<meter-id>/$state`, `$description`, `info/*`, `meter/*`, …) appearing. The meter found the broker over mDNS and connected over mTLS, with no hardcoded host. Stop everything with:

```bash
./scripts/laptop-bench.sh stop
```

Useful knobs (env vars): `PROFILE` (`discovery` or `strict`), `METER_ID`, `METER_CFG`, `DEBUG_PORT`. See the header of `scripts/laptop-bench.sh`.

## What got created

| Path | What it is |
|------|------------|
| `state/laptop/ca/ca.crt`, `ca.key` | the dev CA (root of trust) |
| `state/laptop/server/server.crt`, `server.key` | Mosquitto's server cert (SAN = `<name>.local`, `localhost`, loopback, LAN IPs) |
| `state/laptop/clients/<id>/client.{crt,key}` | per-client certs; the CN becomes the MQTT username |
| `state/laptop/mosquitto.conf` | the rendered broker config |

All of `state/` is gitignored; the keys never leave your machine.

## Handy individual commands

| Command | Purpose |
|---------|---------|
| `python -m laptop.run [--profile P] [--debug-port N]` | broker + advertiser together (the one-command runner) |
| `python -m laptop.broker` | broker only (mint certs, render config, run Mosquitto) |
| `python -m laptop.advertiser` | advertiser only |
| `python -m laptop.discover [--json]` | discover a broker via mDNS (host + port); the consumer-side mirror of the advertiser |
| `python -m laptop.certs --client <id>` | mint the CA / server / a client cert |
| `python -m laptop.verify_handshake` | mTLS handshake self-test (connect by `<name>.local`) |
| `python -m laptop.verify_advertiser` | mDNS self-discovery self-test |
| `python -m laptop.verify_loop` | full discover then mTLS then publish loop |

## Troubleshooting

- **`dns-sd -B` shows nothing.** The advertiser is not running, or the firewall blocked it. Confirm `laptop.run` is up and allow the firewall prompt (step 1).
- **TLS handshake fails after your machine name or network changed.** The server cert SAN is tied to your `<name>.local` and your IPs. The broker re-mints automatically when the `.local` name changes or a new IP appears; if needed, force it with `python -m laptop.certs --regenerate`.
- **Client cert rejected after `--regenerate-ca`.** Regenerating the CA orphans every previously minted client cert. Re-mint your client certs (`python -m laptop.certs --client <id>`) and reconfigure the GUI client.
- **Port 8883 already in use.** Another Mosquitto (or an earlier `laptop.run`) is still running. Stop it, or check with `lsof -nP -iTCP:8883 -sTCP:LISTEN`.

## How this maps to a real deployment

The laptop broker is a faithful stand-in for a real eBus broker host: same mDNS service type (`_secure-mqtt._tcp`), same TXT records (`framework.md` §"MQTT Broker Advertisement"), and the same mTLS trust surface. A publisher's discovery and TLS code path is therefore identical against this laptop broker and against real hardware. The difference from the Raspberry Pi path is only in plumbing: python-zeroconf instead of Avahi (Bonjour owns mDNS on macOS), a one-command supervisor instead of systemd, and user-writable paths instead of root. See the [security profiles](security-profiles.md) for the `open` / `discovery` / `strict` definitions and how to tighten the broker.
