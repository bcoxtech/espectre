"""
Micro-ESPectre - Control-Plane Boot Entry Point

Deployed to the device root as `main.py` (MicroPython's auto-run entry
point). Connects WiFi once at power-on, then idles announcing presence via
heartbeat and waiting for START/STOP commands from the configured control
host (see src.control) - no serial/USB tether required after this is
flashed.

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""
import time
from src.main import connect_wifi, cleanup_wifi
from src.control import ControlServer, StopFlag, STATE_IDLE, STATE_STREAMING
from src.csi_streamer import stream_with_wlan

IDLE_POLL_SLEEP_MS = 50  # throttle idle spin loop - battery-powered nodes


def main():
    print('Micro-ESPectre control-plane boot...')
    wlan = connect_wifi()
    ctl = ControlServer()
    print('[control] node ready: mac={} chip={} control_port={}'.format(
        ctl.mac, ctl.chip, ctl.port))

    stop_flag = StopFlag()

    try:
        while True:
            ctl.maybe_send_heartbeat()
            cmd = ctl.poll_command()

            if cmd is None:
                time.sleep_ms(IDLE_POLL_SLEEP_MS)
                continue

            action, arg = cmd

            if action == "START":
                dest_ip = ctl.host
                if not dest_ip:
                    print('[control] START ignored: no CONTROL_HOST configured')
                    continue
                stop_flag.reset()
                ctl.set_state(STATE_STREAMING)
                try:
                    stream_with_wlan(wlan, dest_ip, duration_sec=arg,
                                      stop_flag=stop_flag, ctl=ctl)
                except Exception as e:
                    print('[control] stream error:', e)
                ctl.set_state(STATE_IDLE)

            elif action == "STOP":
                # Nothing is actively streaming here (an in-progress stream
                # is interrupted directly inside stream_with_wlan's own poll)
                print('[control] STOP received while idle - nothing to stop')

    except KeyboardInterrupt:
        print('\n\nControl-plane stopped by user')

    finally:
        ctl.close()
        cleanup_wifi(wlan)


if __name__ == '__main__':
    main()
