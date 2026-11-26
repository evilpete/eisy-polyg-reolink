"""One IoX node per NVR channel.

The node type depends on what the camera can detect, so a motion-only camera
does not show Person/Vehicle/... values that can never change:

  reocam    motion only                      ST, GV5
  reocamai  + person, vehicle, animal        ST, GV0-GV2, GV5
  reocampk  + package                        ST, GV0-GV3, GV5
  reodbell  doorbell: + package, visitor     ST, GV0-GV5

Reolink reports detections as short pulses and motion can drop and return
within a second, so each driver goes ON immediately but only goes OFF after it
has stayed clear for `hold` seconds (the controller's hold_time parameter).
"""
import udi_interface

LOGGER = udi_interface.LOGGER

# driver -> reolink_aio AI object type
AI_DRIVERS = {
    'GV0': 'people',
    'GV1': 'vehicle',
    'GV2': 'dog_cat',
    'GV3': 'package',
}
LABELS = {'ST': 'motion', 'GV0': 'person', 'GV1': 'vehicle', 'GV2': 'animal',
          'GV3': 'package', 'GV4': 'visitor', 'GV5': 'online'}


def channel_address(channel):
    return f'cam{channel}'


def _drv(name):
    return {'driver': name, 'value': 0, 'uom': 2}


class Camera(udi_interface.Node):
    """Motion-only camera (base class for the other camera types)."""
    id = 'reocam'
    drivers = [_drv('ST'), _drv('GV5')]
    ai_drivers = ()          # subset of AI_DRIVERS this type shows
    has_visitor = False

    def __init__(self, poly, primary, address, name, channel):
        super().__init__(poly, primary, address, name)
        self.channel = channel
        self.host = None
        self._state = {}     # driver -> last value we set (absent = unknown)
        self._off_at = {}    # driver -> monotonic time to turn OFF

    # ------------------------------------------------------------ state

    def _set(self, drv, val):
        self._state[drv] = val
        if self.setDriver(drv, val) and drv != 'GV5':
            LOGGER.info(f'{self.name}: {LABELS[drv]} {"ON" if val else "OFF"}')
            if drv == 'ST':
                # DON/DOF let IoX programs use "If Control ... is switched On"
                self.reportCmd('DON' if val else 'DOF')

    def _apply(self, drv, raw, now, hold):
        if raw:
            self._off_at.pop(drv, None)
            if self._state.get(drv) != 1:
                self._set(drv, 1)
        elif self._state.get(drv) == 1 and hold > 0:
            self._off_at.setdefault(drv, now + hold)
        elif self._state.get(drv) != 0:
            self._set(drv, 0)

    def update(self, host, now, hold):
        """Copy the state held by reolink_aio onto the node.

        Called from the asyncio thread on every push and fallback poll.
        """
        self.host = host
        ch = self.channel
        self._apply('ST', host.motion_detected(ch), now, hold)
        for drv in self.ai_drivers:
            self._apply(drv, host.ai_detected(ch, AI_DRIVERS[drv]), now, hold)
        if self.has_visitor:
            self._apply('GV4', host.visitor_detected(ch), now, hold)
        self._set('GV5', int(bool(host.camera_online(ch))))
        self.tick(now)

    def tick(self, now):
        """Turn OFF drivers whose hold time has run out (called every second)."""
        for drv, when in list(self._off_at.items()):
            if now >= when:
                del self._off_at[drv]
                self._set(drv, 0)

    def query(self, command=None):
        self.reportDrivers()

    commands = {'QUERY': query}


class CameraAI(Camera):
    id = 'reocamai'
    drivers = [_drv('ST'), _drv('GV0'), _drv('GV1'), _drv('GV2'), _drv('GV5')]
    ai_drivers = ('GV0', 'GV1', 'GV2')


class CameraPackage(Camera):
    id = 'reocampk'
    drivers = [_drv('ST'), _drv('GV0'), _drv('GV1'), _drv('GV2'), _drv('GV3'),
               _drv('GV5')]
    ai_drivers = ('GV0', 'GV1', 'GV2', 'GV3')


class Doorbell(Camera):
    id = 'reodbell'
    drivers = [_drv('ST'), _drv('GV0'), _drv('GV1'), _drv('GV2'), _drv('GV3'),
               _drv('GV4'), _drv('GV5')]
    ai_drivers = ('GV0', 'GV1', 'GV2', 'GV3')
    has_visitor = True


def camera_class(host, channel):
    """Pick the node type that matches what this channel can detect."""
    if host.is_doorbell(channel):
        return Doorbell
    types = set(host.ai_supported_types(channel))
    if 'package' in types:
        return CameraPackage
    if types & {'people', 'vehicle', 'dog_cat'}:
        return CameraAI
    return Camera
