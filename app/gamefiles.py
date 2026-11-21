import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time

from vltdb import AttribDB, FormatError

ATTR = os.path.join('GLOBAL', 'attributes.bin')
GMF = os.path.join('GLOBAL', 'GlobalMemoryFile.bin')
STUDIO_DIR = 'ModStudio'
BACKUP_DIR = os.path.join(STUDIO_DIR, 'backup')
CONFIG_FILE = os.path.join(STUDIO_DIR, 'applied_config.json')
EXTRA_OPTIONS_ASI = os.path.join('scripts', 'NFSMWExtraOptions.asi')
EXTRA_OPTIONS_INI = os.path.join('scripts', 'NFSMWExtraOptionsSettings.ini')
COPFLY_ASI = os.path.join('scripts', 'NFSMWCopFly.asi')
COPFLY_INI = os.path.join('scripts', 'NFSMWCopFly.ini')
COPFLY_LOG = os.path.join('scripts', 'NFSMWCopFly.log')
LANG_LABELS = os.path.join('LANGUAGES', 'Labels.bin')
LANG_TEXT = os.path.join('LANGUAGES', 'English.bin')

LINKS = {
    'extra_options': 'https://github.com/ExOptsTeam/NFSMWExOpts/releases',
    'asi_loader': 'https://github.com/ThirteenAG/Ultimate-ASI-Loader/releases',
    'widescreen_fix': 'https://github.com/ThirteenAG/WidescreenFixesPack/releases/tag/nfsmw',
}


def resource(*parts):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def app_settings_path():
    root = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(root, 'NFSMW Mod Studio', 'settings.json')


