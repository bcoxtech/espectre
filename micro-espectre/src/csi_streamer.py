"""
Micro-ESPectre - CSI UDP Streamer

Streams raw CSI I/Q data via UDP for real-time processing.

Packet format:
  Header (7 bytes):
    - Magic: 0x4353 ("CS") - 2 bytes
    - Chip type: 1 byte (0=unknown, 1=ESP32, 2=S2, 3=S3, 4=C3, 5=C5, 6=C6)
    - Flags: 1 byte (bit 0 = gain_locked)
    - Sequence number: 1 byte (0-255, wrapping)
    - Num subcarriers: 2 bytes (uint16, little-endian)
  Payload (N × 2 bytes):
    - I0, Q0, I1, Q1, ... (int8 each)

HT20 only: 64 subcarriers, packet size = 7 + 128 = 135 bytes

Usage:
    ./me stream --ip 192.168.1.100

Author: Francesco Pace <francesco.pace@gmail.com>
License: GPLv3
"""

import socket
import time
import gc
import os
import src.config as config
from src.config import NUM_SUBCARRIERS, EXPECTED_CSI_LEN
from src.traffic_generator import TrafficGenerator
from src.main import connect_wifi, cleanup_wifi, run_gain_lock
from src.utils import normalize_ht20_csi_payload

# Streaming configuration
STREAM_PORT = 5001
MAGIC_STREAM = 0x4353  # "CS" in little-endian

# Chip type codes (must match receiver)
CHIP_UNKNOWN = 0
CHIP_ESP32 = 1
CHIP_S2 = 2
CHIP_S3 = 3
CHIP_C3 = 4
CHIP_C5 = 5
CHIP_C6 = 6


def detect_chip_code():
    """Detect chip type and return code for protocol"""
    machine = os.uname().machine.upper()
    if "ESP32-C6" in machine or "ESP32C6" in machine:
        return CHIP_C6
    elif "ESP32-C5" in machine or "ESP32C5" in machine:
        return CHIP_C5
    elif "ESP32-C3" in machine or "ESP32C3" in machine:
        return CHIP_C3
    elif "ESP32-S3" in machine or "ESP32S3" in machine:
        return CHIP_S3
    elif "ESP32-S2" in machine or "ESP32S2" in machine:
        return CHIP_S2
    elif "ESP32" in machine:
        return CHIP_ESP32
    return CHIP_UNKNOWN


