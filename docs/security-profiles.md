# Security profiles

The broker ships three profiles, selected by one setting (laptop: `--profile`; Pi/Docker: `security_profile` in `config.toml`). A profile resolves to a set of MQTT listeners; that one set drives both the broker config and the mDNS advertisement, so what the broker enforces and what it advertises never drift. This document is the authoritative definition; the README table is the at-a-glance summary.

## The three profiles

| Profile | Listeners | Advertised (mDNS) | Use case |
|---------|-----------|-------------------|----------|
| `open` | plaintext MQTT, anonymous read **and** write | `_mqtt._tcp` | First-ten-minutes hello-world. **Never** expose to an untrusted network. |
| `discovery` *(default)* | mTLS (client cert required) **plus** a plaintext, read-only anonymous listener | `_secure-mqtt._tcp` **and** `_mqtt._tcp` | Most installs; matches eBus intent. Devices authenticate by client cert; a consumer can browse `$state` / `$description` without one. |
| `strict` | mTLS only (client cert required) | `_secure-mqtt._tcp` | Production / multi-tenant. No anonymous access at all. |

`discovery` is `strict` plus an advertised plaintext anonymous-read window. Both use the same client-cert authentication and the same ACL; they differ only in whether that anonymous window is open.

## Authentication: client certificates

The TLS profiles authenticate clients by **mutual TLS**: the client presents a certificate, the broker validates it against the dev CA, and the certificate's Common Name (CN) becomes the MQTT username (`use_identity_as_username`). There is no password backend. This is one of the authentication mechanisms the eBus spec allows (framework.md §24, §"mTLS Client Authentication"); a future deployment MAY instead issue username/password credentials via a registration endpoint, but these profiles pin down the *semantics* (what TLS / anonymous / ACL surface a client sees), not the mechanism.

A note on the split listeners in `discovery`: Mosquitto's `use_identity_as_username` requires `require_certificate true`, so a single listener cannot be both cert-optional and cert-identified (it rejects every client). Rather than fight that, `discovery` runs two listeners: an mTLS one for identified devices and a separate plaintext one for anonymous read. The plaintext window carries only non-sensitive lifecycle data, consistent with the spec's `_mqtt._tcp` role.

## Authorization: one shared ACL

All TLS/ACL profiles share one ACL:

```
# Lifecycle topics are readable by every client (anonymous included, where allowed):
topic read ebus/5/+/$state
topic read ebus/5/+/$description

# Each authenticated client owns its own device subtree:
pattern readwrite ebus/5/%u/#
```

- An **anonymous** client (no certificate, on the plaintext window) has no username, so it matches only the `topic read` lines: it can read lifecycle topics and nothing else (no writes, no property values).
- An **authenticated** client (cert CN = username) additionally matches the `pattern` line, so it owns `ebus/5/<cn>/#` (read and write) and can read every device's lifecycle.

`open` has no ACL: anonymous clients read and write everything.

## The debug port

`--debug-port N` (laptop) adds one more plaintext listener bound to `127.0.0.1`, with no ACL and **not advertised**. It is the same listener machinery as the anonymous-read window, but localhost-only and unrestricted, for a cert-free local `mosquitto_sub` or GUI client. It is a developer convenience, never part of the trust surface.

## Same behavior on every deployment

Because the profile resolves to one listener set, the laptop path and (when built) the Pi/Docker path render the same broker behavior from the same definition. A publisher's discovery and connection code is therefore identical against the laptop broker and against real hardware. The laptop renders this set in `laptop/profiles.py`; the Pi/Docker `config.toml` selects the same profile by name.
