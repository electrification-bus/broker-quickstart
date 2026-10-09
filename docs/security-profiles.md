# Security profiles

The broker ships three profiles, selected by one setting (laptop: `--profile`; Pi/Docker: `security_profile` in `config.toml`). A profile resolves to a set of MQTT listeners; that one set drives both the broker config and the mDNS advertisement, so what the broker enforces and what it advertises never drift. This document is the authoritative definition; the README table is the at-a-glance summary.

## The three profiles

| Profile | Listeners | Advertised (mDNS) | Use case |
|---------|-----------|-------------------|----------|
| `open` | plaintext MQTT, anonymous read **and** write | `_mqtt._tcp` | First-ten-minutes hello-world. **Never** expose to an untrusted network. |
| `discovery` *(default)* | mTLS (client cert required) **plus** a plaintext, read-only anonymous listener | `_secure-mqtt._tcp` **and** `_mqtt._tcp` | Most installs; matches eBus intent. Devices authenticate by client cert; a consumer can read device data without one. |
| `strict` | mTLS only (client cert required) | `_secure-mqtt._tcp` | Production / multi-tenant. No anonymous access at all. |

`discovery` is `strict` plus an advertised plaintext anonymous-read window. Both use the same client-cert authentication and the same ACL; they differ only in whether that anonymous window is open.

## Authentication: client certificates

The TLS profiles authenticate clients by **mutual TLS**: the client presents a certificate, the broker validates it against the dev CA, and the certificate's Common Name (CN) becomes the MQTT username (`use_identity_as_username`). There is no password backend. This is one of the authentication mechanisms the eBus spec allows (framework.md §24, §"mTLS Client Authentication"); a future deployment MAY instead issue username/password credentials via a registration endpoint, but these profiles pin down the *semantics* (what TLS / anonymous / ACL surface a client sees), not the mechanism.

A note on the split listeners in `discovery`: Mosquitto's `use_identity_as_username` requires `require_certificate true`, so a single listener cannot be both cert-optional and cert-identified (it rejects every client). Rather than fight that, `discovery` runs two listeners: an mTLS one for identified devices and a separate plaintext one for anonymous read. That window is read-only but unrestricted: under the shared ACL it carries all readable device data, not just lifecycle. Use `strict` (no anonymous window) to close reads.

## Authorization: one shared ACL

All TLS/ACL profiles share one ACL:

```
# There are no read restrictions: any client may read the whole tree.
pattern read ebus/#

# Each authenticated client owns (may publish) its own device subtree:
pattern readwrite ebus/5/%u/#
```

- Read is unrestricted: every client, anonymous or authenticated, may read the whole tree. On `discovery` that includes the anonymous plaintext window, so a certless LAN client reads all device data, not just lifecycle. Use `strict` (no anonymous listener) if reads must be closed.
- Write stays narrow: an **authenticated** client (cert CN = username) owns `ebus/5/<cn>/#`, its own subtree, through the `%u` grant. An **anonymous** client has no username, so it matches no write grant and cannot publish. The plaintext window refuses a client that presents a username (an empty password file), so a certless client cannot claim another client's grants by naming itself after it. Grants beyond its own subtree come from the client registry (below).

### Per-client grants: roles and child devices

The client registry (`<state-dir>/clients.json`, managed with `python -m laptop.clients`) adds grants for named clients, rendered into the ACL as `user <cn>` sections after the shared patterns. Roles are framework.md's taxonomy (§"Authorization (Broker-Side ACLs)"):

| Role | Writes beyond its own subtree |
|---|---|
| `observer`, `sensor` *(default)* | nothing |
| `controller`, `automation` | `/set` on every device (`ebus/5/+/+/+/set`) and Homie broadcasts (`ebus/5/$broadcast/#`) |
| `admin` | the whole tree |

A controller's grant is `/set` topics only, so it cannot overwrite another device's `$state` or `$description`. A client may also list child device ids: children share their root's MQTT connection (framework.md §"Device Topology"), so the root writes each child's `ebus/5/<child>/#`. Anonymous clients have no username, so no `user` section reaches them.

```bash
python -m laptop.clients set my-controller --role controller
python -m laptop.clients set my-panel --child my-panel-circuit-1 --child my-panel-circuit-2
python -m laptop.clients list
python -m laptop.clients remove my-controller
```

Each change rewrites the ACL and signals a running broker to reload (SIGHUP), so it applies without a restart.

`open` has no ACL: anonymous clients read and write everything.

## The debug port

`--debug-port N` (laptop) adds one more plaintext listener bound to `127.0.0.1`, with no ACL and **not advertised**. It is the same listener machinery as the anonymous-read window, but localhost-only and unrestricted, for a cert-free local `mosquitto_sub` or GUI client. It is a developer convenience, never part of the trust surface.

## Same behavior on every deployment

Because the profile resolves to one listener set, the laptop path and (when built) the Pi/Docker path render the same broker behavior from the same definition. A publisher's discovery and connection code is therefore identical against the laptop broker and against real hardware. The laptop renders this set in `laptop/profiles.py`; the Pi/Docker `config.toml` selects the same profile by name.
