"""
Micro-ESPectre - Relay Tools

Host-side control-plane client for boards running boot_main.py.

Author: Claude Code (for Brennan C)
License: GPLv3
"""

from .espectre_ctl import discover_all, send_command, resolve, registry, STALE_AFTER_SEC

__all__ = ['discover_all', 'send_command', 'resolve', 'registry', 'STALE_AFTER_SEC']
