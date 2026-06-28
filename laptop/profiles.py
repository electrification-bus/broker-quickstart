"""
Security profiles for the laptop broker (BQ-ydr epic).

The same three profiles the README and config/config.toml.j2 describe for the
Docker/Pi paths, applied to the laptop runner. A single `--profile` value drives
both the rendered Mosquitto config and the mDNS advertisement so they never
drift:

- open      : plaintext MQTT on all interfaces, anonymous. Advertised as
              `_mqtt._tcp`. For the first-ten-minutes demo only; never expose to
              an untrusted network.
- discovery : mTLS on 8883, client cert required, cert CN is the username
              (the default; matches eBus intent). Advertised as
              `_secure-mqtt._tcp`.
- strict    : discovery plus a password_file and acl_file (auth required and
              authorized everywhere). Advertised as `_secure-mqtt._tcp`.
"""

from __future__ import annotations

OPEN = "open"
DISCOVERY = "discovery"
STRICT = "strict"

PROFILES = (OPEN, DISCOVERY, STRICT)
DEFAULT_PROFILE = DISCOVERY

# Profiles whose listener uses TLS (and therefore need a server cert).
TLS_PROFILES = (DISCOVERY, STRICT)


def is_tls(profile: str) -> bool:
    return profile in TLS_PROFILES
