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
3. starts Mosquitto host-native on port 8883 requiring client certificates (`require_certificate` + `use_identity_as_username`, so the client cert's CN becomes the MQTT username);
4. advertises `_secure-mqtt._tcp` over mDNS, riding your existing `<name>.local`.

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

Because the broker requires client certificates, point a GUI client at the dev CA and give it a client cert. First mint one:

```bash
python -m laptop.certs --client my-explorer
```

Then configure [MQTT Explorer](https://mqtt-explorer.com/):

- **Host**: `<name>.local`, **Port**: `8883`, **Encryption (TLS)**: on, **Validate certificate**: on.
- **CA certificate**: `state/laptop/ca/ca.crt`
- **Client certificate**: `state/laptop/clients/my-explorer/client.crt`
- **Client key**: `state/laptop/clients/my-explorer/client.key`

Validation succeeds because the server certificate chains to the dev CA and its SAN contains `<name>.local`.

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
| `python -m laptop.run` | broker + advertiser together (the one-command runner) |
| `python -m laptop.broker` | broker only (mint certs, render config, run Mosquitto) |
| `python -m laptop.advertiser` | advertiser only |
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

The laptop broker is a faithful stand-in for a real eBus broker host: same mDNS service type (`_secure-mqtt._tcp`), same TXT records (`framework.md` §"MQTT Broker Advertisement"), and the same mTLS trust surface. A publisher's discovery and TLS code path is therefore identical against this laptop broker and against real hardware. The difference from the Raspberry Pi path is only in plumbing: python-zeroconf instead of Avahi (Bonjour owns mDNS on macOS), a one-command supervisor instead of systemd, and user-writable paths instead of root. See the [security profiles](security-profiles.md) for tightening the broker beyond this MVP's mTLS listener.
