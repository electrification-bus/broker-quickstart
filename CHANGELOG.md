# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- laptop: host-native macOS broker (`python -m laptop.run`): Mosquitto with a dev CA and a server certificate for the host's `<name>.local`, the `open` / `discovery` / `strict` security profiles, and an mDNS advertisement of every listener the profile enables.
- laptop: mDNS through [ebus-service-discovery](https://github.com/electrification-bus/python-service-discovery): the broker also advertises `_ebus._tcp` / `_device-info._tcp` with `roles=broker-host`, and publishes no address records, so each network resolves the broker to the Mac's address on that network. `laptop.discover` finds an mTLS broker. (#10, #13)
- laptop: optional bridge to a remote broker, including username/password bridges. (#4, #5)
- `scripts/laptop-bench.sh`: the broker, the python-sdk utility-meter discovering it over mDNS, and a debug-port subscriber, in tmux. (#2, #6, #11)
- laptop: Mosquitto 2.1 configuration with the `mosquitto_acl_file` plugin attached per listener; 2.0 keeps `per_listener_settings`. (#14)

### Fixed

- laptop: the shared broker ACL rendered its world-readable lifecycle grants as `topic` lines, which Mosquitto applies only to clients with no username, so authenticated (mTLS) clients matched neither and received zero messages. The grants are now `pattern`. The ACL is also rewritten on every bring-up, so an on-disk copy from before this fix is refreshed rather than kept. (#7, #8)

### Changed

- laptop: authenticated clients now read the whole tree (`pattern read ebus/#`), not just lifecycle, so a consumer or bridged-in broker can read device data. Because the `discovery` profile shares one ACL between its mTLS and plaintext listeners, this also widens the anonymous plaintext read window from lifecycle to all readable data; use `strict` (no anonymous listener) to keep reads closed. Cross-device `/set` write remains out of scope for the static ACL (future dynamic-security tier). (#7)

### Planned

- Raspberry Pi: Ansible playbook (hostname from MAC, mDNS, TLS).
- Docker: broker container with example device and controller containers.
