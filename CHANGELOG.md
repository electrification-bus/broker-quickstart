# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial repo scaffolding: directory layout, top-level files, stub register service, Mosquitto config template (open profile), Docker compose skeleton, Ansible role skeletons, doc placeholders.

### Fixed

- laptop: the shared broker ACL rendered its world-readable lifecycle grants as `topic` lines, which Mosquitto applies only to clients with no username, so authenticated (mTLS) clients matched neither and received zero messages. The grants are now `pattern`. The ACL is also rewritten on every bring-up, so an on-disk copy from before this fix is refreshed rather than kept. (#7, #8)

### Changed

- laptop: authenticated clients now read the whole tree (`pattern read ebus/#`), not just lifecycle, so a consumer or bridged-in broker can read device data. Because the `discovery` profile shares one ACL between its mTLS and plaintext listeners, this also widens the anonymous plaintext read window from lifecycle to all readable data; use `strict` (no anonymous listener) to keep reads closed. Cross-device `/set` write remains out of scope for the static ACL (future dynamic-security tier). (#7)

### Planned for v0.1.0

- M1: Docker compose end-to-end in `open` profile (broker + register + simple-device + simple-controller).
- M2: `discovery` and `strict` security profiles on Docker.
- M3: Ansible role for Raspberry Pi (hostname-from-MAC, mDNS, TLS, register service as systemd unit).
- M4: Documentation pass and upstream tracking issue for `tls-certificate-manager` harvest.
