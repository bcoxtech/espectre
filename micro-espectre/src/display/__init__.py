"""
Micro-ESPectre - Display Plugin Loader

load_display() picks a concrete DisplayInterface implementation based on
config.DISPLAY_DRIVER, so boot_main.py stays hardware-agnostic. Add a new
board's display by dropping a module in this package and adding one entry
to _DRIVERS below - no changes needed anywhere else.

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""

from src.display.base import DisplayInterface

_DRIVERS = {
    "st7789_waveshare147": ("src.display.st7789_waveshare147", "ST7789WaveshareDisplay"),
}


def load_display():
    """Return a DisplayInterface instance per config.DISPLAY_DRIVER, or None
    if unset (boards without a display leave this off)."""
    import src.config as config

    driver = getattr(config, "DISPLAY_DRIVER", None)
    if not driver:
        return None
    if driver not in _DRIVERS:
        raise ValueError("Unknown DISPLAY_DRIVER: {}".format(driver))
    module_name, class_name = _DRIVERS[driver]
    module = __import__(module_name, None, None, [class_name])
    return getattr(module, class_name)()
