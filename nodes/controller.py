"""Controller node: reads the config and runs one Device per NVR / camera.

All devices share one asyncio loop in a background thread (udi_interface is
threaded, reolink_aio is asyncio). Each device connects, subscribes to push
events and reconnects on its own, so one being offline does not affect the
others.
"""
import asyncio
import logging
import threading
import time

import udi_interface

from .config import parse_params
from .device import Device

LOGGER = udi_interface.LOGGER
Custom = udi_interface.Custom

# reolink_aio is chatty at DEBUG; keep it at INFO unless debugging the lib
logging.getLogger('reolink_aio').setLevel(logging.INFO)

HOLD_DEFAULT = 5       # seconds a detection stays ON after it clears


class Controller(udi_interface.Node):
    id = 'reonvr'
    hint = [0x01, 0x0e, 0x01, 0x00]   # Gateway (UniversalDevicesInc/hints hint.yaml)
    drivers = [
        {'driver': 'ST',  'value': 1, 'uom': 2},   # node server online (PG3)
        {'driver': 'GV0', 'value': 0, 'uom': 56},  # devices connected
        {'driver': 'GV1', 'value': 0, 'uom': 56},  # devices with push events confirmed
        {'driver': 'GV2', 'value': 0, 'uom': 56},  # cameras
        {'driver': 'GV3', 'value': 0, 'uom': 56},  # devices configured
    ]

    def __init__(self, poly, primary, address, name):
        super().__init__(poly, primary, address, name)
        self.poly = poly
        self.params = Custom(poly, 'customparams')
        self.devices = []
        self.hold = HOLD_DEFAULT
        self._cfgs = None
        self._uids = {}            # camera UID -> (device, channel, name)
        self._lock = threading.Lock()
        self._loop = None
        self._thread = None
        self._stop_evt = None
        self._started = False

        poly.subscribe(poly.START, self.start, address)
        poly.subscribe(poly.STOP, self.stop)
        poly.subscribe(poly.CUSTOMPARAMS, self.parameter_handler)

        poly.ready()
        poly.addNode(self, conn_status='ST')

    # ------------------------------------------------------------------ PG3

    def start(self):
        LOGGER.info('Reolink node server starting')
        self.poly.updateProfile()
        self.poly.setCustomParamsDoc()
        self._started = True
        self._apply_config()

    def stop(self):
        LOGGER.info('Reolink node server stopping')
        with self._lock:
            self._stop_worker()
        self.refresh_status()

    def parameter_handler(self, params):
        self.params.load(params)
        self._apply_config()

    # -------------------------------------------------------------- notices

    def set_notice(self, key, text):
        self.poly.Notices[key] = text

    def clear_notice(self, key):
        try:
            if key in self.poly.Notices:
                self.poly.Notices.delete(key)
        except Exception as err:
            LOGGER.debug(f'clear notice {key}: {err!r}')

    # --------------------------------------------------------------- config

    def _read_config(self):
        self.poly.Notices.clear()
        params = dict(self.params.items())
        hold = (params.get('hold_time') or '').strip()
        try:
            self.hold = max(0.0, float(hold)) if hold else HOLD_DEFAULT
        except ValueError:
            self.set_notice('hold', f'hold_time must be a number of seconds, using {HOLD_DEFAULT}')
            self.hold = HOLD_DEFAULT

        cfgs, problems = parse_params(params)
        for i, text in enumerate(problems):
            LOGGER.warning(f'config: {text}')
            self.set_notice(f'cfg{i}', text)
        for cfg in cfgs:
            LOGGER.info(f'config: {cfg!r}')
        return tuple(cfgs)

    def _apply_config(self):
        if not self._started:
            return
        cfgs = self._read_config()
        with self._lock:
            if cfgs == self._cfgs and self._thread and self._thread.is_alive():
                return
            self._stop_worker()
            self._cfgs = cfgs
            self.devices = [Device(self, c) for c in cfgs]
            self._uids = {}
            self.refresh_status()
            if not cfgs:
                return
            self._loop = asyncio.new_event_loop()
            self._stop_evt = asyncio.Event()
            self._thread = threading.Thread(target=self._run, name='reolink-push',
                                            daemon=True)
            self._thread.start()

    def register_camera(self, uid, dev, ch, name):
        """Warn when the same camera is reached through two devices (e.g. an
        NVR channel and the camera's own IP): it would show up twice."""
        if not uid or uid.lower() == 'unknown':
            return
        other = self._uids.setdefault(uid, (dev, ch, name))
        if other[0] is dev:
            return
        odev, och, oname = other
        text = (f'Camera {name!r} is both {dev.cfg.key} camera {ch + 1} and '
                f'{odev.cfg.key} camera {och + 1} ({oname!r}); it has two nodes. '
                f'Add exclude={ch + 1} to {dev.cfg.key} or exclude={och + 1} to '
                f'{odev.cfg.key} if that is not wanted.')
        LOGGER.warning(text)
        self.set_notice(f'dup_{uid}', text)

    def refresh_status(self):
        devs = self.devices
        self.setDriver('GV0', sum(d.connected for d in devs))
        self.setDriver('GV1', sum(d.push_active for d in devs))
        self.setDriver('GV2', sum(len(d.cameras) for d in devs))
        self.setDriver('GV3', len(devs))

    # --------------------------------------------------------- asyncio side

    def _stop_worker(self):
        """Caller holds self._lock."""
        if self._thread and self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._stop_evt.set)
            self._thread.join(timeout=15)
            if self._thread.is_alive():
                LOGGER.warning('Reolink worker did not stop within 15 s')
        self._thread = None

    def _run(self):
        loop = self._loop
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._main())
        except Exception:
            LOGGER.exception('Reolink worker crashed')
        finally:
            loop.close()

    async def _main(self):
        ticker = asyncio.create_task(self._tick_loop())
        tasks = [asyncio.create_task(d.run(self._stop_evt)) for d in self.devices]
        try:
            await self._stop_evt.wait()
            # connected devices notice the stop and log out by themselves; one
            # still trying to reach its host (30 s request timeout) is cancelled
            done, pending = await asyncio.wait(tasks, timeout=5)
            for t in pending:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            ticker.cancel()

    async def _tick_loop(self):
        # expire hold timers once a second
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            for dev in self.devices:
                dev.tick(now)

    # -------------------------------------------------------------- commands

    def query(self, command=None):
        self.reportDrivers()
        for dev in self.devices:
            for cam in dev.cameras.values():
                cam.reportDrivers()

    def discover(self, command=None):
        loop = self._loop
        if loop is None or not (self._thread and self._thread.is_alive()):
            LOGGER.warning('Discover: not running')
            return
        for dev in self.devices:
            asyncio.run_coroutine_threadsafe(dev.rediscover(), loop)

    commands = {'QUERY': query, 'DISCOVER': discover}
