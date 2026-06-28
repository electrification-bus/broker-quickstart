"""
Single source of truth for eBus mDNS conventions used by broker-quickstart.

These constants are consumed by:
- the FastAPI register service (mDNS advertisement, /config response)
- the Pi Ansible role `mdns` (templates mdns-publisher's input)
- the Docker compose (env vars for the broker + register containers)

The eBus framework spec is authoritative. These values track framework.md
§"MQTT Broker Advertisement"; if the spec changes, change them here. Do not
duplicate these strings anywhere else in the repo.
"""

from __future__ import annotations

# Service types per framework.md §"MQTT Broker Advertisement".
SECURE_MQTT_SERVICE_TYPE = "_secure-mqtt._tcp"
WS_SERVICE_TYPE = "_mqtt-ws._tcp"
WSS_SERVICE_TYPE = "_mqtt-wss._tcp"
PLAIN_MQTT_SERVICE_TYPE = "_mqtt._tcp"

# Default ports
MQTT_PLAIN_PORT = 1883        # open profile only
MQTTS_PORT = 8883             # discovery, strict
WS_PORT = 9001                # discovery, strict
WSS_PORT = 9002               # discovery, strict
REGISTER_HTTP_PORT = 8080     # FastAPI register service

# TXT record version and MQTT protocol value, per framework.md.
TXTVERS = "1"
MQTT_PROTOCOL_V5 = "mqtt-v5"

# TXT schema for the _secure-mqtt._tcp advertisement, per framework.md
# §"MQTT Broker Advertisement". (Supersedes the legacy SPAN-panel v/p/reg/ca/prof
# scheme, which is out of date; the spec is authoritative.)
SECURE_MQTT_TXT_KEYS = {
    "txtvers": "TXT record version (always '1')",
    "protocol": "MQTT protocol version (e.g. 'mqtt-v5')",
    "broker": "broker hostname (e.g. 'ebus-broker-a3f2.local')",
    "device_id": "broker host device id (e.g. 'nt-2025-c123y')",
}

# Hostname pattern: '{prefix}-{mac4}.local'
HOSTNAME_PREFIX_DEFAULT = "ebus-broker"


def build_hostname(mac4_hex: str, prefix: str = HOSTNAME_PREFIX_DEFAULT) -> str:
    """Compose the mDNS hostname from a 4-hex-digit MAC suffix."""
    return f"{prefix}-{mac4_hex.lower()}.local"
