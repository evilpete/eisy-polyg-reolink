"""Controller node: owns the NVR connection and the Baichuan event subscription."""
import asyncio
import logging
import threading
import time

import udi_interface
from reolink_aio.api import Host
from reolink_aio.exceptions import CredentialsInvalidError

from .camera import camera_class, channel_address

LOGGER = udi_interface.LOGGER
Custom = udi_interface.Custom

# reolink_aio is chatty at DEBUG; keep it at INFO unless debugging the lib
logging.getLogger('reolink_aio').setLevel(logging.INFO)

CHECK_INTERVAL = 60      # seconds between subscription health checks
RETRY_MIN = 10           # reconnect backoff (seconds)
RETRY_MAX = 300
HOLD_DEFAULT = 5       # seconds a detection stays ON after it clears


class Controller(udi_interface.Node):
    id = 'reonvr'
    drivers = [
        {'driver': 'ST',  'value': 1, 'uom': 2},   # node server online (PG3)
        {'driver': 'GV0', 'value': 0, 'uom': 2},   # logged in to NVR
        {'driver': 'GV1', 'value': 0, 'uom': 2},   # push events confirmed
        {'driver': 'GV2', 'value': 0, 'uom': 56},  # cameras
    ]

    def __init__(self, poly, primary, address, name):
        super().__init__(poly, primary, address, name)
        self.poly = poly
        self.params = Custom(poly, 'customparams')
        self.cameras = {}
        self.host = None
        self._cfg = None
        self._lock = threading.Lock()
        self._loop = None
        self._thread = None
        self._stop_evt = None
        self._started = False
        self.hold = HOLD_DEFAULT

        poly.subscribe(poly.START, self.start, address)
        poly.subscribe(poly.STOP, self.stop)
        poly.subscribe(poly.CUSTOMPARAMS, self.parameter_handler)

        poly.ready()
        poly.addNode(self, conn_status='ST')

    # ------------------------------------------------------------------ PG3

    def start(self):
        LOGGER.info('Reolink NVR node server starting')
        self.poly.updateProfile()
        self.poly.setCustomParamsDoc()
        self._started = True
        self._apply_config()

    def stop(self):
        LOGGER.info('Reolink NVR node server stopping')
        self._stop_worker()
        self.setDriver('GV0', 0)
        self.setDriver('GV1', 0)

    def parameter_handler(self, params):
        self.params.load(params)
        self._apply_config()

    def _read_config(self):
        self.poly.Notices.clear()
        host = (self.params.get('host') or '').strip()
        user = (self.params.get('username') or '').strip()
        pw = self.params.get('password') or ''
        missing = [k for k, v in (('host', host), ('username', user), ('password', pw)) if not v]
        if missing:
            self.poly.Notices['cfg'] = f'Please set: {", ".join(missing)}'
            return None
        port = (self.params.get('port') or '').strip()
        https = (self.params.get('use_https') or '').strip().lower()
        hold = (self.params.get('hold_time') or '').strip()
        try:
            self.hold = max(0.0, float(hold)) if hold else HOLD_DEFAULT
        except ValueError:
            self.poly.Notices['hold'] = f'hold_time must be a number of seconds, using {HOLD_DEFAULT}'
            self.hold = HOLD_DEFAULT
        return {
            'host': host,
            'user': user,
            'pw': pw,
            'port': int(port) if port.isdigit() else None,
            'https': True if https in ('1', 'true', 'yes') else (False if https in ('0', 'false', 'no') else None),
        }

    def _apply_config(self):
        if not self._started:
            return
        cfg = self._read_config()
        with self._lock:
            if cfg == self._cfg and self._thread and self._thread.is_alive():
                return
            self._stop_worker()
            self._cfg = cfg
            if cfg is None:
                return
            self._thread = threading.Thread(target=self._run, args=(cfg,),
                                            name='reolink-push', daemon=True)
            self._thread.start()

    # --------------------------------------------------------- asyncio side

    def _stop_worker(self):
        if self._loop and self._stop_evt and self._thread and self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._stop_evt.set)
            self._thread.join(timeout=15)
        self._thread = None

    def _run(self, cfg):
        try:
            asyncio.run(self._main(cfg))
        except Exception:
            LOGGER.exception('Reolink worker crashed')

    async def _sleep_or_stop(self, seconds):
        """Sleep; return True if a stop was requested."""
        try:
            await asyncio.wait_for(self._stop_evt.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    async def _main(self, cfg):
        self._loop = asyncio.get_running_loop()
        self._stop_evt = asyncio.Event()
        backoff = RETRY_MIN

        while not self._stop_evt.is_set():
            host = None
            ticker = None
            try:
                # Host must be created inside the running loop
                host = Host(cfg['host'], cfg['user'], cfg['pw'],
                            port=cfg['port'], use_https=cfg['https'])
                await host.get_host_data()
                self.host = host
                self.setDriver('GV0', 1)
                LOGGER.info(f'Connected to {host.nvr_name} ({host.model}), '
                            f'NVR={host.is_nvr}, channels={host.channels}')
                self._sync_nodes(host)

                host.baichuan.register_callback('udi', lambda: self._on_push(host))
                await host.baichuan.subscribe_events()
                LOGGER.info('Subscribed to Baichuan push events')

                await self._poll_states(host)   # initial state
                ticker = asyncio.create_task(self._tick_loop())
                backoff = RETRY_MIN

                while not await self._sleep_or_stop(CHECK_INTERVAL):
                    await host.baichuan.check_subscribe_events()
                    active = host.baichuan.events_active
                    self.setDriver('GV1', int(active))
                    if not active:
                        # no push seen yet (or connection lost): keep state fresh
                        await self._poll_states(host)

            except CredentialsInvalidError:
                LOGGER.error('NVR rejected username/password')
                self.poly.Notices['auth'] = 'Reolink NVR rejected the username/password'
                backoff = RETRY_MAX
            except Exception as err:
                LOGGER.error(f'NVR connection error: {err!r}')
            finally:
                if ticker is not None:
                    ticker.cancel()
                self.setDriver('GV0', 0)
                self.setDriver('GV1', 0)
                if host is not None:
                    try:
                        host.baichuan.unregister_callback('udi')
                        await host.baichuan.unsubscribe_events()
                        await host.logout()
                    except Exception as err:
                        LOGGER.debug(f'cleanup: {err!r}')
                self.host = None

            if await self._sleep_or_stop(backoff):
                break
            LOGGER.info(f'Reconnecting to NVR (waited {backoff}s)')
            backoff = min(backoff * 2, RETRY_MAX)

    async def _tick_loop(self):
        # expire hold timers once a second
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            for cam in list(self.cameras.values()):
                cam.tick(now)

    async def _poll_states(self, host):
        try:
            await host.get_motion_state_all_ch()
            await host.get_ai_state_all_ch()
        except Exception as err:
            LOGGER.warning(f'State poll failed: {err!r}')
        self._update_all(host)

    def _on_push(self, host):
        # runs in the asyncio thread; reolink_aio has already updated its state
        self.setDriver('GV1', 1)
        self._update_all(host)

    def _update_all(self, host):
        now = time.monotonic()
        for cam in list(self.cameras.values()):
            try:
                cam.update(host, now, self.hold)
            except Exception as err:
                LOGGER.error(f'{cam.name}: update failed: {err!r}')

    def _sync_nodes(self, host):
        channels = host.channels if host.is_nvr else [0]
        for ch in channels:
            addr = channel_address(ch)
            if addr in self.cameras:
                continue
            name = host.camera_name(ch) or f'Camera {ch + 1}'
            # PG3 keeps an existing (possibly user-renamed) node's name
            name = self.poly.getValidName(name)
            cls = camera_class(host, ch)
            LOGGER.info(f'ch{ch} {name}: {host.camera_model(ch)} -> {cls.id} '
                        f'(ai={host.ai_supported_types(ch)})')
            cam = cls(self.poly, self.address, addr, name, ch)
            self.poly.addNode(cam)
            self.cameras[addr] = cam
        self.setDriver('GV2', len(self.cameras))

    # -------------------------------------------------------------- commands

    def query(self, command=None):
        self.reportDrivers()
        for cam in self.cameras.values():
            cam.reportDrivers()

    def discover(self, command=None):
        host, loop = self.host, self._loop
        if host is None or loop is None:
            LOGGER.warning('Discover: not connected to NVR')
            return

        async def _rediscover():
            await host.get_host_data()
            self._sync_nodes(host)
            await self._poll_states(host)

        asyncio.run_coroutine_threadsafe(_rediscover(), loop)

    commands = {'QUERY': query, 'DISCOVER': discover}
