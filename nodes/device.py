"""One Reolink NVR or stand-alone camera: connection, push subscription, nodes."""
import asyncio
import time

import udi_interface
from reolink_aio.api import Host
from reolink_aio.exceptions import CredentialsInvalidError

from .camera import camera_class, channel_address

LOGGER = udi_interface.LOGGER

CHECK_INTERVAL = 60      # seconds between subscription health checks
RETRY_MIN = 10           # reconnect backoff (seconds)
RETRY_MAX = 300
REQUEST_TIMEOUT = 30    # per HTTP request (reolink_aio default; Wi-Fi cameras can be slow)
CONNECT_TIMEOUT = 90    # whole login + capability read (~20 s seen on an RLC-511)


class Device:
    def __init__(self, ctl, cfg):
        self.ctl = ctl               # Controller (poly, hold, status, camera registry)
        self.cfg = cfg
        self.poly = ctl.poly
        self.host = None
        self.cameras = {}            # address -> Camera node
        self.connected = False
        self.push_active = False

    @property
    def label(self):
        return f'{self.cfg.key} ({self.cfg.host})'

    def _status(self, connected=None, push=None):
        if connected is not None:
            self.connected = connected
        if push is not None:
            self.push_active = push
        self.ctl.refresh_status()

    # ------------------------------------------------------------ connection

    async def run(self, stop_evt):
        backoff = RETRY_MIN

        async def sleep_or_stop(seconds):
            try:
                await asyncio.wait_for(stop_evt.wait(), timeout=seconds)
                return True
            except asyncio.TimeoutError:
                return False

        while not stop_evt.is_set():
            host = None
            notice = f'dev_{self.cfg.id}'
            try:
                cfg = self.cfg
                # Host must be created inside the running loop
                host = Host(cfg.host, cfg.user, cfg.pw, port=cfg.port, use_https=cfg.https,
                            timeout=REQUEST_TIMEOUT)
                await asyncio.wait_for(host.get_host_data(), CONNECT_TIMEOUT)
                self.host = host
                self.ctl.clear_notice(notice)
                LOGGER.info(f'{self.label}: connected to {host.nvr_name} ({host.model}), '
                            f'NVR={host.is_nvr}, channels={host.channels}')
                self._status(connected=True)
                self.sync_nodes()

                host.baichuan.register_callback(f'udi_{cfg.id}', self._on_push)
                await host.baichuan.subscribe_events()
                LOGGER.info(f'{self.label}: subscribed to push events')

                await self.poll_states()   # initial state
                backoff = RETRY_MIN

                while not await sleep_or_stop(CHECK_INTERVAL):
                    await host.baichuan.check_subscribe_events()
                    active = host.baichuan.events_active
                    self._status(push=active)
                    if not active:
                        # no push seen yet (or connection lost): keep state fresh
                        await self.poll_states()

            except CredentialsInvalidError:
                LOGGER.error(f'{self.label}: username/password rejected')
                self.ctl.set_notice(notice, f'{self.cfg.key}: Reolink rejected the username/password')
                backoff = RETRY_MAX
            except Exception as err:
                why = 'no answer' if isinstance(err, asyncio.TimeoutError) else type(err).__name__
                LOGGER.error(f'{self.label}: connection error: {err!r}')
                self.ctl.set_notice(notice, f'{self.cfg.key}: cannot connect to {self.cfg.host} '
                                            f'({why}), retrying')
            finally:
                self._status(connected=False, push=False)
                if host is not None:
                    try:
                        host.baichuan.unregister_callback(f'udi_{self.cfg.id}')
                        await host.baichuan.unsubscribe_events()
                        await host.logout()
                    except Exception as err:
                        LOGGER.debug(f'{self.label}: cleanup: {err!r}')
                self.host = None

            if await sleep_or_stop(backoff):
                break
            LOGGER.info(f'{self.label}: reconnecting (waited {backoff}s)')
            backoff = min(backoff * 2, RETRY_MAX)

    async def rediscover(self):
        if self.host is None:
            LOGGER.warning(f'{self.label}: discover: not connected')
            return
        await self.host.get_host_data()
        self.sync_nodes()
        await self.poll_states()

    async def poll_states(self):
        try:
            host = self.host
            await host.get_motion_state_all_ch()
            if any(host.ai_supported(ch) for ch in host.channels):
                await host.get_ai_state_all_ch()
        except Exception as err:
            LOGGER.warning(f'{self.label}: state poll failed: {err!r}')
        self.update_all()

    def _on_push(self):
        # runs in the asyncio thread; reolink_aio has already updated its state
        if not self.push_active:
            self._status(push=True)
        self.update_all()

    def update_all(self):
        host = self.host
        if host is None:
            return
        now = time.monotonic()
        for cam in list(self.cameras.values()):
            try:
                cam.update(host, now, self.ctl.hold)
            except Exception as err:
                LOGGER.error(f'{cam.name}: update failed: {err!r}')

    def tick(self, now):
        for cam in list(self.cameras.values()):
            cam.tick(now)

    # ----------------------------------------------------------------- nodes

    def sync_nodes(self):
        host, cfg = self.host, self.cfg
        channels = host.channels if host.is_nvr else [0]
        for ch in channels:
            LOGGER.info(f'{cfg.key}: camera {ch + 1} {host.camera_name(ch)!r} -> '
                        f'{channel_address(cfg.id, ch)}: '
                        f'{"used" if cfg.selected(ch) else "ignored (use/exclude)"}')
        unknown = sorted(c + 1 for c in (cfg.use or set()) | cfg.exclude if c not in channels)
        if unknown:
            self.ctl.set_notice(f'cams_{cfg.id}',
                                f'{cfg.key}: use/exclude: no camera {", ".join(map(str, unknown))} '
                                f'(cameras are 1-{len(channels)})')

        # remove nodes for cameras that are now ignored, including ones left in
        # the PG3 database from an earlier run (cameras the device no longer
        # lists are kept, they may just be offline)
        ignored = {channel_address(cfg.id, ch) for ch in channels if not cfg.selected(ch)}
        known = set(self.cameras)
        try:
            known |= {n['address'] for n in self.poly.getNodesFromDb() or []}
        except Exception as err:
            LOGGER.debug(f'getNodesFromDb: {err!r}')
        for addr in sorted(known & ignored):
            LOGGER.info(f'Removing node {addr} (camera ignored by use/exclude)')
            self.cameras.pop(addr, None)
            self.poly.delNode(addr)

        for ch in channels:
            addr = channel_address(cfg.id, ch)
            if addr in self.cameras or not cfg.selected(ch):
                continue
            name = host.camera_name(ch) or (host.nvr_name if not host.is_nvr else None) \
                or f'Camera {ch + 1}'
            # PG3 keeps an existing (possibly user-renamed) node's name
            name = self.poly.getValidName(name)
            cls = camera_class(host, ch)
            LOGGER.info(f'{cfg.key}: ch{ch} {name}: {host.camera_model(ch)} -> {cls.id} '
                        f'(ai={host.ai_supported_types(ch)})')
            cam = cls(self.poly, self.ctl.address, addr, name, ch)
            self.poly.addNode(cam)
            self.cameras[addr] = cam

        for ch in channels:
            if cfg.selected(ch):
                try:
                    uid = host.camera_uid(ch)
                except Exception:
                    uid = None
                self.ctl.register_camera(uid, self, ch, host.camera_name(ch))
        self.ctl.refresh_status()
