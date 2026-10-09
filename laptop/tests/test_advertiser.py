"""Fast tests for the profile-to-Advertiser mapping (no network)."""

from __future__ import annotations

import pytest
from ebus_service_discovery import ebus

from laptop import advertiser
from laptop.profiles import DISCOVERY, OPEN, STRICT

HOST = "test-host.local"


@pytest.fixture(autouse=True)
def _own_hostname(monkeypatch):
    monkeypatch.setattr(advertiser, "default_local_hostname", lambda: HOST)


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (OPEN, [(ebus.MQTT_SERVICE, 1883)]),
        (STRICT, [(ebus.SECURE_MQTT_SERVICE, 8883)]),
        (DISCOVERY, [(ebus.SECURE_MQTT_SERVICE, 8883), (ebus.MQTT_SERVICE, 1883)]),
    ],
)
def test_brokers_follow_the_profile(profile, expected):
    _, kwargs = advertiser.advertiser_config(profile=profile)
    assert [(b.service_type, b.port) for b in kwargs["brokers"]] == expected


def test_identity_is_a_broker_host_named_for_the_host_label():
    identity, kwargs = advertiser.advertiser_config(profile=STRICT)
    assert identity.roles == (ebus.ROLE_BROKER_HOST,)
    assert identity.device_id == "test-host"
    assert kwargs["instance_name"] == "eBus broker test-host"


def test_secure_txt_names_the_cert_hostname():
    identity, kwargs = advertiser.advertiser_config(profile=STRICT)
    (secure,) = kwargs["brokers"]
    txt = secure.txt(identity, kwargs["server"])
    assert txt == {"txtvers": "1", "protocol": "mqtt-v5", "broker": HOST, "device_id": "test-host"}


def test_own_hostname_publishes_no_addresses():
    _, kwargs = advertiser.advertiser_config(profile=STRICT)
    assert kwargs["server"] == f"{HOST}."
    assert kwargs["addresses"] is None


def test_other_hostname_publishes_this_hosts_addresses(monkeypatch):
    monkeypatch.setattr(advertiser, "local_ip_addresses", lambda: ["192.0.2.10"])
    _, kwargs = advertiser.advertiser_config(hostname="ebus-broker-a3f2.local", profile=STRICT)
    assert kwargs["server"] == "ebus-broker-a3f2.local."
    assert kwargs["addresses"] == ["192.0.2.10"]
