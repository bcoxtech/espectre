"""
Micro-ESPectre - Loopback UDP Smoke Test

Confirms this MicroPython build's lwIP has loopback enabled
(CONFIG_LWIP_NETIF_LOOPBACK) BEFORE relying on it for the local trigger
toggle (src/triggers/ sends START/STOP to 127.0.0.1 and expects the same
socket's recvfrom() to see it - see src/control.py's send_loopback()).

Usage:
    mpremote connect <port> run examples/loopback_smoke_test.py

Expected: prints "PASS: loopback works" within a couple seconds. If it
prints "FAIL" instead, loopback isn't available on this firmware build and
the local trigger toggle (button) won't work - relay-driven start/stop is
unaffected either way, since that never uses loopback.

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""
import socket
import time

PORT = 5099  # scratch port, unrelated to the real control port

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('0.0.0.0', PORT))
sock.settimeout(2)

sock.sendto(b'PING', ('127.0.0.1', PORT))

try:
    data, addr = sock.recvfrom(64)
    if data == b'PING':
        print('PASS: loopback works (received {} from {})'.format(data, addr))
    else:
        print('FAIL: received unexpected data:', data)
except OSError as e:
    print('FAIL: no packet received within timeout -', e)
finally:
    sock.close()
