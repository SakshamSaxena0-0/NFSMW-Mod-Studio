import json
import os
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))

import copfly_cfg
import gamefiles as G
import hooks
import tuning as T

GAME = os.environ.get('MODSTUDIO_TEST_GAME', r'C:\Games\nfsmw')
OLD_DEFAULT = {
    'version': 1,
    'cars': {},
    'police': {'enabled': False, 'knobs': {}, 'no_puncture': False},
    'world': {'no_stopping': False, 'keep_cops': False, 'keep_traffic': False, 'keep_walls': False},
    'nitro': {'boost': 3.0, 'all_racers': False},
    'heat': None,
    'copfly': {'installed': False, 'settings': {}},
}


def file_offset(data, va):
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    opt = struct.unpack_from('<H', data, pe + 20)[0]
    base = struct.unpack_from('<I', data, pe + 24 + 28)[0]
    for i in range(struct.unpack_from('<H', data, pe + 6)[0]):
        vs, rva, rs, ro = struct.unpack_from('<IIII', data, pe + 24 + opt + 40 * i + 8)
        if base + rva <= va < base + rva + rs:
            return va - base - rva + ro
    raise ValueError(hex(va))


def original_attributes():
    for rel in (os.path.join('ModStudio', 'backup', 'attributes.bin'), os.path.join('GLOBAL', 'attributes.bin')):
        p = os.path.join(GAME, rel)
        if os.path.isfile(p):
            return p
    return None


class DefaultConfig(unittest.TestCase):
    def test_everything_else_unchanged(self):
        cfg = T.default_config()
        camera = cfg.pop('camera')
        self.assertEqual(cfg, OLD_DEFAULT)
        self.assertEqual(camera, {'fov_speed': False, 'smooth': False, 'settings': {}})

    def test_normalize_keeps_old_profiles(self):
        old = json.loads(json.dumps(OLD_DEFAULT))
        old['copfly'] = {'installed': True, 'settings': {'UpSpeed': 20}}
        cfg = T.normalize(old)
        self.assertEqual(cfg['camera'], {'fov_speed': False, 'smooth': False, 'settings': {}})
        self.assertEqual(cfg['copfly'], old['copfly'])

    def test_ini_unchanged_when_camera_off(self):
        text = copfly_cfg.ini_text(copfly_cfg.DEFAULTS, True, {'cops': True})
        copfly, camera = text.split('\n[Camera]\n')
        self.assertIn('Launch = 1', copfly)
        self.assertIn('KeepSpeedCops = 1', copfly)
        self.assertRegex(camera, r'(?m)^FovSpeed = 0 ')
        self.assertRegex(camera, r'(?m)^SmoothCam = 0 ')
        self.assertRegex(camera, r'(?m)^Log = 0 ')


class CameraValues(unittest.TestCase):
    def test_clamped(self):
        cfg = T.normalize({'camera': {'fov_speed': True, 'smooth': 1, 'settings': {
            'FovMaxExtra': 500, 'FovResponse': -3, 'SmoothAmount': 7, 'ShakeScale': -1, 'Log': 5}}})
        cam = cfg['camera']
        self.assertTrue(cam['fov_speed'])
        self.assertTrue(cam['smooth'])
        self.assertEqual(cam['settings']['FovMaxExtra'], 30)
        self.assertEqual(cam['settings']['FovResponse'], 0.02)
        self.assertEqual(cam['settings']['SmoothAmount'], 1)
        self.assertEqual(cam['settings']['ShakeScale'], 0)
        self.assertEqual(cam['settings']['Log'], 1)

    def test_rejects_bad_values(self):
        cfg = T.normalize({'camera': {'fov_speed': 'yes', 'smooth': [1], 'settings': {
            'FovMaxExtra': float('nan'), 'FovResponse': float('inf'), 'SmoothAmount': '0.5', 'ShakeScale': None,
            'Evil': 3, 'FovStartSpeed': 12}}})
        cam = cfg['camera']
        self.assertFalse(cam['fov_speed'])
        self.assertFalse(cam['smooth'])
        self.assertEqual(set(cam['settings']), {'FovStartSpeed'})
        self.assertEqual(cam['settings']['FovStartSpeed'], 12)

    def test_full_speed_above_start(self):
        cam = T.normalize({'camera': {'settings': {'FovStartSpeed': 90, 'FovFullSpeed': 40}}})['camera']
        self.assertEqual(cam['settings']['FovFullSpeed'], 91)
        cam = T.normalize({'camera': {'settings': {'FovStartSpeed': 95}}})['camera']
        self.assertEqual(cam['settings']['FovFullSpeed'], 96)

    def test_not_a_dict(self):
        self.assertEqual(T.normalize({'camera': 'on'})['camera'], {'fov_speed': False, 'smooth': False, 'settings': {}})
        self.assertEqual(T.normalize({'camera': {'settings': [1, 2]}})['camera']['settings'], {})


