import json
import os
import struct
import sys
import threading
import traceback
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import copfly_cfg
import gamefiles as G
import tuning as T
from profiles import BUILTIN_PROFILES, builtin_profile
from vltdb import FormatError

APP_NAME = 'NFSMW Mod Studio'
APP_VERSION = '1.7.0'
REPO_URL = ''


class Api:
    def __init__(self):
        self._window = None
        self._settings = G.load_app_settings()
        self._game = self._db = None
        self._cars, self._db_error = [], None
        self._notice = None
        self._dirty = False
        self._lock = threading.Lock()
        self._override = os.environ.get('MODSTUDIO_GAME_DIR')
        path = self._override or self._settings.get('game_dir')
        if not G.is_game_dir(path) and not self._override:
            found = G.detect_game_dirs()
            path = found[0] if found else ''
        self._open(path)

    def _open(self, path):
        self._game, self._db, self._cars, self._extra, self._db_error = None, None, [], [], None
        if path and G.is_game_dir(path):
            self._game = G.Game(path)
            try:
                self._sync()
                self._load_db()
            except (FormatError, OSError, KeyError, ValueError, struct.error) as e:
                self._db_error = str(e) or e.__class__.__name__
                self._db = None
            if not self._override:
                self._settings['game_dir'] = self._game.path
                G.save_app_settings(self._settings)

    def _sync(self):
        if self._game.sync_backup(T.apply_config, T.remove_mods):
            self._notice = ('Another tool changed your game files (for example, it added a car). The studio\'s '
                            'backup now includes that change, so Apply and Restore keep it.')
            return True
        return False

    def _load_db(self):
        self._db = self._game.original_db()
        cars = T.player_cars(self._db)
        names = G.car_names(self._game.path, [n for n, _ in cars if n not in T.CAR_NAMES])
        self._cars = [(n, names.get(n, disp)) for n, disp in cars]
        others = T.other_vehicles(self._db)
        applied = (self._game.load_applied() or {}).get('cars') or {}
        garage = G.garage_vehicles({T.h32(n) for n in others})
        self._extra = [n for n in others if T.h32(n) in garage
                       or (applied.get(n) or {}).get('enabled') or (applied.get(n) or {}).get('nitro')]
        self._cars += [(n, T.VEHICLE_NAMES.get(n, n)) for n in self._extra]

    def _name(self, car):
        return dict(self._cars).get(car) or T.CAR_NAMES.get(car, car)

    def _filter(self, cfg):
        cfg = T.normalize(cfg)
        known = {n for n, _ in self._cars}
        cfg['cars'] = {n: c for n, c in cfg['cars'].items() if n in known}
        if not (self._game and self._game.extra_options_installed()):
            cfg['heat'] = None
        return cfg

    def _current_cfg(self):
        cfg = T.default_config()
        needs_apply = False
        if self._game:
            applied = self._game.load_applied()
            if applied:
                cfg = T.normalize(applied)
            cfg['heat'] = self._game.read_heat() if self._game.extra_options_installed() else None
            plugin = self._game.copfly_installed()
            launch, keep = self._game.copfly_modes() if plugin else (False, {})
            installed = plugin and launch
            for kind in T.KEEP_KINDS:
                cfg['world']['keep_' + kind] = bool(plugin and keep.get(kind))
            cfg['copfly'] = {'installed': installed,
                             'settings': self._game.read_copfly() if installed
                             else dict(copfly_cfg.DEFAULTS, **(cfg['copfly'].get('settings') or {}))}
            data_mods = any(c.get('enabled') or c.get('nitro') for c in cfg['cars'].values()) or \
                cfg['police'].get('enabled') or cfg['police'].get('no_puncture') or cfg['nitro'].get('all_racers') or \
                cfg['world'].get('no_stopping')
            needs_apply = bool(data_mods and not self._game.files_modified())
        return self._filter(cfg), needs_apply

    def get_state(self):
        with self._lock:
            cfg, needs_apply = self._current_cfg()
            cars = []
            if self._db:
                targets = {n: T.car_targets(self._db, n) for n, _ in self._cars}
                listed = set(targets)
                for n, disp in self._cars:
                    route, extra = T.nitro_route(self._db, n)
                    garage = n in self._extra
                    cars.append({'id': n, 'name': disp, 'nitro': route,
                                 'via': self._name(extra) if route == 'via' else None,
                                 'shared': [d for o, d in self._cars if o != n and targets[o] & targets[n]],
                                 'garage': garage,
                                 'traffic': sorted(T.VEHICLE_NAMES.get(o, o) for o in T.shared_vehicles(self._db, n)
                                             if o not in listed) if garage else []})
            notice, self._notice = self._notice, None
            return {
                'app': {'name': APP_NAME, 'version': APP_VERSION, 'repo': REPO_URL},
                'game': {'path': self._game.path if self._game else '', 'ok': bool(self._db),
                         'error': self._db_error},
                'cars': cars,
                'knobs': [{'key': k.key, 'label': k.label, 'help': k.help, 'lo': k.lo, 'hi': k.hi,
                           'advanced': k.advanced, 'log': k.lo > 0} for k in T.KNOBS],
                'presets': T.PRESETS, 'presetNitro': sorted(T.PRESET_NITRO),
                'copflyDefs': [{'key': s.key, 'label': s.label, 'help': s.help, 'lo': s.lo, 'hi': s.hi,
                                'step': s.step, 'kind': s.kind, 'default': s.default} for s in copfly_cfg.SETTINGS],
                'extraOptions': bool(self._game and self._game.extra_options_installed()),
                'builtins': [{'name': n, 'desc': d} for n, d in BUILTIN_PROFILES],
                'links': G.LINKS,
                'cfg': cfg,
                'needsApply': needs_apply,
                'notice': notice,
            }

    def status(self):
        g = self._game
        if not g:
            return [{'title': 'Game folder', 'state': 'bad',
                     'text': 'No game folder selected, or speed.exe / GLOBAL\\attributes.bin not found.'}]
        out = [{'title': 'Game folder', 'state': 'ok', 'text': g.path}]
        if self._db:
            addons = [d for n, d in self._cars if n not in T.CAR_NAMES and n not in self._extra]
            extra = [self._name(n) for n in self._extra]
            out.append({'title': 'Car database', 'state': 'ok', 'text': '%d vehicles found, %d drivable cars%s%s.' % (
                len(self._db.collections_of(T.PVEHICLE)), len(self._cars) - len(extra),
                ' (add-on: %s)' % ', '.join(addons) if addons else '',
                '; from your garage: %s' % ', '.join(extra) if extra else '')})
        else:
            out.append({'title': 'Car database', 'state': 'bad', 'text': 'Could not read it: %s' % self._db_error})
        if g.has_backup():
            info = g.backup_info()
            out.append({'title': 'Backup of original files', 'state': 'ok',
                        'text': 'Saved %s in ModStudio\\backup.' % info.get('created', '') + (
                            ' Updated %s to keep changes made by other tools (like add-on cars).' % info['updated']
                            if info.get('updated') else '')})
        else:
            out.append({'title': 'Backup of original files', 'state': 'warn',
                        'text': 'Made automatically the first time you press Apply.'})
        try:
            mod = g.files_modified()
        except OSError:
            mod = False
        out.append({'title': 'Mods in game files', 'state': 'ok' if mod else 'off',
                    'text': 'Yes: the car data is modded.' if mod else 'No: the game files are original.'})
        loader = G.asi_loader_present(g.path)
        out.append({'title': 'ASI loader (plugins)', 'state': 'ok' if loader else 'warn',
                    'text': '%s found: scripts\\*.asi plugins load.' % loader if loader else
                    'Not found. CopFly and Extra Options need it (comes with the Widescreen Fix).',
                    'link': None if loader else G.LINKS['asi_loader']})
        eo = g.extra_options_installed()
        out.append({'title': 'Extra Options plugin', 'state': 'ok' if eo else 'warn',
                    'text': 'Installed: heat levels can be edited.' if eo else 'Not installed. Needed only for '
                    'heat above 5.', 'link': None if eo else G.LINKS['extra_options']})
        cf = G.copfly_compatible(g.path)
        out.append({'title': 'CopFly compatibility', 'state': 'ok' if cf else 'bad',
                    'text': 'speed.exe is v1.3: CopFly will work.' if cf else 'speed.exe is not v1.3: CopFly will not '
                    'work (everything else does).'})
        run = G.game_running()
        out.append({'title': 'Game running', 'state': 'warn' if run else 'ok',
                    'text': 'Running. Close it before you press Apply.' if run else 'Not running.'})
        return out

    def browse(self):
        res = self._window.create_file_dialog(G_FOLDER, directory=self._game.path if self._game else '')
        if res:
            self._open(res[0] if isinstance(res, (list, tuple)) else res)
            if not self._game:
                return {'error': 'That folder has no speed.exe and GLOBAL\\attributes.bin. Pick the folder NFS '
                                 'Most Wanted is installed in.'}
        return self.get_state()

    def autodetect(self):
        found = G.detect_game_dirs()
        if not found:
            return {'error': 'No NFS Most Wanted folder found automatically. Use Browse and pick the folder '
                             'that contains speed.exe.'}
        self._open(found[0])
        return self.get_state()

    def apply(self, cfg):
        if not self._game or not self._db:
            return {'ok': False, 'error': 'Select your NFS Most Wanted folder on the Game page first.'}
        if G.game_running():
            return {'ok': False, 'error': 'Need for Speed: Most Wanted is running. Close the game, then press '
                                          'Apply again.'}
        cfg = self._filter(cfg)
        try:
            with self._lock:
                first_backup = not self._game.has_backup()
                synced = self._sync()
                if synced:
                    self._load_db()
                    cfg = self._filter(cfg)
                stats, notes = self._game.apply_data(cfg, T.apply_config)
                if synced:
                    notes = [self._notice] + notes
                    self._notice = None
                if cfg.get('heat') is not None and self._game.extra_options_installed():
                    self._game.write_heat(cfg['heat'])
                keep = {kind: bool(cfg['world'].get('keep_' + kind)) for kind in T.KEEP_KINDS}
                if cfg['copfly'].get('installed') or any(keep.values()):
                    self._game.install_copfly(cfg['copfly'].get('settings', {}), launch=bool(cfg['copfly'].get('installed')),
                                              keep=keep)
                elif self._game.copfly_installed():
                    self._game.uninstall_copfly()
                self._game.save_applied(cfg)
        except PermissionError:
            return {'ok': False, 'error': 'Windows blocked writing to the game folder. Close the game and run '
                                          'NFSMW Mod Studio as administrator (right-click > Run as administrator).'}
        except Exception as e:
            traceback.print_exc()
            return {'ok': False, 'error': '%s: %s. Your original files are safe in ModStudio\\backup (Game page > '
                                          'Restore original game files).' % (e.__class__.__name__, e)}
        lines = []
        if first_backup:
            lines.append('Original files backed up to ModStudio\\backup')
        lines.append('Cars tuned: %d' % stats['cars'])
        if stats['nitro']:
            lines.append('Unlimited nitro: %s' % ', '.join(self._name(n) for n in stats['nitro']))
        if cfg['police'].get('enabled'):
            lines.append('Tougher cop cars')
        if cfg['police'].get('no_puncture'):
            lines.append('Spike-proof tires')
        if stats.get('props'):
            lines.append('No stopping on obstacles: %d kinds of props made light' % stats['props'])
        if cfg.get('heat') and cfg['heat'].get('override'):
            lines.append('Heat levels %d to %d' % (cfg['heat']['min'], cfg['heat']['max']))
        kept = [label for kind, label in (('cops', 'police cars'), ('traffic', 'traffic'), ('walls', 'walls'))
                if cfg['world'].get('keep_' + kind)]
        if kept:
            lines.append('No stopping on hits: %s' % ', '.join(kept))
        lines.append('CopFly %s' % ('installed' if cfg['copfly'].get('installed') else 'off'))
        return {'ok': True, 'lines': lines, 'notes': stats['skipped'] + notes, 'state': self.get_state()}

    def restore(self):
        if not self._game or not self._game.has_backup():
            return {'ok': False, 'error': 'There is no backup yet: the studio has not changed your game files.'}
        if G.game_running():
            return {'ok': False, 'error': 'Close the game first.'}
        try:
            with self._lock:
                cur, _ = self._current_cfg()
                self._game.restore_data()
                off = T.default_config()
                off['heat'], off['copfly'] = cur.get('heat'), cur['copfly']
                for kind in T.KEEP_KINDS:
                    off['world']['keep_' + kind] = cur['world'].get('keep_' + kind, False)
                self._game.save_applied(off)
        except PermissionError:
            return {'ok': False, 'error': 'Windows blocked writing to the game folder. Run as administrator.'}
        return {'ok': True, 'state': self.get_state()}

    def builtin(self, name):
        return self._filter(builtin_profile(name))

    def save_profile(self, cfg):
        res = self._window.create_file_dialog(G_SAVE, save_filename='my_nfsmw_setup.json',
                                             file_types=('Mod Studio setup (*.json)',))
        if not res:
            return False
        path = res[0] if isinstance(res, (list, tuple)) else res
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(T.normalize(cfg), f, indent=2)
        return os.path.basename(path)

    def load_profile(self):
        res = self._window.create_file_dialog(G_OPEN, file_types=('Mod Studio setup (*.json)', 'All files (*.*)'))
        if not res:
            return None
        path = res[0] if isinstance(res, (list, tuple)) else res
        try:
            with open(path, encoding='utf-8') as f:
                return {'cfg': self._filter(json.load(f)), 'name': os.path.basename(path)}
        except (OSError, ValueError) as e:
            return {'error': 'Could not read that file: %s' % e}

    def set_dirty(self, flag):
        self._dirty = bool(flag)

    def open_folder(self):
        if self._game:
            os.startfile(self._game.path)

    def open_log(self):
        p = self._game and self._game.p(G.COPFLY_LOG)
        if p and os.path.isfile(p):
            os.startfile(p)
            return True
        return False

    def open_url(self, url):
        if isinstance(url, str) and url.startswith('https://'):
            webbrowser.open(url)


G_FOLDER = G_OPEN = G_SAVE = None


def main():
    global G_FOLDER, G_OPEN, G_SAVE
    import webview
    G_FOLDER, G_OPEN, G_SAVE = webview.FileDialog.FOLDER, webview.FileDialog.OPEN, webview.FileDialog.SAVE
    api = Api()
    window = webview.create_window(APP_NAME, G.resource('ui', 'index.html'), js_api=api, width=1300, height=840,
                                   min_size=(1080, 700), background_color='#07080a')
    api._window = window

    def on_closing():
        if api._dirty:
            return window.create_confirmation_dialog(APP_NAME, 'You have changes that are not applied to the game '
                                                               'yet. Quit anyway?')
        return True
    window.events.closing += on_closing
    try:
        webview.start(gui='edgechromium', icon=G.resource('assets', 'icon.ico'))
    except Exception as e:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, 'NFSMW Mod Studio needs the Microsoft Edge WebView2 Runtime '
                                            '(built into Windows 11).\n\nGet it from:\nhttps://developer.microsoft.com/'
                                            'microsoft-edge/webview2/\n\n(%s)' % e, APP_NAME, 0x10)


if __name__ == '__main__':
    main()
