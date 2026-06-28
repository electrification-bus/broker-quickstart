"""
Security profiles for the eBus broker (BQ-ydr; reconciled in BQ-9j9).

A profile resolves to a SET OF LISTENERS. That one list drives everything: the
rendered Mosquitto config (one block per listener) and the mDNS advertisement
(one record per advertised listener, under its service type). Keeping the list
as the single source is what keeps the config and the advertisement from
drifting.

mosquitto constraint: `use_identity_as_username` (cert CN as the MQTT username)
requires `require_certificate true`, so a single listener cannot be both
cert-optional and cert-identified. We therefore split roles across listeners
rather than fight it:

- open      : one plaintext listener (anonymous read+write). Advertised
              `_mqtt._tcp`. First-ten-minutes demo only; never expose to an
              untrusted network.
- strict    : one mTLS listener (client cert REQUIRED, cert CN = username),
              shared ACL. No anonymous access. Advertised `_secure-mqtt._tcp`.
- discovery : strict's mTLS listener PLUS a plaintext, read-only anonymous
              listener so a consumer can browse `$state` / `$description`
              without a cert. Advertised as `_secure-mqtt._tcp` AND `_mqtt._tcp`.
              The default; matches eBus intent.

All TLS/ACL profiles share one ACL (docs/security-profiles.md): lifecycle topics
are world-readable; each authenticated client (cert CN = username) owns its
`ebus/5/<user>/#` subtree. The plaintext anonymous listener is read-only because
anonymous clients have no username and so match only the `topic read` lines.

A `--debug-port` adds one more plaintext listener bound to 127.0.0.1 and NOT
advertised: the same listener machinery, localhost-only, for a cert-free local
tap.
"""

from __future__ import annotations

from dataclasses import dataclass

from mdns.constants import (
    MQTT_PLAIN_PORT,
    MQTTS_PORT,
    PLAIN_MQTT_SERVICE_TYPE,
    SECURE_MQTT_SERVICE_TYPE,
)

OPEN = "open"
DISCOVERY = "discovery"
STRICT = "strict"

PROFILES = (OPEN, DISCOVERY, STRICT)
DEFAULT_PROFILE = DISCOVERY


@dataclass(frozen=True)
class Listener:
    """One Mosquitto listener and how (if at all) it is advertised over mDNS."""

    port: int
    tls: bool
    require_certificate: bool
    use_identity_as_username: bool
    acl: bool
    bind: str | None  # None = all interfaces; "127.0.0.1" = localhost only
    advertised: bool
    service_type: str | None  # mDNS service type when advertised


def _mtls_listener() -> Listener:
    return Listener(
        port=MQTTS_PORT,
        tls=True,
        require_certificate=True,
        use_identity_as_username=True,
        acl=True,
        bind=None,
        advertised=True,
        service_type=SECURE_MQTT_SERVICE_TYPE,
    )


def _plaintext_listener(*, port: int, acl: bool, bind: str | None, advertised: bool) -> Listener:
    return Listener(
        port=port,
        tls=False,
        require_certificate=False,
        use_identity_as_username=False,
        acl=acl,
        bind=bind,
        advertised=advertised,
        service_type=PLAIN_MQTT_SERVICE_TYPE if advertised else None,
    )


def listeners(profile: str, debug_port: int | None = None) -> list[Listener]:
    """Resolve a profile (+ optional debug port) into its set of listeners."""
    result: list[Listener] = []
    if profile == OPEN:
        result.append(
            _plaintext_listener(port=MQTT_PLAIN_PORT, acl=False, bind=None, advertised=True)
        )
    else:  # discovery, strict
        result.append(_mtls_listener())
        if profile == DISCOVERY:
            # Plaintext, read-only (by ACL), LAN-advertised anonymous-read window.
            result.append(
                _plaintext_listener(port=MQTT_PLAIN_PORT, acl=True, bind=None, advertised=True)
            )
    if debug_port is not None:
        # Localhost-only plaintext tap; never advertised, no ACL.
        result.append(
            _plaintext_listener(port=debug_port, acl=False, bind="127.0.0.1", advertised=False)
        )
    return result


def advertised_listeners(profile: str) -> list[Listener]:
    """The listeners a profile advertises over mDNS (excludes the debug tap)."""
    return [listener_ for listener_ in listeners(profile) if listener_.advertised]


def is_tls(profile: str) -> bool:
    return any(listener_.tls for listener_ in listeners(profile))