class IniRoundTrip(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.game = G.Game(self.dir)
        self.asi = G.resource('copfly', 'NFSMWCopFly.asi')
        if not os.path.isfile(self.asi):
            self.skipTest('plugin not built (run build.py)')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_read_back(self):
        cam = {'fov_speed': True, 'smooth': False, 'settings': {'FovMaxExtra': 8.5, 'ShakeScale': 0.25, 'Log': 1}}
        self.game.install_copfly({}, launch=False, keep={}, camera=cam)
        self.assertEqual(self.game.camera_modes(), (True, False))
        got = self.game.read_camera()
        self.assertEqual(got['FovMaxExtra'], 8.5)
        self.assertEqual(got['ShakeScale'], 0.25)
        self.assertEqual(got['Log'], 1)
        self.assertEqual(got['FovFullSpeed'], copfly_cfg.CAMERA_DEFAULTS['FovFullSpeed'])
        launch, keep = self.game.copfly_modes()
        self.assertFalse(launch)
        self.assertFalse(any(keep.values()))

    def test_no_camera_section(self):
        os.makedirs(os.path.join(self.dir, 'scripts'))
        with open(self.game.p(G.COPFLY_INI), 'w') as f:
            f.write('[CopFly]\nEnabled = 1\n')
        self.assertEqual(self.game.camera_modes(), (False, False))
        self.assertEqual(self.game.read_camera(), copfly_cfg.CAMERA_DEFAULTS)


class Addresses(unittest.TestCase):
    def test_call_target(self):
        mem = {0x1000: 0x123456E8, 0x1001: 0xFFFFFB12}
        self.assertEqual(hooks.call_target(mem.get, 0x1000), 0x1000 + 5 - 0x4EE)
        self.assertIsNone(hooks.call_target({0x1000: 0x90, 0x1001: 0}.get, 0x1000))

    def test_header_has_every_address(self):
        text = hooks.header()
        for name, a, fname, b in hooks.COPFLY_SLOTS + hooks.CAMERA_SLOTS + hooks.CAMERA_CALLS:
            self.assertIn('#define %s ' % name, text)
            self.assertIn('#define %s_ADDR 0x%08X' % (fname, b), text)
            self.assertIn('0x%08X' % a, text)

    def test_plugin_source_uses_the_header(self):
        with open(os.path.join(ROOT, 'copfly', 'copfly.c'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn('#include "hooks.h"', src)
        flat = src.upper().replace('0X00', '0X')
        for _, a, _, b in hooks.COPFLY_SLOTS + hooks.CAMERA_SLOTS + hooks.CAMERA_CALLS:
            self.assertNotIn('0X%06X' % a, flat)
            self.assertNotIn('0X%06X' % b, flat)

    def test_real_exe(self):
        exe = os.path.join(GAME, 'speed.exe')
        if not os.path.isfile(exe):
            self.skipTest('no speed.exe at ' + GAME)
        self.assertTrue(G.copfly_compatible(GAME))
        self.assertTrue(G.camera_compatible(GAME))
        d = tempfile.mkdtemp()
        try:
            with open(exe, 'rb') as f:
                data = bytearray(f.read())
            raw = file_offset(data, hooks.CAMERA_CALLS[0][1])
            self.assertEqual(data[raw], 0xE8)
            data[raw + 1] ^= 0xFF
            with open(os.path.join(d, 'speed.exe'), 'wb') as f:
                f.write(data)
            self.assertFalse(G.camera_compatible(d))
            self.assertTrue(G.copfly_compatible(d))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class ApplyRestore(unittest.TestCase):
    def setUp(self):
        src = original_attributes()
        if not src:
            self.skipTest('no attributes.bin under ' + GAME)
        if not os.path.isfile(G.resource('copfly', 'NFSMWCopFly.asi')):
            self.skipTest('plugin not built (run build.py)')
        if G.game_running():
            self.skipTest('the game is running')
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, 'GLOBAL'))
        shutil.copy2(src, os.path.join(self.dir, G.ATTR))
        exe = os.path.join(GAME, 'speed.exe')
        if os.path.isfile(exe):
            shutil.copy2(exe, os.path.join(self.dir, 'speed.exe'))
        else:
            open(os.path.join(self.dir, 'speed.exe'), 'wb').close()
        with open(src, 'rb') as f:
            self.original = f.read()
        self.env = os.environ.get('MODSTUDIO_GAME_DIR')
        os.environ['MODSTUDIO_GAME_DIR'] = self.dir
        import modstudio
        self.api = modstudio.Api()
        self.assertEqual(os.path.normcase(self.api._game.path), os.path.normcase(os.path.normpath(self.dir)))

    def tearDown(self):
        if self.env is None:
            os.environ.pop('MODSTUDIO_GAME_DIR', None)
        else:
            os.environ['MODSTUDIO_GAME_DIR'] = self.env
        shutil.rmtree(self.dir, ignore_errors=True)

    def attributes(self):
        with open(os.path.join(self.dir, G.ATTR), 'rb') as f:
            return f.read()

    def test_apply_then_restore(self):
        cfg = self.api.get_state()['cfg']
        car = self.api._cars[0][0]
        cfg['cars'][car] = {'enabled': True, 'knobs': {'power': 2.0, 'grip': 1.5}, 'nitro': False}
        cfg['camera'] = {'fov_speed': True, 'smooth': True, 'settings': {'FovMaxExtra': 10, 'ShakeScale': 0.5}}
        r = self.api.apply(cfg)
        self.assertTrue(r['ok'], r.get('error'))
        self.assertNotEqual(self.attributes(), self.original)
        game = self.api._game
        self.assertTrue(game.copfly_installed())
        self.assertEqual(game.camera_modes(), (True, True))
        self.assertEqual(game.read_camera()['FovMaxExtra'], 10)
        self.assertEqual(game.copfly_modes()[0], False)
        r = self.api.restore()
        self.assertTrue(r['ok'], r.get('error'))
        self.assertEqual(self.attributes(), self.original)
        cam = r['state']['cfg']['camera']
        self.assertTrue(cam['fov_speed'] and cam['smooth'])
        self.assertTrue(game.copfly_installed())
        cfg = r['state']['cfg']
        cfg['camera']['fov_speed'] = cfg['camera']['smooth'] = False
        r = self.api.apply(cfg)
        self.assertTrue(r['ok'], r.get('error'))
        self.assertFalse(game.copfly_installed())
        self.assertEqual(self.attributes(), self.original)

    def test_camera_only_leaves_data_alone(self):
        cfg = self.api.get_state()['cfg']
        cfg['camera']['smooth'] = True
        r = self.api.apply(cfg)
        self.assertTrue(r['ok'], r.get('error'))
        self.assertEqual(self.attributes(), self.original)
        self.assertEqual(self.api._game.camera_modes(), (False, True))
        self.assertIn('Camera: smoother, no shake', r['lines'])


if __name__ == '__main__':
    unittest.main()