def _stream_loop(wlan, chip_code, dest_ip, duration_sec=0, stop_flag=None, ctl=None, trigger=None, display=None):
    """
    Core CSI streaming loop over an already-connected wlan.

    Owns the traffic generator and UDP socket for the duration of the call,
    but does NOT touch the WiFi connection itself (caller connects/cleans up).

    Args:
        wlan: already-connected WLAN instance with CSI enabled
        chip_code: protocol chip code (see CHIP_* constants)
        dest_ip: destination IP address
        duration_sec: duration in seconds (0 = infinite)
        stop_flag: optional src.control.StopFlag - checked each loop iteration
                   so a caller can interrupt an infinite/long stream early
        ctl: optional src.control.ControlServer - when provided, its socket is
             polled every iteration (non-blocking) for a STOP command, and
             heartbeats keep going out while this loop owns execution
        trigger: optional src.triggers.base.TriggerInterface - a local
                 button/etc that can only be caught here, since this loop is
                 the only thing running while streaming owns execution; a
                 press sends STOP over loopback via ctl (requires ctl)
        display: optional src.display.base.DisplayInterface - refreshed with
                 the same status shown while idle, plus live packet_count

    Returns:
        int: number of packets sent
    """
    duration_sec = int(duration_sec)

    # Start traffic generator
    traffic_mode = getattr(config, "TRAFFIC_GENERATOR_MODE", "ping")
    traffic_gen = TrafficGenerator(mode=traffic_mode)
    traffic_gen_started = False
    if config.TRAFFIC_GENERATOR_RATE > 0:
        if traffic_gen.start(config.TRAFFIC_GENERATOR_RATE):
            traffic_gen_started = True
            print(f"Traffic generator: {traffic_mode}, {config.TRAFFIC_GENERATOR_RATE} pps")
        time.sleep(1)

    # Phase 1: Gain lock (stabilizes AGC/FFT)
    # Do this BEFORE creating streaming socket to avoid ENOMEM
    gc.collect()
    agc, fft, needs_cv = run_gain_lock(wlan)
    # needs_cv = True means gain lock was skipped (AGC too low or not supported)
    # This flag is sent in each packet so the receiver knows if CV normalization is needed
    gain_locked = not needs_cv
    print(f"Gain locked: {gain_locked} (needs_cv_normalization={needs_cv})")

    # Create UDP socket for streaming (after gain lock to reduce memory pressure)
    gc.collect()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest_addr = (dest_ip, STREAM_PORT)

    # Packet format: <magic><chip><flags><seq><num_sc_u16><payload>
    # Pre-allocate packet buffer to avoid memory allocation in loop
    header_size = 7  # magic(2) + chip(1) + flags(1) + seq(1) + num_sc(2)
    payload_size = EXPECTED_CSI_LEN  # 64 SC × 2 bytes
    packet_size = header_size + payload_size

    # Build flags byte (bit 0 = gain_locked)
    flags = 0x01 if gain_locked else 0x00

    # Pre-allocate bytearray (reused every iteration)
    packet_buf = bytearray(packet_size)
    # Write static header fields (magic, chip, flags, num_sc) - only seq changes
    packet_buf[0] = MAGIC_STREAM & 0xFF
    packet_buf[1] = (MAGIC_STREAM >> 8) & 0xFF
    packet_buf[2] = chip_code
    packet_buf[3] = flags
    # packet_buf[4] = seq_num (updated in loop)
    packet_buf[5] = NUM_SUBCARRIERS & 0xFF
    packet_buf[6] = (NUM_SUBCARRIERS >> 8) & 0xFF

    print("")
    print(f"Streaming to: {dest_ip}:{STREAM_PORT}")
    print(f"Subcarriers:  {NUM_SUBCARRIERS} (HT20)")
    print(f"Packet size:  {packet_size} bytes")
    duration_str = "infinite" if duration_sec == 0 else str(duration_sec) + "s"
    print(f"Duration:     {duration_str}")
    print("")

    # Streaming loop
    start_time = time.ticks_ms()
    packet_count = 0
    filtered_count = 0
    seq_num = 0
    last_progress_time = start_time
    last_progress_count = 0
    collapse_logged = False
    remap_logged = False
    ht57_remap_buffer = bytearray(EXPECTED_CSI_LEN)

    try:
        while True:
            # Service the control channel (non-blocking): keep heartbeats
            # flowing and catch a STOP command while this loop has control.
            if ctl is not None:
                ctl.maybe_send_heartbeat()
                cmd = ctl.poll_command()
                if cmd is not None and cmd[0] == "STOP":
                    print("Streaming stopped by control command")
                    break

            # Local trigger (e.g. BOOT button): send STOP over loopback so
            # it's picked up by the same ctl.poll_command() chokepoint above
            # on the next iteration, rather than breaking directly here -
            # keeps one source of truth for "how streaming stops".
            if trigger is not None and ctl is not None and trigger.pressed():
                print("[trigger] press detected - sending loopback STOP")
                ctl.send_loopback("STOP")

            if display is not None and ctl is not None:
                display.update(ctl.state, ctl.controller, gc.mem_free(), packet_count)

            # Check external stop request (e.g. set programmatically by a caller)
            if stop_flag is not None and stop_flag.stop:
                print("Streaming stopped by control command")
                break

            # Check duration
            if duration_sec > 0:
                elapsed = time.ticks_diff(time.ticks_ms(), start_time) / 1000
                if elapsed >= duration_sec:
                    break

            frame = wlan.csi_read()
            if frame:
                csi_data, raw_len, remap_tag = normalize_ht20_csi_payload(
                    frame[5], EXPECTED_CSI_LEN, remap_buffer=ht57_remap_buffer
                )

                if csi_data is None:
                    filtered_count += 1
                    if filtered_count % 100 == 1:
                        print(
                            f"[WARN] Filtered {filtered_count} packets with wrong SC count (got {raw_len} bytes, expected {EXPECTED_CSI_LEN})"
                        )
                    del frame
                    continue

                if remap_tag in ("double_ht20", "double_ht57_and_remap") and not collapse_logged:
                    print("[INFO] CSI double-length collapse active: 256->128 and/or 228->114")
                    collapse_logged = True
                if remap_tag in ("ht57_to_64", "double_ht57_and_remap") and not remap_logged:
                    print("[INFO] CSI remap active: 57->64 SC (left_pad=4, right_pad=3)")
                    remap_logged = True
                del frame

                # Build and send packet using pre-allocated buffer (zero allocation)
                try:
                    # Update seq_num in header
                    packet_buf[4] = seq_num
                    # Copy CSI data into payload section
                    packet_buf[header_size:] = csi_data
                    # Send packet
                    sock.sendto(packet_buf, dest_addr)
                    packet_count += 1
                    seq_num = (seq_num + 1) & 0xFF
                except Exception:
                    pass

                # GC every 50 packets to prevent ENOMEM
                if packet_count % 50 == 0:
                    gc.collect()

                # Progress every 100 packets
                if packet_count % 100 == 0:
                    current_time = time.ticks_ms()
                    elapsed_block = time.ticks_diff(current_time, last_progress_time)
                    delta = packet_count - last_progress_count
                    pps = int((delta * 1000) / elapsed_block) if elapsed_block > 0 else 0

                    filter_str = f" | filtered: {filtered_count}" if filtered_count > 0 else ""
                    print(f"Sent {packet_count} pkts | {pps} pps | seq: {seq_num}{filter_str}")

                    last_progress_time = current_time
                    last_progress_count = packet_count
            else:
                time.sleep_us(100)

    except KeyboardInterrupt:
        print("\n\nStreaming stopped by user")

    finally:
        print("Cleaning up stream...")
        sock.close()
        if traffic_gen_started and traffic_gen.is_running():
            traffic_gen.stop()

    elapsed = time.ticks_diff(time.ticks_ms(), start_time) / 1000
    avg_pps = packet_count / elapsed if elapsed > 0 else 0
    print(f"\nTotal: {packet_count} packets in {elapsed:.1f}s ({avg_pps:.1f} pps avg)")
    return packet_count


