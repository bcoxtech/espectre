"""
Micro-ESPectre - Local Trigger Plugin Loader

load_trigger() picks a concrete TriggerInterface implementation based on
config.TRIGGER_DRIVER, so boot_main.py stays hardware-agnostic. Add a new
board's input by dropping a module in this package and adding one entry
to _DRIVERS below - no changes needed anywhere else.

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""

from src.triggers.base import TriggerInterface

_DRIVERS = {
    "gpio_button": ("src.triggers.gpio_button", "GpioButtonTrigger"),
}


def load_trigger():
    """Return a TriggerInterface instance per config.TRIGGER_DRIVER, or None
    if unset (boards without a local button leave this off)."""
    import src.config as config

    driver = getattr(config, "TRIGGER_DRIVER", None)
    if not driver:
        return None
    if driver not in _DRIVERS:
        raise ValueError("Unknown TRIGGER_DRIVER: {}".format(driver))
    module_name, class_name = _DRIVERS[driver]
    module = __import__(module_name, None, None, [class_name])
    return getattr(module, class_name)()