def load_app_settings():
    try:
        with open(app_settings_path(), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_app_settings(s):
    p = app_settings_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(s, f, indent=2)


def is_game_dir(path):
    return bool(path) and os.path.isfile(os.path.join(path, 'speed.exe')) and os.path.isfile(os.path.join(path, ATTR))


def detect_game_dirs():
    found = []
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in (r'SOFTWARE\WOW6432Node\EA GAMES\Need for Speed Most Wanted',
                        r'SOFTWARE\EA GAMES\Need for Speed Most Wanted'):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        found.append(winreg.QueryValueEx(k, 'Install Dir')[0])
                except OSError:
                    pass
    except ImportError:
        pass
    for drive in 'CDEFG':
        for rel in (r'Games\nfsmw', r'Games\Need for Speed Most Wanted', r'Games\NFS Most Wanted',
                    r'Program Files (x86)\EA GAMES\Need for Speed Most Wanted',
                    r'Program Files\EA GAMES\Need for Speed Most Wanted',
                    r'Program Files (x86)\Steam\steamapps\common\Need for Speed Most Wanted'):
            found.append('%s:\\%s' % (drive, rel))
    out = []
    for p in found:
        p = os.path.normpath(p.strip('"')) if p else p
        if is_game_dir(p) and p not in out:
            out.append(p)
    return out


def game_running():
    try:
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq speed.exe', '/NH'], capture_output=True, text=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=10)
        return 'speed.exe' in r.stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _write_atomic(path, data):
    tmp = path + '.modstudio-tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


COPFLY_SLOTS = {0x8AD460: 0x69CA30, 0x8AD2F4: 0x69C030, 0x8AD378: 0x69C030, 0x8AD020: 0x68BC80, 0x8AC950: 0x68BC80}


def _pe_reader(data):
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    nsec = struct.unpack_from('<H', data, pe + 6)[0]
    opt = struct.unpack_from('<H', data, pe + 20)[0]
    base = struct.unpack_from('<I', data, pe + 24 + 28)[0]
    secs = [struct.unpack_from('<IIII', data, pe + 24 + opt + 40 * i + 8) for i in range(nsec)]

    def u32(va):
        for vs, rva, rs, ro in secs:
            if base + rva <= va < base + rva + rs:
                return struct.unpack_from('<I', data, va - base - rva + ro)[0]
        return None
    return u32


def copfly_compatible(game):
    try:
        with open(os.path.join(game, 'speed.exe'), 'rb') as f:
            u32 = _pe_reader(f.read())
        return all(u32(slot) == fn for slot, fn in COPFLY_SLOTS.items())
    except (OSError, struct.error):
        return False


def asi_loader_present(game):
    for dll in ('dinput8.dll', 'winmm.dll', 'version.dll', 'dsound.dll', 'd3d9.dll', 'vorbisFile.dll'):
        p = os.path.join(game, dll)
        if os.path.isfile(p):
            try:
                with open(p, 'rb') as f:
                    data = f.read()
            except OSError:
                continue
            for s in ('Ultimate ASI Loader', '.asi'):
                if s.encode() in data or s.encode('utf-16-le') in data:
                    return dll
    return None


def _language_table(path):
    with open(path, 'rb') as f:
        d = f.read()
    cid, _, _, n, hashes, texts = struct.unpack_from('<6I', d, 0)
    if cid != 0x39000:
        return {}
    out = {}
    for i in range(n):
        h, off = struct.unpack_from('<II', d, 8 + hashes + 8 * i)
        start = 8 + texts + off
        out[h] = d[start:d.index(b'\0', start)].decode('cp1252', 'replace')
    return out


def car_names(game, cars):
    try:
        labels = _language_table(os.path.join(game, LANG_LABELS))
        text = _language_table(os.path.join(game, LANG_TEXT))
    except (OSError, struct.error, ValueError):
        return {}
    out = {}
    for car in cars:
        tail = '_' + car.upper()
        hits = {text[h] for h, lab in labels.items() if lab.startswith('CARNAME_') and lab.endswith(tail) and text.get(h)}
        if len(hits) == 1:
            out[car] = hits.pop()
    return out


def save_dirs():
    docs = None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:
            docs = buf.value
    except (AttributeError, OSError):
        pass
    root = os.path.join(docs or os.path.join(os.path.expanduser('~'), 'Documents'), 'NFS Most Wanted')
    try:
        return [os.path.join(root, n) for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
    except OSError:
        return []


def garage_vehicles(keys):
    pats = {k: struct.pack('<I', k) for k in keys}
    found = set()
    for d in save_dirs():
        try:
            with open(os.path.join(d, os.path.basename(d)), 'rb') as f:
                data = f.read()
        except OSError:
            continue
        found |= {k for k, p in pats.items() if p in data}
    return found


class Game:
    def __init__(self, path):
        self.path = os.path.normpath(path)

    def p(self, rel):
        return os.path.join(self.path, rel)

    def has_backup(self):
        return os.path.isfile(self.p(os.path.join(BACKUP_DIR, 'attributes.bin')))

    def backup_info(self):
        try:
            with open(self.p(os.path.join(BACKUP_DIR, 'info.json')), encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def make_backup(self):
        if self.has_backup():
            return False
        d = self.p(BACKUP_DIR)
        os.makedirs(d, exist_ok=True)
        AttribDB(open(self.p(ATTR), 'rb').read())
        info = {'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'files': {}}
        for rel in (ATTR, GMF):
            if os.path.isfile(self.p(rel)):
                shutil.copy2(self.p(rel), os.path.join(d, os.path.basename(rel)))
                info['files'][os.path.basename(rel)] = sha256(self.p(rel))
        with open(os.path.join(d, 'info.json'), 'w', encoding='utf-8') as f:
            json.dump(info, f, indent=2)
        return True

    def files_modified(self):
        if not self.has_backup():
            return False
        for rel in (ATTR, GMF):
            b = self.p(os.path.join(BACKUP_DIR, os.path.basename(rel)))
            if os.path.isfile(b) and os.path.isfile(self.p(rel)):
                if os.path.getsize(b) != os.path.getsize(self.p(rel)) or sha256(b) != sha256(self.p(rel)):
                    return True
        return False

    def original_db(self):
        src = self.p(os.path.join(BACKUP_DIR, 'attributes.bin')) if self.has_backup() else self.p(ATTR)
        with open(src, 'rb') as f:
            return AttribDB(f.read())

    def _save_info(self, info):
        with open(self.p(os.path.join(BACKUP_DIR, 'info.json')), 'w', encoding='utf-8') as f:
            json.dump(info, f, indent=2)

    def _remember_written(self):
        info = self.backup_info()
        info['applied'] = {os.path.basename(rel): sha256(self.p(rel)) for rel in (ATTR, GMF) if os.path.isfile(self.p(rel))}
        self._save_info(info)

    def _build(self, cfg, apply_config):
        bdir = self.p(BACKUP_DIR)
        with open(os.path.join(bdir, 'attributes.bin'), 'rb') as f:
            base = f.read()
        out, stats = apply_config(AttribDB(base), cfg)
        AttribDB(out)
        notes = []
        gmf_src = os.path.join(bdir, 'GlobalMemoryFile.bin')
        gmf_out = None
        if os.path.isfile(gmf_src):
            gmf = bytearray(open(gmf_src, 'rb').read())
            at = gmf.find(base)
            if at >= 0:
                gmf[at:at + len(out)] = out
                gmf_out = bytes(gmf)
            else:
                copies = 0
                for i, end in _embedded_dbs(gmf):
                    copies += 1
                    try:
                        patched, _ = apply_config(AttribDB(bytes(gmf[i:end])), cfg)
                        gmf[i:end] = patched
                        gmf_out = bytes(gmf)
                    except (FormatError, KeyError, struct.error, IndexError):
                        continue
                if copies and gmf_out is None:
                    notes.append('GlobalMemoryFile.bin has no readable copy of the car database; only '
                                 'attributes.bin was changed, so the game may not see the changes.')
        return out, gmf_out, stats, notes

    def apply_data(self, cfg, apply_config):
        self.make_backup()
        out, gmf_out, stats, notes = self._build(cfg, apply_config)
        _write_atomic(self.p(ATTR), out)
        if gmf_out is not None:
            _write_atomic(self.p(GMF), gmf_out)
        self._remember_written()
        return stats, notes

    def sync_backup(self, apply_config, remove_mods):
        if not self.has_backup():
            return False
        info = self.backup_info()
        live = {rel: self.p(rel) for rel in (ATTR, GMF) if os.path.isfile(self.p(rel))}
        hashes = {rel: sha256(p) for rel, p in live.items()}
        known = lambda rel: hashes[rel] in (info.get('files', {}).get(os.path.basename(rel)),
                                            info.get('applied', {}).get(os.path.basename(rel)))
        changed = [rel for rel in live if not known(rel)]
        applied = self.load_applied()
        if changed and 'applied' not in info and applied:
            try:
                out, gmf_out, _, _ = self._build(applied, apply_config)
                expect = {ATTR: out, GMF: gmf_out}
                changed = [rel for rel in changed if expect[rel] is None or open(live[rel], 'rb').read() != expect[rel]]
            except (FormatError, KeyError, struct.error, IndexError):
                pass
        if not changed:
            if 'applied' not in info and applied:
                self._remember_written()
            return False
        orig = self.original_db()
        new = {}
        for rel in changed:
            data = open(live[rel], 'rb').read()
            if rel == ATTR:
                new[rel] = remove_mods(AttribDB(data), orig, applied)[0] if applied else data
            else:
                gmf = bytearray(data)
                for i, end in _embedded_dbs(gmf):
                    try:
                        if applied:
                            gmf[i:end] = remove_mods(AttribDB(bytes(gmf[i:end])), orig, applied)[0]
                    except (FormatError, KeyError, struct.error, IndexError):
                        continue
                new[rel] = bytes(gmf)
        AttribDB(new.get(ATTR) or open(live[ATTR], 'rb').read())
        bdir = self.p(BACKUP_DIR)
        stamp = time.strftime('%Y-%m-%d %H-%M-%S')
        old = os.path.join(bdir, 'older', stamp)
        os.makedirs(old, exist_ok=True)
        for name in ('attributes.bin', 'GlobalMemoryFile.bin', 'info.json'):
            if os.path.isfile(os.path.join(bdir, name)):
                shutil.copy2(os.path.join(bdir, name), os.path.join(old, name))
        files = info.setdefault('files', {})
        for rel, data in new.items():
            _write_atomic(os.path.join(bdir, os.path.basename(rel)), data)
            files[os.path.basename(rel)] = hashlib.sha256(data).hexdigest()
        info['applied'] = {os.path.basename(rel): h for rel, h in hashes.items()}
        info['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
        info['updated_note'] = ('the game files were changed by another tool (e.g. an add-on car); this backup keeps '
                                'those changes without the studio\'s mods. Earlier backup: older\\' + stamp)
        self._save_info(info)
        return True

    def restore_data(self):
        bdir = self.p(BACKUP_DIR)
        for rel in (ATTR, GMF):
            b = os.path.join(bdir, os.path.basename(rel))
            if os.path.isfile(b):
                shutil.copy2(b, self.p(rel))

    def load_applied(self):
        try:
            with open(self.p(CONFIG_FILE), encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def save_applied(self, cfg):
        os.makedirs(self.p(STUDIO_DIR), exist_ok=True)
        with open(self.p(CONFIG_FILE), 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)

    def extra_options_installed(self):
        return os.path.isfile(self.p(EXTRA_OPTIONS_ASI)) and os.path.isfile(self.p(EXTRA_OPTIONS_INI))

    HEAT_KEYS = ('HeatLevelOverride', 'MinimumHeatLevel', 'MaximumHeatLevel', 'PursuitActionMode')

    def read_heat(self):
        vals = read_ini_values(self.p(EXTRA_OPTIONS_INI), 'Pursuit', self.HEAT_KEYS)
        try:
            return {'override': int(float(vals.get('HeatLevelOverride', 0))) == 1,
                    'min': int(float(vals.get('MinimumHeatLevel', 1))),
                    'max': int(float(vals.get('MaximumHeatLevel', 5))),
                    'action_mode': int(float(vals.get('PursuitActionMode', 0))) == 1}
        except ValueError:
            return {'override': False, 'min': 1, 'max': 5, 'action_mode': False}

    def write_heat(self, heat):
        write_ini_values(self.p(EXTRA_OPTIONS_INI), 'Pursuit', {
            'HeatLevelOverride': int(bool(heat['override'])), 'MinimumHeatLevel': int(heat['min']),
            'MaximumHeatLevel': int(heat['max']), 'PursuitActionMode': int(bool(heat['action_mode']))})

    def copfly_installed(self):
        return os.path.isfile(self.p(COPFLY_ASI))

    def read_copfly(self):
        from copfly_cfg import SETTINGS
        vals = read_ini_values(self.p(COPFLY_INI), 'CopFly', [s.key for s in SETTINGS])
        out = {}
        for s in SETTINGS:
            try:
                out[s.key] = float(vals[s.key]) if s.key in vals else s.default
            except ValueError:
                out[s.key] = s.default
        return out

    def copfly_modes(self):
        keys = ['Launch', 'KeepSpeed', 'KeepSpeedCops', 'KeepSpeedTraffic', 'KeepSpeedWalls']
        vals = read_ini_values(self.p(COPFLY_INI), 'CopFly', keys)
        on = lambda k, d: (vals.get(k) or str(d)).strip() not in ('0', '')
        old = on('KeepSpeed', 0)
        return on('Launch', 1), {'cops': on('KeepSpeedCops', int(old)), 'traffic': on('KeepSpeedTraffic', int(old)),
                                 'walls': on('KeepSpeedWalls', 0)}

    def install_copfly(self, settings, launch=True, keep=None):
        from copfly_cfg import ini_text
        asi = resource('copfly', 'NFSMWCopFly.asi')
        if not os.path.isfile(asi):
            raise FileNotFoundError('the CopFly plugin is not bundled with this copy of the studio (run build.py, '
                                    'or use the exe from the GitHub releases)')
        os.makedirs(self.p('scripts'), exist_ok=True)
        shutil.copy2(asi, self.p(COPFLY_ASI))
        with open(self.p(COPFLY_INI), 'w', encoding='utf-8') as f:
            f.write(ini_text(settings, launch, keep))

    def uninstall_copfly(self):
        for rel in (COPFLY_ASI, COPFLY_INI, COPFLY_LOG):
            if os.path.isfile(self.p(rel)):
                os.remove(self.p(rel))


def _embedded_dbs(gmf):
    out = []
    for m in re.finditer(b'VPAK\x01\x00\x00\x00', gmf):
        i = m.start()
        try:
            _, _, _, voff = struct.unpack_from('<4I', gmf, i + 0x14)
            vsize = struct.unpack_from('<I', gmf, i + 0x18)[0]
        except struct.error:
            continue
        if i + voff + vsize <= len(gmf):
            out.append((i, i + voff + vsize))
    return out


_LINE = re.compile(r'^(\s*)([A-Za-z0-9_]+)(\s*=\s*)([^\s;/]*)(.*)$')


def read_ini_values(path, section, keys):
    out, cur = {}, None
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                s = line.strip()
                if s.startswith('['):
                    cur = s[1:s.index(']')] if ']' in s else s[1:]
                    continue
                if cur == section:
                    m = _LINE.match(line.rstrip('\n'))
                    if m and m.group(2) in keys:
                        out[m.group(2)] = m.group(4)
    except OSError:
        pass
    return out


def write_ini_values(path, section, values):
    with open(path, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    cur, done = None, set()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith('['):
            if cur == section:
                missing = [k for k in values if k not in done]
                lines[i:i] = ['%s = %s\n' % (k, values[k]) for k in missing]
                done.update(missing)
                break
            cur = s[1:s.index(']')] if ']' in s else s[1:]
            continue
        if cur == section:
            m = _LINE.match(line.rstrip('\n'))
            if m and m.group(2) in values and m.group(2) not in done:
                v = str(values[m.group(2)])
                pad = max(len(m.group(4)) - len(v), 0) * ' '
                lines[i] = '%s%s%s%s%s%s\n' % (m.group(1), m.group(2), m.group(3), v, pad, m.group(5))
                done.add(m.group(2))
    missing = [k for k in values if k not in done]
    if missing:
        if cur != section:
            lines.append('\n[%s]\n' % section)
        lines += ['%s = %s\n' % (k, values[k]) for k in missing]
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
