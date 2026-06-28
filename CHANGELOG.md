# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial repo scaffolding: directory layout, top-level files, stub register service, Mosquitto config template (open profile), Docker compose skeleton, Ansible role skeletons, doc placeholders.

### Planned for v0.1.0

- M1: Docker compose end-to-end in `open` profile (broker + register + simple-device + simple-controller).
- M2: `discovery` and `strict` security profiles on Docker.
- M3: Ansible role for Raspberry Pi (hostname-from-MAC, mDNS, TLS, register service as systemd unit).
- M4: Documentation pass and upstream tracking issue for `tls-certificate-manager` harvest.
