"""
Micro-ESPectre - BOOT Button Smoke Test

Standalone check that GPIO0 (the board's BOOT button - the only physical
button here that's software-readable; RESET is a hardware-only EN/CHIP_PU
line) works as a normal debounced input once the app is running, and that
config.TRIGGER_DEBOUNCE_MS feels right.

Usage:
    mpremote connect <port> run examples/button_smoke_test.py
    (then press the BOOT button a few times, Ctrl-C to stop)

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""
import time
from src.triggers.gpio_button import GpioButtonTrigger

print('Watching BOOT button (GPIO0) - press it a few times, Ctrl-C to stop.')
trigger = GpioButtonTrigger()
count = 0

try:
    while True:
        if trigger.pressed():
            count += 1
            print('press #{} detected'.format(count))
        time.sleep_ms(20)
except KeyboardInterrupt:
    print('\nStopped. Total presses detected: {}'.format(count))
