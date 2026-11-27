"""Parse the node server's custom parameters into a list of devices.

Each NVR or stand-alone camera is one custom parameter whose key starts with
"nvr" or "cam" (any case; the two are equivalent) and whose value is a
';'-separated list of name=value settings on one line:

    nvr         host=192.168.1.50;user=guest;pass=secret;exclude=1,4
    cam_garage  h=10.1.32.37;u=guest;p=secret;https=t

Setting names are not case sensitive and may be abbreviated to any prefix
(h, ho, hostname ...). When a prefix fits several settings the first one in
FIELDS wins, so u = user and p = password. Use \\; for a literal ';' in a
value. Values keep their case.

The original plain keys (host, username, password, port, use_https, use,
exclude) still work and describe the device "nvr". Plain username / password
are also the defaults for device lines that leave them out.

This module has no PG3 dependency so it can be tested on its own.
"""
import re
from dataclasses import dataclass
from typing import Optional

# canonical name, aliases; ORDER MATTERS for abbreviation priority
FIELDS = [
    ('host',     ('hostname', 'ip')),
    ('user',     ('username', 'login')),
    ('password', ('pass', 'pw', 'pwd')),
    ('port',     ()),
    ('https',    ('use_https', 'ssl')),
    ('use',      ('include',)),
    ('exclude',  ('ignore',)),
]
TRUE = {'1', 't', 'true', 'y', 'yes', 'on'}
FALSE = {'0', 'f', 'false', 'n', 'no', 'off'}
DEVICE_KEY = re.compile(r'^(nvr|cam)', re.I)
LEGACY_ID = 'nvr'
MAX_ID = 10        # IoX addresses are max 14 chars: <id>_<channel>


@dataclass(frozen=True)
class DeviceCfg:
    id: str                      # node address prefix, e.g. 'nvr', 'cam_garage'
    key: str                     # parameter key as written
    host: str
    user: str
    pw: str
    port: Optional[int] = None
    https: Optional[bool] = None
    use: Optional[frozenset] = None      # 0-based channels, None = all
    exclude: frozenset = frozenset()

    def selected(self, ch):
        if self.use is not None and ch not in self.use:
            return False
        return ch not in self.exclude

    def __repr__(self):          # never show the password
        return (f'DeviceCfg({self.id!r}, host={self.host!r}, user={self.user!r}, '
                f'port={self.port}, https={self.https}, use={self.use}, '
                f'exclude={set(self.exclude) or "{}"})')


def field_name(token):
    """Map a (possibly abbreviated, any-case) setting name to its canonical name."""
    t = token.strip().lower()
    if not t:
        return None
    for name, aliases in FIELDS:
        if t == name or t in aliases:
            return name
    for name, aliases in FIELDS:
        if any(n.startswith(t) for n in (name, *aliases)):
            return name
    return None


def parse_bool(val):
    v = val.strip().lower()
    if v in TRUE:
        return True
    if v in FALSE:
        return False
    if v == '':
        return None
    raise ValueError(f'"{val}" is not true/false')


def parse_cam_list(raw):
    """'1,4,5' (1-based, as the NVR app shows them) -> (frozenset of 0-based
    channels or None if nothing usable, [bad tokens])."""
    chans, bad = set(), []
    for tok in re.split(r'[,\s]+', raw.strip()):
        if not tok:
            continue
        if tok.isdigit() and int(tok) >= 1:
            chans.add(int(tok) - 1)
        else:
            bad.append(tok)
    # nothing usable: treat as unset rather than "no cameras"
    return (frozenset(chans) if chans else None), bad


def split_line(line):
    """Split 'a=1;b=2' into {'a': '1', 'b': '2'} (raw names), honouring \\;."""
    out = []
    for part in re.split(r'(?<!\\);', line):
        part = part.replace('\\;', ';').strip()
        if not part:
            continue
        if '=' not in part:
            raise ValueError(f'"{part}" is not name=value')
        k, v = part.split('=', 1)
        out.append((k.strip(), v.strip()))
    return out


def device_id(key):
    return re.sub(r'[^a-z0-9_]', '', key.lower())[:MAX_ID]


def _build(dev_id, key, settings, default_user, default_pw, problems):
    """settings: {canonical: raw string}. Returns DeviceCfg or None."""
    where = f'{key}:'
    host = settings.get('host', '').strip()
    user = settings.get('user', '').strip() or default_user
    pw = settings.get('password', '') or default_pw
    missing = [n for n, v in (('host', host), ('user', user), ('password', pw)) if not v]
    if missing:
        problems.append(f'{where} missing {", ".join(missing)}')
        return None
    port = None
    if settings.get('port', '').strip():
        p = settings['port'].strip()
        if p.isdigit():
            port = int(p)
        else:
            problems.append(f'{where} port "{p}" is not a number, ignored')
    https = None
    if 'https' in settings:
        try:
            https = parse_bool(settings['https'])
        except ValueError as err:
            problems.append(f'{where} https {err}, ignored')
    lists = {}
    for name in ('use', 'exclude'):
        lists[name] = None
        if settings.get(name, '').strip():
            chans, bad = parse_cam_list(settings[name])
            if bad:
                problems.append(f'{where} {name}: ignoring {", ".join(bad)} '
                                f'(camera numbers start at 1, e.g. 1,4,5)')
            lists[name] = chans
    return DeviceCfg(id=dev_id, key=key, host=host, user=user, pw=pw, port=port,
                     https=https, use=lists['use'],
                     exclude=lists['exclude'] or frozenset())


def parse_params(params):
    """params: dict of custom parameters. Returns (devices, problems)."""
    problems = []
    devices = []
    seen = {}
    norm = {k.strip().lower(): (v or '') for k, v in params.items()}
    default_user = norm.get('username', '').strip() or norm.get('user', '').strip()
    default_pw = norm.get('password', '') or norm.get('pass', '')

    def add(dev):
        if dev is None:
            return
        if dev.id in seen:
            problems.append(f'{dev.key}: same node prefix "{dev.id}" as {seen[dev.id]}, '
                            f'ignored (use keys that differ in the first {MAX_ID} characters)')
            return
        seen[dev.id] = dev.key
        devices.append(dev)

    for key, value in params.items():
        if not DEVICE_KEY.match(key.strip()):
            continue
        settings = {}
        try:
            pairs = split_line(value or '')
        except ValueError as err:
            problems.append(f'{key}: {err}')
            continue
        for raw_name, val in pairs:
            name = field_name(raw_name)
            if name is None:
                problems.append(f'{key}: unknown setting "{raw_name}", ignored')
                continue
            settings[name] = val
        if not settings:
            problems.append(f'{key}: no settings (expected e.g. host=1.2.3.4;user=guest;pass=...)')
            continue
        add(_build(device_id(key.strip()), key.strip(), settings,
                   default_user, default_pw, problems))

    # original single-device keys
    if norm.get('host', '').strip():
        if LEGACY_ID in seen:
            problems.append(f'host: ignored because "{seen[LEGACY_ID]}" already '
                            f'defines device "{LEGACY_ID}"')
        else:
            legacy = {'host': norm['host'], 'port': norm.get('port', ''),
                      'use': norm.get('use', '') or norm.get('include', ''),
                      'exclude': norm.get('exclude', '') or norm.get('ignore', '')}
            if norm.get('use_https', '').strip():
                legacy['https'] = norm['use_https']
            add(_build(LEGACY_ID, 'host', legacy, default_user, default_pw, problems))

    if not devices and not problems:
        problems.append('No NVR or camera configured. Add a parameter like '
                        'nvr = host=192.168.1.50;user=guest;pass=...')
    return devices, problems
