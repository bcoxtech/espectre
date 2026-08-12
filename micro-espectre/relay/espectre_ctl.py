#!/usr/bin/env python3
"""
espectre_ctl - minimal control-plane listener/CLI for Micro-ESPectre boards.

Periodically broadcasts "KNOCK" on the isolated segment. Any board running
boot_main.py (control-plane firmware) that hears it replies with
"HELLO <mac> <chip> <state>" and starts trusting/heartbeating to us. Builds
a live registry from those replies, and lets you send "START <duration>" /
"STOP" commands back to a board by mac or ip.

Modes:
    python3 espectre_ctl.py
        Interactive if stdin is a TTY (list | start <mac|ip> [dur] | stop <mac|ip> | quit).
        Daemon-only (discovery log, no stdin) if stdin is NOT a TTY - e.g. under
        `nohup ... &`. Selecting on a non-TTY stdin busy-loops (EOF makes it
        always show as ready), so it's deliberately excluded rather than watched.

    python3 espectre_ctl.py --send <mac|ip> START [duration]
    python3 espectre_ctl.py --send <mac|ip> STOP
        One-shot: broadcast a few KNOCKs to (re)discover, send the command,
        exit. Good for scripting/testing without a long-running daemon.
"""
import socket
import select
import sys
import time

PORT = 5002
BROADCAST_ADDR = "192.168.0.255"  # isolated segment, /24
KNOCK_INTERVAL_SEC = 5
STALE_AFTER_SEC = 20  # drop a node from "live" listing if no heartbeat in this long

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
sock.bind(("0.0.0.0", PORT))

# mac -> {"ip": str, "chip": str, "state": str, "last_seen": float}
registry = {}


def send_knock():
    try:
        sock.sendto(b"KNOCK", (BROADCAST_ADDR, PORT))
    except OSError as e:
        print(f"\n[knock] send failed: {e}")


def handle_heartbeat(data, addr, verbose=True):
    try:
        text = data.decode().strip()
    except Exception:
        return
    parts = text.split()
    if len(parts) != 4 or parts[0] != "HELLO":
        return
    _, mac, chip, state = parts
    prev = registry.get(mac)
    registry[mac] = {"ip": addr[0], "chip": chip, "state": state, "last_seen": time.time()}
    if not verbose:
        return
    if prev is None:
        print(f"\n[discovered] {mac} ({chip}) at {addr[0]}")
    elif prev["state"] != state:
        print(f"\n[state] {mac} {prev['state']} -> {state}")


def resolve(identifier):
    """Look up a registry entry by mac or ip, return (mac, entry) or (None, None)."""
    if identifier in registry:
        return identifier, registry[identifier]
    for mac, entry in registry.items():
        if entry["ip"] == identifier:
            return mac, entry
    return None, None


def send_command(identifier, cmd):
    mac, entry = resolve(identifier)
    if entry is None:
        print(f"unknown node: {identifier} (try 'list')")
        return False
    sock.sendto(cmd.encode(), (entry["ip"], PORT))
    print(f"sent '{cmd}' -> {mac} ({entry['ip']})")
    return True


def print_list():
    if not registry:
        print("no nodes discovered yet")
        return
    now = time.time()
    for mac, entry in registry.items():
        age = now - entry["last_seen"]
        live = "live" if age < STALE_AFTER_SEC else f"stale ({age:.0f}s ago)"
        print(f"  {mac}  {entry['ip']:15s}  {entry['chip']:5s}  {entry['state']:10s}  {live}")


def print_prompt():
    sys.stdout.write("\n> ")
    sys.stdout.flush()


def run_one_shot(identifier, cmd_parts):
    """
    Knock at most a few times (not on a tight loop - a knock storm from
    running this back-to-back for multiple boards can overflow a board's
    small UDP recv queue and drop the real command right after) to (re)discover
    the target, send one command, exit.
    """
    cmd = " ".join(cmd_parts)
    mac, entry = resolve(identifier)
    if entry is None or time.time() - entry["last_seen"] > STALE_AFTER_SEC:
        print(f"knocking to discover {identifier}...")
        deadline = time.time() + 5
        sock.settimeout(0.5)
        next_knock = 0.0
        while time.time() < deadline:
            now = time.time()
            if now >= next_knock:
                send_knock()
                next_knock = now + 1.5
            try:
                data, addr = sock.recvfrom(256)
                handle_heartbeat(data, addr, verbose=False)
            except socket.timeout:
                continue
            mac, entry = resolve(identifier)
            if entry is not None:
                break
    else:
        print(f"{identifier} already known (fresh), skipping knock")
    # give the target's socket queue a moment to drain any straggling
    # knock replies in flight before we send the real command
    time.sleep(0.3)
    if not send_command(identifier, cmd):
        sys.exit(1)


def run_daemon(interactive):
    print(f"Broadcasting KNOCK every {KNOCK_INTERVAL_SEC}s on {BROADCAST_ADDR}:{PORT}")
    if interactive:
        print("Commands: list | start <mac|ip> [duration] | stop <mac|ip> | quit")
        print_prompt()
    else:
        print("(non-interactive stdin - daemon mode, discovery log only; use --send to issue commands)")

    watch = [sock, sys.stdin] if interactive else [sock]
    last_knock = 0.0
    while True:
        readable, _, _ = select.select(watch, [], [], 1.0)

        now = time.time()
        if now - last_knock >= KNOCK_INTERVAL_SEC:
            send_knock()
            last_knock = now

        for r in readable:
            if r is sock:
                data, addr = sock.recvfrom(256)
                handle_heartbeat(data, addr)
                if interactive:
                    print_prompt()
            else:
                line = sys.stdin.readline().strip()
                if not line:
                    print_prompt()
                    continue
                parts = line.split()
                op = parts[0].lower()
                if op == "quit" or op == "exit":
                    return
                elif op == "list":
                    print_list()
                elif op == "start" and len(parts) >= 2:
                    duration = parts[2] if len(parts) > 2 else "0"
                    send_command(parts[1], f"START {duration}")
                elif op == "stop" and len(parts) >= 2:
                    send_command(parts[1], "STOP")
                else:
                    print("usage: list | start <mac|ip> [duration] | stop <mac|ip> | quit")
                print_prompt()


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--send":
            if len(sys.argv) < 4:
                print("usage: espectre_ctl.py --send <mac|ip> START [duration] | STOP")
                sys.exit(1)
            run_one_shot(sys.argv[2], sys.argv[3:])
        else:
            run_daemon(interactive=sys.stdin.isatty())
    except KeyboardInterrupt:
        print("\nbye")
