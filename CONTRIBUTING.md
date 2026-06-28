# Contributing to broker-quickstart

Thanks for your interest in contributing! `broker-quickstart` is a turnkey [Electrification Bus (eBus)](https://ebus.energy) MQTT broker bundle for new developers. It stands up a Mosquitto broker (with a small registration service and TLS material) three ways: in Docker, on a Raspberry Pi via Ansible, and host-native on a Mac laptop. The goal is that someone new to eBus gets a spec-correct broker running, with mDNS discovery and mTLS, in minutes.

## How to contribute

### Discussions

Use [Discussions](https://github.com/electrification-bus/broker-quickstart/discussions) for:

- Open-ended questions about deployment ("how should I run this on my LAN / behind X?").
- Proposed new deployment targets, profiles, or convenience tooling, worth aligning on before writing the code.
- Questions about the relationship between this bundle and the [Electrification Bus specification](https://github.com/electrification-bus/specification); the broker aims to be a faithful stand-in for a real eBus broker host, so spec-level questions belong in the spec repo's Discussions.
- Thinking out loud about a change before scoping it.

### Issues

Use [Issues](https://github.com/electrification-bus/broker-quickstart/issues) for actionable changes:

- Bug reports with reproduction steps (which path: Docker / Pi / laptop; OS; Mosquitto version; the exact command and output).
- Spec-conformance gaps where the broker's advertisement, TXT records, or trust surface diverge from the [specification](https://github.com/electrification-bus/specification) (note which document and section).
- Concrete feature requests with a clear scope and a use case.
- Documentation gaps where a specific quickstart or README change is intended.

If you are not sure whether something is an Issue or a Discussion, start with a Discussion; we can convert it later.

### Pull requests

Pull requests are welcome.

- For small fixes (typos, doc tweaks, low-risk bug fixes), open a PR directly.
- For substantive changes (a new deployment path, changes to the security profiles, new dependencies, changes to the mDNS advertisement or TLS trust surface), open a Discussion or Issue first so we can align on scope.
- **Spec conformance is the north star.** This broker exists to be indistinguishable, from a publisher's point of view, from a real eBus broker host. When a change is normative (mDNS service types, TXT records, topic structure, the security profiles), point to the [specification](https://github.com/electrification-bus/specification) section it implements. The authoritative mDNS schema lives in `framework.md` §"MQTT Broker Advertisement"; do not reintroduce older ad-hoc TXT schemes.
- **Generic capabilities live upstream.** This repo is a downstream integration. Generic, reusable eBus building blocks (TLS certificate management, the mDNS publisher) belong in their own upstream projects ([`tls-certificate-manager`](https://github.com/electrification-bus/tls-certificate-manager), [`mdns-publisher`](https://github.com/electrification-bus/mdns-publisher)); this bundle should only add the laptop / Pi / Docker specialization on top. If you find yourself forking generic cert or discovery logic here, propose the change upstream instead.
- **Mind the security posture.** The `open` profile is intentionally wide open for the first-ten-minutes demo and must never become the default for anything network-exposed. Changes that touch authentication, TLS, the profiles, or the default bind addresses get extra scrutiny; explain the threat model in the PR.
- **Lint before sending.** The repo uses [ruff](https://github.com/astral-sh/ruff); run `ruff check` and `ruff format` locally before pushing.
- **Tests where they fit.** New Python behavior should come with a `pytest` test; for the deployment paths, describe how you validated end to end (the commands you ran and what you observed).
- **Keep comments to a minimum.** Prefer self-explanatory code; reserve comments for the non-obvious *why* (a spec quirk, a Mosquitto behavior, a macOS-versus-Linux difference).

One commit per logical change is fine; we do not require squash or any particular branch naming.

## Supported Python

The Python tooling targets **Python 3.10+**. On 3.10 the `tomli` backport is pulled in automatically; 3.11+ uses the stdlib `tomllib`.

## Code of conduct

Be respectful and constructive. We appreciate everyone who takes the time to file an issue, start a discussion, or send a pull request.

## Maintenance posture

`broker-quickstart` is an active alpha project. Updates and maintenance, including responses to issues, happen on an "as time and resources permit" basis. It is maintained alongside the [Electrification Bus specification](https://github.com/electrification-bus/specification); see the specification repo's README §Governance for the project's long-term governance context.
