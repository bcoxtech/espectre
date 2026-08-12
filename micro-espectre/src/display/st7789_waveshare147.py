"""
Micro-ESPectre - Waveshare ESP32-S3-LCD-1.47 Display Driver

Concrete DisplayInterface for the Waveshare ESP32-S3-LCD-1.47 board's
onboard 1.47" ST7789 SPI TFT (172x320 physical panel).

Hardware note: the vendored src/st7789py.py driver only natively supports
240x320 / 240x240 / 135x240 / 128x128 panels - 172x320 isn't in its
_SUPPORTED_DISPLAYS table. The documented workaround (used for the sibling
ESP32-C6-LCD-1.47, same panel) is to initialize the controller in its native
240x320 mode and draw within an X-offset window sized to the actual 172px
visible width. WAVESHARE_LCD147_X_OFFSET in config.py defaults to a centered
guess ((240-172)//2 = 34) - confirmed correct on real hardware via
examples/lcd_smoke_test.py (2026-08-12).

Pin numbers (SPI + reset/cs/dc/backlight) are sourced from a third-party
MicroPython/LVGL config example for this exact board - also bench-verified.

Gotcha found during bring-up: SPI host id 2 hard-crashes/reboots this board
(not a catchable Python exception - a full chip panic and USB
disconnect/reconnect). SPI host id 1 works correctly. If porting this to a
different ESP32-S3 board/firmware, don't assume id 2 is safe to try first.

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""
import time
import gc
from machine import Pin, SPI
import src.config as config
from src.display.base import DisplayInterface
from src.st7789py import ST7789, BLACK, WHITE, GREEN, YELLOW
from src.fonts import vga1_8x8 as FONT

# Native controller resolution the vendored driver supports - NOT the
# physical panel size. The 172px-wide panel is centered within this.
_CTRL_WIDTH = 240
_CTRL_HEIGHT = 320

_LINE_HEIGHT = FONT.HEIGHT + 4
# Small TFT modules like this often physically hide a few pixels of the
# addressable area under the bezel - pad text in from every edge rather
# than starting flush against x_offset/0.
_MARGIN_X = 8
_MARGIN_TOP = 8
_VISIBLE_WIDTH = 172
_TEXT_WIDTH = _VISIBLE_WIDTH - 2 * _MARGIN_X


class ST7789WaveshareDisplay(DisplayInterface):
    def __init__(self):
        spi = SPI(
            1,
            baudrate=20_000_000,
            sck=Pin(config.WAVESHARE_LCD147_SCLK_PIN),
            mosi=Pin(config.WAVESHARE_LCD147_MOSI_PIN),
        )
        self._x_offset = getattr(config, "WAVESHARE_LCD147_X_OFFSET", 34)
        self.tft = ST7789(
            spi,
            _CTRL_WIDTH,
            _CTRL_HEIGHT,
            reset=Pin(config.WAVESHARE_LCD147_RST_PIN, Pin.OUT),
            cs=Pin(config.WAVESHARE_LCD147_CS_PIN, Pin.OUT),
            dc=Pin(config.WAVESHARE_LCD147_DC_PIN, Pin.OUT),
            backlight=Pin(config.WAVESHARE_LCD147_BL_PIN, Pin.OUT),
            rotation=0,
        )
        self.tft.fill(BLACK)
        # Total heap is invariant after boot (mem_alloc + mem_free never
        # changes), so capturing it once here is enough to compute a
        # percentage on every update() call without recomputing it.
        self._total_heap = gc.mem_alloc() + gc.mem_free()
        self._last_update = 0
        self._last_lines = None

    def update(self, state, controller_ip, heap_free, packet_count):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_update) < config.DISPLAY_UPDATE_INTERVAL_MS:
            return
        heap_pct = heap_free * 100 // self._total_heap
        streaming = state == "STREAMING"
        lines = (
            ("State: {}".format(state), GREEN if streaming else WHITE),
            ("Ctrl:  {}".format(controller_ip or "none"), WHITE),
            ("Heap:  {}% free".format(heap_pct), WHITE),
            ("Pkts:  {}".format(packet_count), YELLOW) if streaming else ("", WHITE),
        )
        if lines == self._last_lines:
            self._last_update = now
            return
        self._last_update = now

        # Redraw only the lines that actually changed, instead of a
        # full-screen fill+redraw every cycle - avoids the visible flash a
        # full clear causes on every update.
        x = self._x_offset + _MARGIN_X
        y = _MARGIN_TOP
        prev_lines = self._last_lines or (None, None, None, None)
        for i, (text, color) in enumerate(lines):
            if prev_lines[i] == (text, color):
                continue
            line_y = y + i * _LINE_HEIGHT
            self.tft.fill_rect(x, line_y, _TEXT_WIDTH, FONT.HEIGHT, BLACK)
            if text:
                self.tft.text(FONT, text, x, line_y, color, BLACK)
        self._last_lines = lines
