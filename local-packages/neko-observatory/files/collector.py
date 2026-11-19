#!/usr/bin/python3
"""Bounded tmpfs telemetry. Only authentication writes to the external AC."""
import collections
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import signal
import stat
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

RUNTIME = Path('/var/run/neko-observatory')
DEVICE = re.compile(r'[A-Za-z0-9_.:-]{1,63}')
MAC = re.compile(r'[0-9a-f]{12}')
MAX_ROWS = 2000


class CollectionError(Exception):
    """Only fixed error codes reach the cache; remote error bodies stay private."""


def bounded_int(value, default, low, high):
    try:
        result = int(value)
        return result if low <= result <= high else default
    except (ValueError, TypeError):
        return default


def text(value, limit=128):
    return ''.join(c for c in str('' if value is None else value) if c >= ' ' and c != '\x7f')[:limit]


def mac(value):
    value = str(value or '').lower().replace(':', '').replace('-', '')
    return ':'.join(value[i:i+2] for i in range(0, 12, 2)) if MAC.fullmatch(value) else ''


def address(value):
    try:
        ip = ipaddress.ip_address(value)
        return '' if ip.is_unspecified else str(ip)
    except ValueError:
        return ''


def command(args):
    return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=4).stdout


def uci_sections(name):
    result, current = [], None
    for line in command(['uci', '-q', 'export', name]).splitlines():
        parts = shlex.split(line, comments=True)
        if not parts:
            continue
        if parts[0] == 'config' and len(parts) >= 2:
            current = {'.type': parts[1], '.name': parts[2] if len(parts) > 2 else ''}
            result.append(current)
        elif current is not None and len(parts) == 3:
            if parts[0] == 'option':
                current[parts[1]] = parts[2]
            elif parts[0] == 'list':
                current.setdefault(parts[1], []).append(parts[2])
    return result


