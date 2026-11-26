# eisy-polyg-reolink

A Polyglot v3 (PG3x) node server for the eisy / Polisy that follows Reolink
**NVR** motion and AI-detection events in real time.

It uses [reolink_aio](https://github.com/starkillerOG/reolink_aio) to
subscribe to the NVR's Baichuan TCP push events (port 9000), the same
mechanism the Home Assistant Reolink integration uses. The connection is
outbound from the eisy, so no webhook or open port is needed, and it works
for cameras attached to an NVR (which do not support Reolink's camera
webhook).

## Nodes

**Reolink NVR** (`reonvr`)

| Driver | Meaning |
|---|---|
| ST | Node server online |
| GV0 | Logged in to NVR |
| GV1 | Push events confirmed (set after the first push arrives) |
| GV2 | Number of cameras |

Commands: Query, Re-discover Cameras

**Reolink Camera**, one per NVR channel. The node type matches what the
camera can detect, so values that can never change are not shown:

| Driver | Meaning | `reocam` | `reocamai` | `reocampk` | `reodbell` |
|---|---|---|---|---|---|
| ST | Motion | x | x | x | x |
| GV0 | Person | | x | x | x |
| GV1 | Vehicle | | x | x | x |
| GV2 | Animal | | x | x | x |
| GV3 | Package | | | x | x |
| GV4 | Visitor (doorbell button) | | | | x |
| GV5 | Camera online | x | x | x | x |

Sends `DON` / `DOF` when motion starts / stops, so programs can use
`If Control 'Front Door' is switched On`. All drivers can also be used as
status conditions (`If 'Front Door' Person is True`).

Reolink reports AI detections as short pulses (often ~1 s) and motion can
drop and return within a second. Each value therefore turns ON immediately
but only turns OFF after staying clear for `hold_time` seconds (default 5).

## Install

1. In PG3x, install from a local/development install pointing at this repo,
   or copy it to the eisy and install as a local node server.
2. Set the custom parameters `host`, `username`, `password` (see
   `POLYGLOT_CONFIG.md`).
3. Camera nodes are added automatically.

Requires Python >= 3.11 (a `reolink_aio` requirement).

## How it works

- `nodes/controller.py` runs an asyncio loop in a background thread, logs in
  with `Host.get_host_data()`, registers a callback with
  `host.baichuan.register_callback()` and calls
  `host.baichuan.subscribe_events()`.
- On every push, reolink_aio updates its state and the callback copies the
  state to each camera node. `setDriver` only reports changes to IoX, and
  OFF is delayed by `hold_time` (a 1 s timer expires the holds).
- Every 60 s the subscription is health-checked. If no push has been seen
  yet, motion/AI state is polled as a fallback. Lost connections are retried
  with backoff (10 s up to 5 min).

## References

- https://github.com/mnpg/Reolink_api_documentations
- https://github.com/ReolinkCameraAPI/reolinkapipy
- https://gist.github.com/jasonk/4772d1cd5154069cfc9eed07acb2057a

(generated with Claude)
