# Reolink NVR configuration

Set these custom parameters, then save:

| Key | Required | Example | Notes |
|---|---|---|---|
| `host` | yes | `192.168.1.50` | NVR IP address or hostname |
| `username` | yes | `admin` | An NVR user (a dedicated non-admin user is fine) |
| `password` | yes | | |
| `port` | no | `443` | NVR HTTP(S) port, only if not the default |
| `use_https` | no | `true` | Leave blank to auto-detect |
| `hold_time` | no | `5` | Seconds a motion / AI detection stays ON after the NVR clears it (default 5, `0` = off). Stops rapid On/Off flapping |

The node server connects **out** to the NVR on TCP port 9000 (Baichuan) for
push events, and to the HTTP(S) port for setup. Nothing needs to be opened on
the eisy.

Camera nodes are created automatically, one per NVR channel. The node type
matches the camera: motion-only cameras show Motion and Online; AI cameras
add Person / Vehicle / Animal (and Package if supported); doorbells add Visitor. Use the NVR
node's **Re-discover Cameras** command after adding a camera to the NVR.
