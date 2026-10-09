# broker-quickstart

Turnkey eBus MQTT broker for new developers: Mosquitto with mTLS, advertised over mDNS the way a real eBus broker host advertises itself.

## Laptop (macOS)

Host-native Mosquitto plus an mDNS advertiser ([`ebus-service-discovery`](https://github.com/electrification-bus/python-service-discovery)), brought up with one command, no Docker and no root. A one-command bench (`scripts/laptop-bench.sh`) runs the whole loop: the broker plus a real eBus publisher that discovers it over mDNS and connects over mTLS. See [`docs/laptop-quickstart.md`](docs/laptop-quickstart.md).

## Simulated devices on the Mac (ebus-dev-fleet)

[`ebus-dev-fleet`](https://github.com/electrification-bus/ebus-dev-fleet) runs simulated eBus devices as containers on the same Mac (Apple `container`). They discover the laptop broker over mDNS and connect over mTLS, alongside real devices on your LAN: each side resolves the broker to the Mac's address on its own network.

## Planned

- **Raspberry Pi**: an Ansible playbook for stock Raspberry Pi OS that claims `ebus-broker-<mac4>.local`, advertises over mDNS, and mints the TLS CA and server certificate.
- **Docker**: a broker container with example device and controller containers built from [`python-sdk/examples/`](https://github.com/electrification-bus/python-sdk/tree/main/examples).

## Security profiles

The broker ships with three profiles, selected with `--profile`:

| Profile | Anon read | Anon write | Device auth | Use case |
|---|---|---|---|---|
| `open` | all topics | all topics | off (plaintext) | First-10-minutes hello-world |
| `discovery` *(default)* | all topics | none | mTLS client cert | Most installs; matches eBus intent |
| `strict` | none | none | mTLS client cert | Production / multi-tenant LAN |

Authentication is by client certificate (the cert CN is the MQTT username), authorized by a shared ACL: every client reads the whole tree, and each device writes only its own `ebus/5/<cn>/#` subtree. `discovery` runs an mTLS listener for devices plus a plaintext, read-only anonymous listener, so a consumer can read device data without a cert; `strict` drops that anonymous window. **Do not expose an `open`-mode broker to an untrusted network.** See [`docs/security-profiles.md`](docs/security-profiles.md) for the full definition.

## License

MIT — see [`LICENSE`](LICENSE).
