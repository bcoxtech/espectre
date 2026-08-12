"""
Micro-ESPectre - Local Trigger Interface

Base class for local start/stop triggers (a physical button today; could be
a touch pad, dial, etc. on a future board). Named "trigger" rather than
"control" deliberately - src.control.ControlServer ("ctl") already owns that
word for the UDP control channel, and reusing it here would be a constant
source of confusion in code and logs.

boot_main.py talks only to this interface via src.triggers.load_trigger() -
never to a concrete implementation directly.

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""


class TriggerInterface:
    """Subclass and implement pressed()."""

    def pressed(self):
        """
        Return True at most once per physical activation (debounced edge).
        Safe to call every loop iteration (idle or streaming).
        """
        raise NotImplementedError