def private_password(path):
    if not path or not Path(path).is_absolute():
        raise CollectionError('credentials_missing')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise CollectionError('credentials_missing') from None
    meta = os.fstat(fd)
    if not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o077 or meta.st_uid != os.geteuid():
        os.close(fd)
        raise CollectionError('credentials_permissions')
    with os.fdopen(fd, 'rb') as stream:
        data = stream.read(4097)
    if not data.removesuffix(b'\n') or len(data) > 4096:
        raise CollectionError('credentials_invalid')
    try:
        # A single final LF is the file delimiter; do not strip credential whitespace.
        return data.removesuffix(b'\n').decode('utf-8')
    except UnicodeError:
        raise CollectionError('credentials_invalid') from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ACClient:
    ROUTES = {'ac/apsearch': ('apnum', 'aplist'), 'ac/stasearch': ('stanum', 'stalist'),
              'ac/hotspotsearch': ('hotspotnum', 'hotspotlist')}

    def __init__(self, url, credential):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            raise CollectionError('invalid_endpoint')
        self.base = url.rstrip('/') + '/api/'
        self.credential = credential
        self.session_value = None
        self.deadline = None
        # No environment proxy and no redirect can forward sysauth elsewhere.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, route, payload=None, authenticated=False):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise CollectionError('collection_timeout')
        if route.split('?', 1)[0] not in {*self.ROUTES, 'getrandom', 'sysauth'}:
            raise CollectionError('invalid_route')
        if (payload is not None) != (route == 'sysauth'):
            raise CollectionError('invalid_method')
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['sysauth'] = self.session_value
        body = json.dumps(payload).encode() if payload is not None else None
        try:
            with self.opener.open(urllib.request.Request(self.base + route, data=body, headers=headers), timeout=4) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise CollectionError('response_too_large')
            data = json.loads(raw)
        except (OSError, ValueError, urllib.error.URLError):
            raise CollectionError('request_failed') from None
        if not isinstance(data, dict):
            raise CollectionError('invalid_response')
        if data.get('ret') == -99:
            raise CollectionError('auth_expired')
        if data.get('ret') != 1:
            raise CollectionError('api_rejected')
        return data

    def login(self):
        nonce = self.request('getrandom').get('random', '')
        if not isinstance(nonce, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', nonce):
            raise CollectionError('invalid_nonce')
        digest = hashlib.md5((nonce + self.credential).encode()).hexdigest()
        session_value = self.request('sysauth', {'password': digest}).get('token')
        if not isinstance(session_value, str) or not re.fullmatch(r'[A-Za-z0-9_.=-]{1,256}', session_value):
            raise CollectionError('invalid_token')
        self.session_value = session_value

    def pages(self, route):
        total_field, list_field = self.ROUTES[route]
        rows = []
        signatures = set()
        for page in range(1, 21):
            query = urllib.parse.urlencode({'pagenum': page, 'numperpage': 100, 'groupid': 'all'})
            data = self.request(route + '?' + query, authenticated=True)
            total, batch = data.get(total_field), data.get(list_field, [])
            if type(total) is not int or not 0 <= total <= MAX_ROWS or not isinstance(batch, list):
                raise CollectionError('invalid_page')
            if any(not isinstance(item, dict) for item in batch) or len(batch) > 100:
                raise CollectionError('invalid_page')
            signature = hashlib.sha256(json.dumps(batch, sort_keys=True).encode()).hexdigest()
            if batch and signature in signatures:
                raise CollectionError('repeated_page')
            signatures.add(signature)
            rows.extend(batch)
            if len(rows) > MAX_ROWS:
                raise CollectionError('row_limit')
            if len(rows) >= total:
                return rows
            if not batch:
                raise CollectionError('incomplete_page')
        raise CollectionError('row_limit')

    def collect(self, now=None):
        self.deadline = time.monotonic() + 25
        for attempt in range(2):
            try:
                if not self.session_value:
                    self.login()
                aps = self.pages('ac/apsearch')
                clients = self.pages('ac/stasearch')
                hotspots = self.pages('ac/hotspotsearch')
                return sanitize_ac(aps, clients, hotspots, now or time.time())
            except CollectionError as exc:
                if str(exc) != 'auth_expired' or attempt:
                    raise
                self.session_value = None


def sanitize_ac(aps, clients, hotspots, now):
    ap_rows = []
    for ap in aps:
        row_id = mac(ap.get('mac'))
        if not row_id:
            continue
        ap_rows.append({'mac': row_id, 'name': text(ap.get('name')), 'ip': address(ap.get('ip', '')),
                        'model': text(ap.get('model')), 'online': ap.get('online') == 'yes',
                        'reported_at': bounded_int(ap.get('reporttime'), 0, 0, 2**40),
                        'clients': bounded_int(ap.get('clientnum'), 0, 0, MAX_ROWS)})
    client_rows = []
    for client in clients:
        row_id = mac(client.get('mac'))
        if not row_id:
            continue
        # Link-rate units are not verified. They are deliberately not traffic rates.
        client_rows.append({'mac': row_id, 'hostname': text(client.get('hostname')),
                            'ip': address(client.get('ip', '')), 'ssid': text(client.get('ssid')),
                            'vlan': text(client.get('vlan'), 16), 'apmac': mac(client.get('apmac')),
                            'radio': text(client.get('radio'), 16),
                            'signal': bounded_int(client.get('signal'), None, -150, 0)})
    ssids = {}
    for hotspot in hotspots:
        name, vlan, ap = text(hotspot.get('ssid')), text(hotspot.get('vlan'), 16), mac(hotspot.get('apmac'))
        row_id = (name, vlan)
        row = ssids.setdefault(row_id, {'ssid': name, 'vlan': vlan, 'aps': set(), 'bands': set()})
        if ap:
            row['aps'].add(ap)
        row['bands'].add(text(hotspot.get('radio'), 16))
    result = []
    for row_id, row in sorted(ssids.items()):
        result.append({**row, 'aps': sorted(row['aps']), 'bands': sorted(row['bands']),
                       'clients': len({c['mac'] for c in client_rows if (c['ssid'], c['vlan']) == row_id})})
    return {'collected_at': int(now), 'aps': ap_rows, 'clients': client_rows, 'ssids': result,
            'unique_clients': len({c['mac'] for c in client_rows}), 'associations': len(client_rows)}


class ACWorker:
    def __init__(self, config):
        self.config, self.lock, self.stop = config, threading.Lock(), threading.Event()
        self.data = {'state': 'pending' if config.get('ac_enabled') == '1' else 'disabled'}

    def collect_once(self):
        try:
            credential = private_password(self.config.get('ac_password_file', ''))
            # Re-read the file each collection so local credential rotation takes effect.
            if not hasattr(self, 'client') or self.client.credential != credential:
                self.client = ACClient(self.config.get('ac_url', ''), credential)
            data = self.client.collect()
            with self.lock:
                self.data = {**data, 'state': 'ok', 'attempted_at': int(time.time())}
        except Exception as exc:
            code = str(exc) if isinstance(exc, CollectionError) else 'collection_failed'
            with self.lock:
                self.data = {**self.data, 'state': code, 'attempted_at': int(time.time())}

    def run(self):
        if self.config.get('ac_enabled') != '1':
            return
        interval = bounded_int(self.config.get('ac_interval'), 30, 15, 3600)
        while not self.stop.is_set():
            self.collect_once()
            self.stop.wait(interval)

    def snapshot(self, now):
        with self.lock:
            data = dict(self.data)
        age = max(0, now - data['collected_at']) if 'collected_at' in data else None
        data['age'] = age
        data['stale'] = age is None or age > bounded_int(self.config.get('ac_stale_after'), 120, 30, 86400)
        data['ap_stale_after'] = bounded_int(self.config.get('ap_stale_after'), 180, 30, 86400)
        return data


def discover(interfaces, network, firewall, explicit, automatic=True):
    """One row per L3 netdevice: bridge/port/alias counters are never summed."""
    devices = {s.get('name'): s for s in network if s.get('.type') == 'device'}
    internal = set()
    external = set()
    for zone in firewall:
        if zone.get('.type') != 'zone':
            continue
        names = zone.get('network', [])
        if isinstance(names, str):
            names = names.split()
        (external if zone.get('masq') == '1' or zone.get('name', '').lower() in ('wan', 'wan6') else internal).update(names)
    manual = {s.get('interface'): s.get('label', '') for s in explicit if s.get('interface')}
    result = {}
    for iface in interfaces:
        name = iface.get('interface', '')
        dev = iface.get('l3_device') or iface.get('device', '')
        if not DEVICE.fullmatch(dev) or not DEVICE.fullmatch(name):
            continue
        config = devices.get(dev, {})
        tag = config.get('vid') or (dev.rsplit('.', 1)[-1] if '.' in dev else '')
        vlan = bounded_int(tag, None, 1, 4094)
        allowed = name in manual or (automatic and vlan is not None and name in internal and name not in external
                                    and iface.get('proto') not in ('pppoe', 'wireguard', 'neko_l2tp', 'vxlan'))
        if not allowed:
            continue
        if dev not in result:
            result[dev] = {'device': dev, 'interface': name, 'interfaces': [], 'vlan': vlan,
                           'label': text(manual.get(name) or name, 64), 'up': bool(iface.get('up'))}
        elif name in manual:
            result[dev]['label'] = text(manual[name] or name, 64)
        result[dev]['interfaces'].append(name)
    return [r for _, _, r in sorted((r['vlan'] or 0, r['device'], r) for r in result.values())][:32]


class Counters:
    def __init__(self, points=360):
        self.rows = {}
        self.points = points

    def update(self, devices, readings, mono, wall):
        active = set()
        output = []
        for device in devices:
            row_id = device['device']
            active.add(row_id)
            state = self.rows.setdefault(row_id, {'prev': None, 'history': collections.deque(maxlen=self.points),
                                               'upload': 0, 'download': 0, 'since': wall})
            current = readings.get(row_id)
            previous = state['prev']
            rate = None
            if current is not None and previous is not None:
                elapsed = mono - previous[0]
                old = previous[1]
                if 0 < elapsed <= 30 and current[0] == old[0] and current[1] >= old[1] and current[2] >= old[2]:
                    up, down = current[1] - old[1], current[2] - old[2]
                    rate = [up * 8 / elapsed, down * 8 / elapsed]
                    state['upload'] += up
                    state['download'] += down
            state['prev'] = (mono, current) if current is not None else None
            state['history'].append([int(wall), *(rate if rate is not None else [None, None])])
            output.append({**device, 'state': 'ok' if current is not None else 'unavailable',
                           'upload_bps': rate[0] if rate else None, 'download_bps': rate[1] if rate else None,
                           'upload_bytes': state['upload'], 'download_bytes': state['download'],
                           'since': int(state['since']), 'history': list(state['history'])})
        self.rows = {row_id: value for row_id, value in self.rows.items() if row_id in active}
        return output


def read_counter(device, sysfs=Path('/sys/class/net')):
    base = sysfs / device
    identity = (base/'ifindex').read_text().strip()
    # include the inode target identity to detect device deletion/recreation
    identity += ':' + str(base.stat().st_ino)
    rx = int((base/'statistics/rx_bytes').read_text())
    tx = int((base/'statistics/tx_bytes').read_text())
    return identity, rx, tx


def system_status():
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        row_id, value = line.split(':', 1)
        memory[row_id] = int(value.split()[0]) * 1024
    return {'uptime': int(float(Path('/proc/uptime').read_text().split()[0])),
            'load': [float(v) for v in Path('/proc/loadavg').read_text().split()[:3]],
            'memory_total': memory.get('MemTotal'), 'memory_available': memory.get('MemAvailable')}


def atomic_snapshot(path, data):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise CollectionError('unsafe_cache')
    fd, temporary = tempfile.mkstemp(prefix='.snapshot-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    os.umask(0o077)
    sections = uci_sections('neko-observatory')
    config = next((s for s in sections if s.get('.name') == 'main'), {})
    if config.get('enabled') != '1':
        return
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    if RUNTIME.is_symlink():
        raise CollectionError('unsafe_cache')
    if RUNTIME.stat().st_uid != os.geteuid():
        raise CollectionError('unsafe_cache')
    RUNTIME.chmod(0o700)
    interval = bounded_int(config.get('interval'), 5, 2, 15)
    counters = Counters(bounded_int(config.get('history_points'), 360, 60, 720))
    ac = ACWorker(config)
    thread = threading.Thread(target=ac.run, daemon=True)
    thread.start()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    devices, discovered_at = [], -60
    discovery_ok = False
    while not stop.is_set():
        started = time.monotonic()
        wall = time.time()
        if started - discovered_at >= 30:
            try:
                interfaces = json.loads(command(['ubus', 'call', 'network.interface', 'dump']))['interface']
                devices = discover(interfaces, uci_sections('network'), uci_sections('firewall'),
                                   [s for s in sections if s.get('.type') == 'vlan'], config.get('auto_discover') == '1')
                discovery_ok = True
            except Exception:
                discovery_ok = False
            discovered_at = started
        readings = {}
        for device in devices:
            try:
                readings[device['device']] = read_counter(device['device'])
            except (OSError, ValueError):
                pass
        try:
            system = system_status()
        except (OSError, ValueError):
            system = {}
        data = {'state': 'ok' if discovery_ok else 'discovery_failed', 'sampled_at': int(wall),
                'interval': interval, 'system': system, 'ac': ac.snapshot(wall),
                'vlans': counters.update(devices, readings, started, wall)}
        atomic_snapshot(RUNTIME/'snapshot.json', data)
        stop.wait(max(0.1, interval - (time.monotonic() - started)))
    ac.stop.set()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Exception text may contain upstream data or endpoint credentials.
        raise SystemExit('neko-observatory: collector stopped') from None
