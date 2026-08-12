"""
Micro-ESPectre - Single GPIO Button Trigger

Concrete TriggerInterface for a single active-low momentary button on one
GPIO pin (the Waveshare ESP32-S3-LCD-1.47's BOOT button, GPIO0 - freely
usable as a normal input once the app is running; its sibling RESET button
is wired to EN/CHIP_PU and can't be read in software at all, so it's not
usable here).

Level-based debounce on read (not interrupt-driven) - matches this
codebase's single-threaded, no-asyncio control flow; every call is O(1) and
safe from both the idle loop and the hot CSI streaming loop.

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""
import time
from machine import Pin
import src.config as config
from src.triggers.base import TriggerInterface


class GpioButtonTrigger(TriggerInterface):
    def __init__(self):
        self.pin = Pin(config.GPIO_BUTTON_PIN, Pin.IN, Pin.PULL_UP)
        self._last_state = self.pin.value()  # 1 = released (pulled up)
        self._last_change = time.ticks_ms()

    def pressed(self):
        now = time.ticks_ms()
        level = self.pin.value()
        if level == self._last_state:
            return False
        if time.ticks_diff(now, self._last_change) < config.TRIGGER_DEBOUNCE_MS:
            return False
        self._last_state = level
        self._last_change = now
        return level == 0  # falling edge = press (active-low)
