# Reolink NVR configuration

Set these custom parameters, then save:

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
  </tbody>
</table>

The node server connects **out** to the NVR on TCP port 9000 (Baichuan) for
push events, and to the HTTP(S) port for setup. Nothing needs to be opened on
the eisy.

Camera nodes are created automatically, one per NVR channel. The node type
matches the camera: motion-only cameras show Motion and Online; AI cameras
add Person / Vehicle / Animal (and Package if supported); doorbells add Visitor. Use the NVR
node's **Re-discover Cameras** command after adding a camera to the NVR.
