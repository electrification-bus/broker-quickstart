"""Laptop-native (Mac MVP) broker deployment for broker-quickstart.

Runs Mosquitto + an mDNS advertiser host-native (no Docker, no root) so an eBus
publisher can discover the broker over real LAN multicast and connect the
spec-correct way, all on a single laptop. See the BQ-0lp epic.
"""
