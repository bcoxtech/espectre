"""
Micro-ESPectre - Waveshare ESP32-S3-LCD-1.47 Display Smoke Test

Standalone hardware bring-up check - run this BEFORE enabling
DISPLAY_DRIVER in config_local.py, to isolate display problems from the
rest of the control-plane flow. Requires ./me deploy to have already pushed
src/st7789py.py, src/fonts/, and src/display/ to the device.

Usage:
    mpremote connect <port> run examples/lcd_smoke_test.py

Expected: screen fills red, then green after ~1s, then shows white "HELLO"
text near the top-left of the visible (172px-wide) area.

If the screen stays blank or shows garbage: suspect a MOSI/SCLK pin swap,
or that WAVESHARE_LCD147_X_OFFSET needs adjusting (all edited in
src/config.py). See the "Notable fixes" / bench-test note in the PR/plan
for context on why 240x320 mode is used for this 172x320 physical panel.

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""
import time
from src.display.st7789_waveshare147 import ST7789WaveshareDisplay
from src.st7789py import RED, GREEN

print('Initializing display...')
display = ST7789WaveshareDisplay()

print('Fill RED')
display.tft.fill(RED)
time.sleep(1)

print('Fill GREEN')
display.tft.fill(GREEN)
time.sleep(1)

print('Drawing HELLO text via update()')
display.update(state="IDLE", controller_ip="192.168.0.99", heap_free=123456, packet_count=0)

print('Done. If you saw red -> green -> a status readout, the pins and offset are correct.')