def stream_csi(dest_ip, duration_sec=0):
    """
    Stream raw CSI I/Q data via UDP. Connects and fully tears down WiFi itself -
    use this for the standalone `./me stream` CLI path.

    Args:
        dest_ip: Destination IP address
        duration_sec: Duration in seconds (0 = infinite)
    """
    print("")
    print("=" * 60)
    print("  CSI UDP Streamer")
    print("=" * 60)

    # Connect WiFi (also enables CSI)
    wlan = connect_wifi()
    chip_type = os.uname().machine
    chip_code = detect_chip_code()
    print(f"Chip: {chip_type} (code: {chip_code})")

    print("")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    # Disable power-save for the duration of the stream - stable CSI capture
    # needs the radio held active. No restore needed: cleanup_wifi() below
    # tears the connection down fully once this one-shot stream ends.
    wlan.config(pm=wlan.PM_NONE)
    try:
        return _stream_loop(wlan, chip_code, dest_ip, duration_sec, stop_flag=None)
    finally:
        cleanup_wifi(wlan)


def stream_with_wlan(wlan, dest_ip, duration_sec=0, stop_flag=None, ctl=None, trigger=None, display=None):
    """
    Stream CSI using an already-connected wlan - does NOT touch the WiFi
    connection. Used by the control-plane boot loop, which needs WiFi to stay
    up across repeated start/stop cycles.

    Args:
        wlan: already-connected WLAN instance with CSI enabled
        dest_ip: Destination IP address
        duration_sec: Duration in seconds (0 = infinite)
        stop_flag: src.control.StopFlag - set .stop = True to interrupt early
        ctl: src.control.ControlServer - polled for STOP + kept heartbeating
             while this call owns the loop
        trigger: optional src.triggers.base.TriggerInterface - see _stream_loop
        display: optional src.display.base.DisplayInterface - see _stream_loop

    Returns:
        int: number of packets sent
    """
    chip_type = os.uname().machine
    chip_code = detect_chip_code()
    print(f"Chip: {chip_type} (code: {chip_code})")
    # Disable power-save only for this stream's duration, then restore it -
    # the control-plane loop reuses this same wlan across many start/stop
    # cycles and can sit idle for hours, so PM_NONE must not linger.
    wlan.config(pm=wlan.PM_NONE)
    try:
        return _stream_loop(
            wlan, chip_code, dest_ip, duration_sec, stop_flag=stop_flag, ctl=ctl, trigger=trigger, display=display
        )
    finally:
        wlan.config(pm=wlan.PM_PERFORMANCE)
