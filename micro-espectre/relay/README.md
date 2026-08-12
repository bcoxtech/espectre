# Relay Tools

Host-side companion for the control-plane firmware (`boot_main.py` + `src/control.py`,
deployed via `me deploy --control-plane`). Runs on the relay host on the same
network segment as the boards (e.g. a Raspberry Pi acting as a dumb UDP relay) —
not on the boards themselves.

## espectre_ctl.py

Broadcasts `KNOCK` and listens for `HELLO <mac> <chip> <state>` replies to build
a registry of powered-on boards, and sends `START <duration_sec>` / `STOP`
commands back to a specific board by node ID, MAC, or IP. See the protocol
docstring in `../src/control.py` for the wire format.

Each board is assigned a short, stable node ID (`node1`, `node2`, ...) the
first time it's discovered, persisted to `.nodes.json` alongside this file
(gitignored — deployment-specific) so you don't have to type out MAC addresses.

```
python3 espectre_ctl.py                          # interactive if stdin is a TTY,
                                                   # daemon-only discovery log otherwise
python3 espectre_ctl.py --knock [timeout_sec]     # one-shot: discover, print, exit
python3 espectre_ctl.py --list                    # one-shot: print the cache, no network activity
python3 espectre_ctl.py --send <node_id|mac|ip> START [duration_sec]
python3 espectre_ctl.py --send <node_id|mac|ip> STOP
```

Pure stdlib, no dependencies. Run the daemon mode in the background for a live
discovery log (`nohup python3 -u espectre_ctl.py > ctl.log 2>&1 &`), or use
the one-shot flags above for scripting — `--send`/`--knock` do their own short
knock-and-discover first, so they work even without the daemon running.

This is also what `me knock` / `me list` / `me start` / `me stop` call into
when run from a host with the full `me` CLI installed — see `../me --help`.
Only a host that's network-adjacent to the boards' segment can actually reach
them either way (e.g. the Pi relay's LAN-facing interface), regardless of
which entry point you use.

**Note on `--send`:** the discovery step skips knocking entirely if the target
is already known and fresh (<20s since last heartbeat), and otherwise throttles
retries to one knock per 1.5s. Don't lower that interval — an earlier version
re-knocked every ~0.3s, and calling `--send` back-to-back for multiple boards
flooded each board's small UDP recv queue with redundant broadcast knocks
meant for its neighbors, silently dropping the real START/STOP command.
