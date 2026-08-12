"""
Micro-ESPectre - Display Interface

Base class for on-device status displays. Boards vary in what screen (if any)
they carry, so boot_main.py talks only to this interface via
src.display.load_display() - never to a concrete driver directly.

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""


class DisplayInterface:
    """Subclass and implement update()."""

    def update(self, state, controller_ip, heap_free, packet_count):
        """
        Refresh the on-device status readout. Safe to call every loop
        iteration (idle or streaming) - implementations are expected to
        rate-limit their own actual redraws internally.

        Args:
            state: "IDLE" or "STREAMING" (src.control.STATE_*)
            controller_ip: paired controller's IP, or None if unpaired
            heap_free: gc.mem_free() at call time
            packet_count: CSI packets sent so far this stream (0 when idle)
        """
        raise NotImplementedError
