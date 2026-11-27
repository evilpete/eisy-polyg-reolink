# Reolink NVR configuration

Set these custom parameters, then save:

## NVRs and cameras

Add one parameter per NVR or stand-alone camera. The **key** starts with
`nvr` or `cam` (any case, the two mean the same), e.g. `nvr`, `nvr2`,
`cam_garage`. The **value** holds all its settings on one line, separated by
`;`:

<table>
  <thead>
    <tr><th>Key</th><th>Value</th></tr>
  </thead>
  <tbody>
    <tr><td><code>nvr</code></td><td><code>host=192.168.1.50;user=guest;pass=secret;exclude=1,4</code></td></tr>
    <tr><td><code>cam_garage</code></td><td><code>h=10.1.32.37;u=guest;p=secret;https=t</code></td></tr>
  </tbody>
</table>

<table>
  <thead>
    <tr>
      <th>Setting</th>
      <th>Also</th>
      <th>Required</th>
      <th>Notes</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>host</code></td>
      <td><code>h</code>, <code>hostname</code>, <code>ip</code></td>
      <td>yes</td>
      <td>NVR / camera IP address or hostname</td>
    </tr>
    <tr>
      <td><code>user</code></td>
      <td><code>u</code>, <code>username</code></td>
      <td>yes*</td>
      <td>A Reolink user (a dedicated non-admin user is fine)</td>
    </tr>
    <tr>
      <td><code>password</code></td>
      <td><code>p</code>, <code>pass</code>, <code>pw</code></td>
      <td>yes*</td>
      <td></td>
    </tr>
    <tr>
      <td><code>port</code></td>
      <td><code>po</code></td>
      <td>no</td>
      <td>HTTP(S) port, only if not the default</td>
    </tr>
    <tr>
      <td><code>https</code></td>
      <td><code>use_https</code>, <code>ssl</code></td>
      <td>no</td>
      <td><code>t</code> / <code>f</code>; blank = auto-detect</td>
    </tr>
    <tr>
      <td><code>use</code></td>
      <td><code>include</code></td>
      <td>no</td>
      <td>Only these cameras, e.g. <code>2,7</code></td>
    </tr>
    <tr>
      <td><code>exclude</code></td>
      <td><code>e</code>, <code>ignore</code></td>
      <td>no</td>
      <td>Ignore these cameras, e.g. <code>1,4,5</code></td>
    </tr>
  </tbody>
</table>

- Setting names are not case sensitive and can be shortened to any prefix
  (`h`, `ho`, `host`). If a prefix fits more than one, the order above wins,
  so `u` = user and `p` = password.
- \* `user` / `password` can be left out if the plain `username` / `password`
  parameters are set; those are then used for every device.
- Use `\;` for a `;` inside a value (e.g. a password).
- Camera nodes of the device keyed `nvr` are `cam0`, `cam1` ...; other
  devices use `<key>_<n>`, e.g. `cam_garage_0`. Keys are cut to 10
  characters for this, so they must differ in their first 10.

## Single NVR (original keys)

These still work and describe the device `nvr`:

<table>
  <thead>
    <tr>
      <th>Key</th>
      <th>Required</th>
      <th>Example</th>
      <th>Notes</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>host</code></td>
      <td>yes</td>
      <td><code>192.168.1.50</code></td>
      <td>NVR IP address or hostname</td>
    </tr>
    <tr>
      <td><code>username</code></td>
      <td>yes</td>
      <td><code>admin</code></td>
      <td>An NVR user (a dedicated non-admin user is fine)</td>
    </tr>
    <tr>
      <td><code>password</code></td>
      <td>yes</td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td><code>port</code></td>
      <td>no</td>
      <td><code>443</code></td>
      <td>NVR HTTP(S) port, only if not the default</td>
    </tr>
    <tr>
      <td><code>use_https</code></td>
      <td>no</td>
      <td><code>true</code></td>
      <td>Leave blank to auto-detect</td>
    </tr>
    <tr>
      <td><code>hold_time</code></td>
      <td>no</td>
      <td><code>5</code></td>
      <td>Seconds a motion / AI detection stays ON after the NVR clears it (default 5, <code>0</code> = off). Stops rapid On/Off flapping</td>
    </tr>
    <tr>
      <td><code>use</code></td>
      <td>no</td>
      <td><code>2,7</code></td>
      <td>Only these cameras (all others ignored). Alias: <code>include</code></td>
    </tr>
    <tr>
      <td><code>exclude</code></td>
      <td>no</td>
      <td><code>1,4,5</code></td>
      <td>Ignore these cameras (use all others). Alias: <code>ignore</code></td>
    </tr>
  </tbody>
</table>

The node server connects **out** to the NVR on TCP port 9000 (Baichuan) for
push events, and to the HTTP(S) port for setup. Nothing needs to be opened on
the eisy.

Camera nodes are created automatically, one per NVR channel. The node type
matches the camera: motion-only cameras show Motion and Online; AI cameras
add Person / Vehicle / Animal (and Package if supported); doorbells add Visitor. Use the Reolink
node's **Re-discover Cameras** command after adding a camera to an NVR.

Camera numbers in `use` / `exclude` start at **1**, as the NVR app shows them
(camera 1 = node `cam0`; a stand-alone camera is camera 1). The node server log lists each camera's number and
name at startup. If both are set, `exclude` is applied after `use`. Nodes for
ignored cameras are removed from IoX.
