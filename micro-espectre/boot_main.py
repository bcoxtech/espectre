"""
Micro-ESPectre - Control-Plane Boot Entry Point

Deployed to the device root as `main.py` (MicroPython's auto-run entry
point). Connects WiFi once at power-on, then stays silent until a host
broadcasts a KNOCK - the knocker becomes the trusted controller for
START/STOP commands and heartbeats (see src.control) - no serial/USB
tether required after this is flashed.

Optionally drives an on-device display and/or a local start/stop trigger
(e.g. a BOOT-button toggle) - see src.display / src.triggers. Both are
opt-in per board via config.DISPLAY_DRIVER / config.TRIGGER_DRIVER; boards
that leave them unset behave exactly as before.

Author: Claude Code (for Brennan C)
License: GPLv3 (matches parent project)
"""

import gc
import time
from src.main import connect_wifi, cleanup_wifi
from src.control import ControlServer, StopFlag, STATE_IDLE, STATE_STREAMING
from src.csi_streamer import stream_with_wlan
from src.display import load_display
from src.triggers import load_trigger
import src.config as config

IDLE_POLL_SLEEP_MS = 50  # throttle idle spin loop - battery-powered nodes


def main():
    print("Micro-ESPectre control-plane boot...")
    wlan = connect_wifi()
    ctl = ControlServer()
    print("[control] node ready: mac={} chip={} control_port={}".format(ctl.mac, ctl.chip, ctl.port))

    display = load_display()
    trigger = load_trigger()

    stop_flag = StopFlag()

    try:
        while True:
            ctl.maybe_send_heartbeat()
            cmd = ctl.poll_command()

            # Idle-side half of the local trigger toggle: a press here always
            # means "start" (a press while streaming is caught inside
            # stream_with_wlan's own loop, since this outer loop doesn't run
            # while that owns execution). Sent over loopback so it flows
            # through the same poll_command() chokepoint as a relay START,
            # picked up on the next iteration below.
            if trigger is not None and trigger.pressed():
                print("[trigger] press detected while idle - sending loopback START")
                ctl.send_loopback("START 0")

            if display is not None:
                display.update(ctl.state, ctl.controller, gc.mem_free(), 0)

            if cmd is None:
                time.sleep_ms(IDLE_POLL_SLEEP_MS)
                continue

            action, arg = cmd

            if action == "START":
                # Falls back to CONTROL_HOST when unpaired, so a local
                # trigger press works standalone (e.g. bench testing with no
                # relay running) rather than being silently dropped.
                dest_ip = ctl.controller or getattr(config, "CONTROL_HOST", None)
                if not dest_ip:
                    print("[control] START ignored: no paired controller and no CONTROL_HOST fallback")
                    continue
                stop_flag.reset()
                ctl.set_state(STATE_STREAMING)
                try:
                    stream_with_wlan(
                        wlan, dest_ip, duration_sec=arg, stop_flag=stop_flag, ctl=ctl, trigger=trigger, display=display
                    )
                except Exception as e:
                    print("[control] stream error:", e)
                ctl.set_state(STATE_IDLE)
                gc.collect()
                print("[control] back to idle, free heap:", gc.mem_free())

            elif action == "STOP":
                # Nothing is actively streaming here (an in-progress stream
                # is interrupted directly inside stream_with_wlan's own poll)
                print("[control] STOP received while idle - nothing to stop")

    except KeyboardInterrupt:
        print("\n\nControl-plane stopped by user")

    finally:
        ctl.close()
        cleanup_wifi(wlan)


if __name__ == "__main__":
    main()
