# broker-quickstart

Turnkey eBus MQTT broker bundle for new developers.

Three paths to a running eBus broker on your network:

1. **Laptop** (macOS, real mDNS) — host-native Mosquitto plus a python-zeroconf advertiser, brought up with one command, no Docker and no root. Exercises real mDNS discovery on a single Mac, where Docker Desktop's LinuxKit VM cannot. See [`docs/laptop-quickstart.md`](docs/laptop-quickstart.md).
2. **Raspberry Pi** (real LAN) — Ansible playbook against stock Raspberry Pi OS. Claims `ebus-broker-<mac4>.local`, advertises via mDNS, generates a TLS CA + server cert, exposes a per-device registration API. See [`docs/pi-quickstart.md`](docs/pi-quickstart.md).
3. **Docker** (any machine) — `docker compose up` brings a broker plus example device and controller containers. No mDNS; containers reach each other by service name. See [`docs/docker-quickstart.md`](docs/docker-quickstart.md).

The Docker and Pi paths bundle the same components: Mosquitto, a small FastAPI register service, and reused [`tls-certificate-manager`](https://github.com/electrification-bus/tls-certificate-manager) + [`mdns-publisher`](https://github.com/electrification-bus/mdns-publisher) modules. Example device + controller containers are built from [`python-sdk/examples/`](https://github.com/electrification-bus/python-sdk/tree/main/examples) and pulled from `ghcr.io/electrification-bus/`.

## Security profiles

The broker ships with three profiles, switchable via a single config setting plus a restart:

| Profile | Anon read | Anon write | TLS | Per-device auth | Use case |
|---|---|---|---|---|---|
| `open` *(default)* | all topics | all topics | off | optional | First-10-minutes hello-world |
| `discovery` | `$state` + `$description` only | none | required | required for writes | Most installs; matches eBus intent |
| `strict` | none | none | required | required everywhere | Production / multi-tenant LAN |

`open` is the default to make the first demo trivial. **Do not expose an `open`-mode broker to an untrusted network.** See [`docs/security-profiles.md`](docs/security-profiles.md) for the tightening procedure.

## Status

Scaffolding in progress. See [`CHANGELOG.md`](CHANGELOG.md) and the v0.1 milestones in beads (`bd ready` from the shadow repo).

## License

MIT — see [`LICENSE`](LICENSE).
