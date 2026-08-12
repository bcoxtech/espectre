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
guess ((240-172)//2 = 34) - not yet hardware-verified, see the display bench
smoke test before trusting on-screen alignment.

Pin numbers (SPI + reset/cs/dc/backlight) are sourced from a third-party
MicroPython/LVGL config example for this exact board, also not yet
hardware-verified - see bench smoke test.

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""
import time
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


class ST7789WaveshareDisplay(DisplayInterface):
    def __init__(self):
        spi = SPI(
            2,
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
        self._last_update = 0
        self._last_shown = None

    def update(self, state, controller_ip, heap_free, packet_count):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_update) < config.DISPLAY_UPDATE_INTERVAL_MS:
            return
        shown = (state, controller_ip, heap_free // 1024, packet_count)
        if shown == self._last_shown:
            self._last_update = now
            return
        self._last_update = now
        self._last_shown = shown

        x = self._x_offset
        self.tft.fill(BLACK)
        color = GREEN if state == "STREAMING" else WHITE
        self.tft.text(FONT, "State: {}".format(state), x, 4, color, BLACK)
        self.tft.text(FONT, "Ctrl:  {}".format(controller_ip or "none"), x, 4 + _LINE_HEIGHT, WHITE, BLACK)
        self.tft.text(FONT, "Heap:  {}KB".format(heap_free // 1024), x, 4 + 2 * _LINE_HEIGHT, WHITE, BLACK)
        if state == "STREAMING":
            self.tft.text(FONT, "Pkts:  {}".format(packet_count), x, 4 + 3 * _LINE_HEIGHT, YELLOW, BLACK)
