"""
Micro-ESPectre - Control-Plane Relay Tests

Tests for relay/espectre_ctl.py: broadcast-address auto-detection, the
--broadcast override, and the node registry (resolve/heartbeat/node-ID
assignment). Network I/O (the module-level UDP socket) and disk I/O (the
node registry file) are exercised only through monkeypatched seams so
these never touch the real .nodes.json or a live board.

Author: Claude <noreply@anthropic.com>
License: GPLv3
"""

import socket

import pytest

from relay import espectre_ctl


@pytest.fixture
def ctl(monkeypatch, tmp_path):
    """espectre_ctl module with an isolated registry and node file per test."""
    monkeypatch.setattr(espectre_ctl, "NODES_FILE", tmp_path / ".nodes.json")
    monkeypatch.setattr(espectre_ctl, "registry", {})
    return espectre_ctl


class TestDetectBroadcastAddr:
    """detect_broadcast_addr() computes the broadcast from a live interface's
    IP/netmask instead of relying on a subnet hardcoded at deploy time."""

    def test_computes_broadcast_from_ip_and_netmask(self, monkeypatch):
        def fake_iface_ipv4(iface, request):
            assert iface == "eth0.100"
            if request == espectre_ctl.SIOCGIFADDR:
                return "192.168.50.250"
            if request == espectre_ctl.SIOCGIFNETMASK:
                return "255.255.255.0"
            raise AssertionError(f"unexpected ioctl request {request!r}")

        monkeypatch.setattr(espectre_ctl, "_iface_ipv4", fake_iface_ipv4)
        assert espectre_ctl.detect_broadcast_addr("eth0.100") == "192.168.50.255"

    def test_respects_a_non_default_prefix(self, monkeypatch):
        def fake_iface_ipv4(iface, request):
            if request == espectre_ctl.SIOCGIFADDR:
                return "10.0.0.5"
            return "255.255.255.128"  # /25

        monkeypatch.setattr(espectre_ctl, "_iface_ipv4", fake_iface_ipv4)
        assert espectre_ctl.detect_broadcast_addr("eth0.100") == "10.0.0.127"

    def test_falls_back_when_interface_is_unreadable(self, monkeypatch, capsys):
        def raise_oserror(iface, request):
            raise OSError("No such device")

        monkeypatch.setattr(espectre_ctl, "_iface_ipv4", raise_oserror)
        result = espectre_ctl.detect_broadcast_addr("eth0.100")
        assert result == espectre_ctl.FALLBACK_BROADCAST_ADDR
        assert "falling back" in capsys.readouterr().out


class TestBroadcastCliOverride:
    """--broadcast is a top-level flag (it must also cover the no-subcommand
    daemon mode), so it has to appear before the subcommand token."""

    def test_broadcast_flag_overrides_and_command_still_parses(self):
        args = espectre_ctl.build_parser().parse_args(["--broadcast", "10.0.0.255", "knock", "3"])
        assert args.broadcast == "10.0.0.255"
        assert args.command == "knock"
        assert args.timeout == 3.0

    def test_broadcast_flag_defaults_to_none(self):
        args = espectre_ctl.build_parser().parse_args(["list"])
        assert args.broadcast is None
        assert args.command == "list"

    def test_broadcast_flag_works_with_no_subcommand(self):
        args = espectre_ctl.build_parser().parse_args(["--broadcast", "10.0.0.255"])
        assert args.broadcast == "10.0.0.255"
        assert args.command is None


class TestRegistryResolve:
    def test_resolve_by_node_id_mac_or_ip(self, ctl):
        ctl.registry["aa:bb:cc:dd:ee:ff"] = {
            "node_id": "node1",
            "ip": "192.168.50.83",
            "chip": "S3",
            "state": "IDLE",
            "last_seen": 100.0,
        }
        for identifier in ("node1", "aa:bb:cc:dd:ee:ff", "192.168.50.83"):
            mac, entry = ctl.resolve(identifier)
            assert mac == "aa:bb:cc:dd:ee:ff"
            assert entry["node_id"] == "node1"

    def test_resolve_unknown_identifier(self, ctl):
        mac, entry = ctl.resolve("node9")
        assert mac is None
        assert entry is None


class TestAssignNodeId:
    def test_first_node_gets_node1(self, ctl):
        assert ctl._assign_node_id("aa:bb:cc:dd:ee:ff") == "node1"

    def test_next_id_skips_taken_ones(self, ctl):
        ctl.registry["aa:aa:aa:aa:aa:aa"] = {"node_id": "node1"}
        ctl.registry["bb:bb:bb:bb:bb:bb"] = {"node_id": "node2"}
        assert ctl._assign_node_id("cc:cc:cc:cc:cc:cc") == "node3"

    def test_fills_a_gap_left_by_a_removed_node(self, ctl):
        ctl.registry["bb:bb:bb:bb:bb:bb"] = {"node_id": "node2"}
        assert ctl._assign_node_id("cc:cc:cc:cc:cc:cc") == "node1"


class TestHandleHeartbeat:
    def test_discovers_a_new_node_and_persists_it(self, ctl):
        ctl.handle_heartbeat(b"HELLO aa:bb:cc:dd:ee:ff S3 IDLE", ("192.168.50.83", 5002), verbose=False)

        assert "aa:bb:cc:dd:ee:ff" in ctl.registry
        entry = ctl.registry["aa:bb:cc:dd:ee:ff"]
        assert entry["node_id"] == "node1"
        assert entry["ip"] == "192.168.50.83"
        assert entry["chip"] == "S3"
        assert entry["state"] == "IDLE"

        assert ctl.NODES_FILE.exists()

    def test_reuses_existing_node_id_on_repeat_heartbeat(self, ctl):
        ctl.handle_heartbeat(b"HELLO aa:bb:cc:dd:ee:ff S3 IDLE", ("192.168.50.83", 5002), verbose=False)
        ctl.handle_heartbeat(b"HELLO aa:bb:cc:dd:ee:ff S3 STREAMING", ("192.168.50.83", 5002), verbose=False)

        assert ctl.registry["aa:bb:cc:dd:ee:ff"]["node_id"] == "node1"
        assert ctl.registry["aa:bb:cc:dd:ee:ff"]["state"] == "STREAMING"

    @pytest.mark.parametrize(
        "data",
        [
            b"KNOCK",
            b"HELLO aa:bb:cc:dd:ee:ff S3",  # missing state field
            b"BYE aa:bb:cc:dd:ee:ff S3 IDLE",  # wrong verb
        ],
    )
    def test_ignores_malformed_or_unrelated_packets(self, ctl, data):
        ctl.handle_heartbeat(data, ("192.168.50.83", 5002), verbose=False)
        assert ctl.registry == {}
