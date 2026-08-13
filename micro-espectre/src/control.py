"""
Micro-ESPectre - Control Plane

Small UDP control channel so a host (e.g. Raspberry Pi relay) can discover
powered-on nodes and start/stop CSI streaming without a serial/USB tether.

Wire protocol (plain ASCII, one UDP port, both directions):
  Host -> Node (broadcast):  "KNOCK"                          (discovery probe)
  Node -> Host:               "HELLO <mac> <chip> <state>"    (knock reply / heartbeat)
  Host -> Node:                "START <duration_sec>"         (0 = infinite)
  Host -> Node:                "STOP"

The node stays silent until it receives a KNOCK. Whoever knocks becomes the
trusted controller for that boot session: the node starts heartbeating to
them and only honors START/STOP from that same source IP. A later KNOCK from
a different IP re-pairs (last knocker wins) - this also means the node
recovers automatically if the controller's own IP changes (e.g. Pi reboot),
with zero firmware reconfiguration.

Unauthenticated by design - same trust model as the raw CSI stream itself,
acceptable only because this runs on a physically isolated network segment.

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""

import socket
import time
import os
import network
import ubinascii
import src.config as config

STATE_IDLE = "IDLE"
STATE_STREAMING = "STREAMING"

HEARTBEAT_INTERVAL_MS = 5000


class StopFlag:
    """Mutable flag passed into stream_with_wlan() so a STOP command can interrupt it mid-loop."""

    def __init__(self):
        self.stop = False

    def reset(self):
        self.stop = False


def get_mac_str():
    """Return this device's STA MAC as a colon-separated hex string."""
    wlan = network.WLAN(network.STA_IF)
    mac_bytes = wlan.config("mac")
    return ubinascii.hexlify(mac_bytes, ":").decode()


def get_chip_str():
    machine = os.uname().machine.upper()
    for variant in ["S3", "S2", "C3", "C5", "C6"]:
        if variant in machine:
            return variant
    if "ESP32" in machine:
        return "ESP32"
    return machine


class ControlServer:
    """
    Non-blocking UDP control server. Silent until a KNOCK is received; the
    knocker becomes the trusted controller for START/STOP + heartbeats.
    """

    def __init__(self):
        self.port = getattr(config, "CONTROL_PORT", 5002)
        self.mac = get_mac_str()
        self.chip = get_chip_str()
        self.state = STATE_IDLE
        self.controller = None  # IP of whoever last knocked - None until paired
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", self.port))
        self.sock.settimeout(0)  # non-blocking: recvfrom raises OSError immediately if empty
        self._last_heartbeat = time.ticks_ms()

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass

    def set_state(self, state):
        self.state = state

    def _send_hello(self, dest_ip):
        msg = "HELLO {} {} {}".format(self.mac, self.chip, self.state)
        try:
            self.sock.sendto(msg.encode(), (dest_ip, self.port))
        except Exception as e:
            print("[control] hello send failed:", e)

    def send_loopback(self, message):
        """
        Send a command to this node's own control socket via 127.0.0.1 -
        used by a local trigger (e.g. the BOOT button) so its presses flow
        through the exact same poll_command() chokepoint as relay commands,
        instead of a second parallel start/stop code path.
        """
        try:
            self.sock.sendto(message.encode(), ("127.0.0.1", self.port))
        except Exception as e:
            print("[control] loopback send failed:", e)

    def maybe_send_heartbeat(self):
        """Send a heartbeat to the paired controller if the interval has elapsed."""
        if not self.controller:
            return
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_heartbeat) < HEARTBEAT_INTERVAL_MS:
            return
        self._last_heartbeat = now
        self._send_hello(self.controller)

    def poll_command(self):
        """
        Non-blocking check for an incoming message.

        KNOCK is always honored (that's how pairing happens/refreshes).
        START/STOP are only honored from the current paired controller.

        Returns a tuple (cmd, arg) for START/STOP, or None otherwise
        (nothing received, a KNOCK was just handled, or the sender isn't
        the trusted controller).
        """
        try:
            data, addr = self.sock.recvfrom(64)
        except OSError:
            return None  # would-block, expected on every idle poll

        sender_ip = addr[0]

        try:
            text = data.decode().strip()
        except Exception:
            return None

        parts = text.split()
        if not parts:
            return None

        cmd = parts[0].upper()

        if cmd == "KNOCK":
            self.controller = sender_ip
            self._last_heartbeat = time.ticks_ms()
            print("[control] knocked by {} - now trusted controller".format(sender_ip))
            self._send_hello(sender_ip)
            return None

        # Everything else must come from the paired controller, or from
        # loopback (a local trigger, e.g. the BOOT button - see
        # src/triggers/). Loopback does NOT mutate self.controller, so it
        # can never hijack pairing away from (or be affected by) a relay.
        if sender_ip != self.controller and sender_ip != "127.0.0.1":
            print("[control] ignored '{}' from untrusted {} (controller={})".format(cmd, sender_ip, self.controller))
            return None

        if cmd == "START":
            duration = 0
            if len(parts) > 1:
                try:
                    duration = int(parts[1])
                except ValueError:
                    duration = 0
            print("[control] START from controller (duration={})".format(duration))
            return ("START", duration)
        elif cmd == "STOP":
            print("[control] STOP from controller")
            return ("STOP", None)

        return None
