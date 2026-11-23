import itertools
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
from vltdb import AttribDB, h32

CLASS_WORDS = ['camerainfo', 'camera', 'cameras', 'cameramover', 'camerashake', 'camera_shake', 'shake', 'chase',
               'chasecam', 'bumper', 'hood', 'driver', 'drift', 'pursuit', 'effects', 'speedeffects', 'nos', 'pvehicle',
               'engine', 'transmission', 'tires', 'chassis', 'brakes', 'induction', 'ecar', 'aivehicle', 'simsurface',
               'rigidbodyspecs', 'collisionreactions', 'damagespecs', 'smackable', 'explosion', 'gameplay', 'fe',
               'frontend', 'presetride', 'presetcar', 'pursuitlevels', 'pursuitescalation', 'pursuitsupport',
               'pursuitlevelattribs', 'supportunits', 'heatlevels', 'cop', 'cops', 'world', 'weather', 'emitter',
               'emittergroup', 'emitterdata', 'fuelcell_effect', 'fuelcell_emitter', 'sound', 'audiosystem',
               'simnode', 'behavior', 'state', 'tuning', 'junkman', 'nis', 'icecam', 'icecamera', 'camerafx',
               'speedfx', 'blur', 'motionblur', 'visuallook', 'visualtreatment', 'tweak', 'tweaks', 'chopper',
               'helicopter', 'nosfx', 'colors', 'teams', 'races', 'quickrace', 'milestones', 'bounty', 'rewards',
               'trafficpattern', 'trafficgroup', 'carclass', 'carsfx', 'engineaudio', 'shiftpattern', 'track',
               'challenge', 'difficulty', 'aidifficulty', 'aiperformance', 'roadblocks', 'spikestrip', 'tirefx',
               'cameraanimation', 'camerablend', 'camerashakes', 'rumble', 'ffb', 'forcefeedback']
FIELD_WORDS = ['FOV', 'LAG', 'STIFFNESS', 'ANGLE', 'HEIGHT', 'LATEOFFSET', 'TILTING', 'SELECTABLE', 'LOOKBACK',
               'LOOKBACK_ANGLE', 'DISTANCE', 'SPEED', 'SHAKE', 'SHAKE_AMOUNT', 'SHAKE_SPEED', 'SHAKE_MAGNITUDE',
               'SHAKE_FREQUENCY', 'COLLISION_SHAKE', 'NOS_FOV', 'NOS_SHAKE', 'DAMPING', 'DAMP', 'OFFSET', 'TILT',
               'ZOOM', 'BLUR', 'FOCAL', 'HEIGHT_OFFSET', 'ANGLE_OFFSET', 'PITCH', 'ROLL', 'YAW', 'ELASTICITY',
               'SPRING', 'CAMERA', 'CAMERA_SHAKE', 'SPEED_SHAKE', 'TERRAIN_SHAKE', 'DRIFT', 'PURSUIT', 'NOS',
               'TIME', 'RANGE', 'MIN', 'MAX', 'MINSPEED', 'MAXSPEED', 'MIN_SPEED', 'MAX_SPEED', 'FOV_MIN', 'FOV_MAX',
               'FOV_SPEED', 'LAG_SPEED', 'ROTATION', 'ROTATION_LAG', 'POSITION_LAG', 'VELOCITY', 'TARGET',
               'TARGET_HEIGHT', 'LOOKAT', 'LOOKAT_HEIGHT', 'LOOK_AHEAD', 'INTENSITY', 'AMPLITUDE', 'FREQUENCY',
               'DURATION', 'DECAY', 'SCALE', 'NAME', 'TYPE', 'MASS', 'DETACH_FORCE', 'TORQUE', 'NOS_CAPACITY',
               'TORQUE_BOOST', 'FLOW_RATE', 'RECHARGE_MIN', 'RECHARGE_MAX', 'NOS_DISENGAGE']
HINTS = ('camera', 'chase', 'bumper', 'hood', 'driver', 'shake', 'fov', 'lag', 'stiff', 'damp', 'speed', 'nos',
         'nitro', 'tilt', 'blur', 'angle', 'height', 'close', 'far', 'drift', 'pursuit', 'look', 'zoom', 'effect')
TYPE_NAMES = {}


def names_for(words):
    out = {}
    for w in words:
        for v in {w, w.lower(), w.upper(), w.capitalize()}:
            out[h32(v)] = v
    return out


def load(game):
    for rel in (os.path.join('ModStudio', 'backup', 'attributes.bin'), os.path.join('GLOBAL', 'attributes.bin')):
        p = os.path.join(game, rel)
        if os.path.isfile(p):
            with open(p, 'rb') as f:
                return AttribDB(f.read()), p
    raise SystemExit('no attributes.bin under ' + game)


def floats(db, addrs):
    return [round(struct.unpack_from('<f', db.d, a)[0], 4) for a in addrs]


def main():
    game = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('MODSTUDIO_GAME_DIR', r'C:\Games\nfsmw')
    db, path = load(game)
    print('reading', path)
    cls_names = names_for(CLASS_WORDS)
    fld_names = names_for(FIELD_WORDS)
    cname = lambda c: db.names.get(c) or cls_names.get(c) or '%08x' % c
    fname = lambda f: db.names.get(f) or fld_names.get(f) or '%08x' % f
    print('\n== every class ==')
    hits = []
    for c in sorted(db.classes, key=cname):
        colls = [db.name(k) for k in db.collections_of(c)]
        defs = db.classdefs(c)
        fields = [fname(f) for f in defs]
        text = ' '.join([cname(c)] + colls + fields).lower()
        flag = any(hint in text for hint in HINTS)
        print('%-3s %-20s %3d collections %3d fields  e.g. %s' % ('*' if flag else '', cname(c), len(colls), len(defs),
                                                                  ', '.join(colls[:8])))
        if flag:
            hits.append(c)
    print('\n== camera-like classes in detail ==')
    for c in hits:
        defs = db.classdefs(c)
        if not any(h in ' '.join([cname(c)] + [db.name(k) for k in db.collections_of(c)]).lower()
                   for h in ('camera', 'close', 'bumper', 'hood', 'shake', 'far', 'chase')):
            continue
        print('\nclass %s (%08x)' % (cname(c), c))
        for f, (typ, off, size, cnt, fl) in sorted(defs.items(), key=lambda x: x[1][1]):
            print('  field %-22s type %08x off %3d size %2d count %d flags %d' % (fname(f), typ, off, size, cnt, fl))
        for k in sorted(db.collections_of(c), key=lambda k: db.coll(c, k)['off']):
            co = db.coll(c, k)
            row = []
            for f in sorted(defs, key=lambda f: defs[f][1]):
                a = db.field_addrs(c, k, f)
                if a and defs[f][2] in (4, 8, 12, 16):
                    row.append('%s=%s' % (fname(f), floats(db, a)))
            print('  %-14s parent %-12s %s' % (db.name(k), db.name(co['parent']) if co['parent'] else '-', ' '.join(row)))
    code_route(game)
    summary()


def code_route(game):
    import hooks
    from gamefiles import _pe_reader
    with open(os.path.join(game, 'speed.exe'), 'rb') as f:
        data = f.read()
    u32 = _pe_reader(data)
    f32 = lambda va: struct.unpack('<f', struct.pack('<I', u32(va)))[0]
    print('\n== code route: speed.exe v1.3 ==')
    ok = True
    for name, slot, fname, fn in hooks.COPFLY_SLOTS + hooks.CAMERA_SLOTS:
        got = u32(slot)
        ok &= got == fn
        print('  %-22s slot 0x%06X holds 0x%06X, expected %s 0x%06X  %s' % (name, slot, got or 0, fname, fn,
                                                                            'ok' if got == fn else 'MISMATCH'))
    for name, site, fname, fn in hooks.CAMERA_CALLS:
        got = hooks.call_target(u32, site)
        ok &= got == fn
        print('  %-22s call at 0x%06X -> 0x%06X, expected %s 0x%06X  %s' % (name, site, got or 0, fname, fn,
                                                                            'ok' if got == fn else 'MISMATCH'))
    print('  speed blend 1/[0x895078] = %.1f m/s' % (1 / f32(0x895078)))
    print('  engine angle units per turn [0x893348] = %.0f (FOV word = degrees * 65536 / 360)' % f32(0x893348))
    print('  shake scales per camera mode: speed %s, extra %s, nearby %s' % (
        [f32(0x8EDE1C + 4 * i) for i in range(7)], [f32(0x8EDE38 + 4 * i) for i in range(7)],
        [f32(0x8EDE00 + 4 * i) for i in range(7)]))
    try:
        import capstone
    except ImportError:
        print('  (pip install capstone to see the instructions around each site)')
        return ok
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    opt = struct.unpack_from('<H', data, pe + 20)[0]
    base = struct.unpack_from('<I', data, pe + 24 + 28)[0]
    secs = [struct.unpack_from('<IIII', data, pe + 24 + opt + 40 * i + 8)
            for i in range(struct.unpack_from('<H', data, pe + 6)[0])]

    def raw(va, n):
        for vs, rva, rs, ro in secs:
            if base + rva <= va < base + rva + rs:
                return data[va - base - rva + ro:va - base - rva + ro + n]
        return b''
    for name, site, fname, fn in hooks.CAMERA_CALLS:
        print('  %s:' % name)
        for i in md.disasm(raw(site - 12, 30), site - 12):
            print('    %08x  %-16s %s %s%s' % (i.address, i.bytes.hex(), i.mnemonic, i.op_str,
                                            '   <- hook' if i.address == site else ''))
    return ok


def summary():
    print('''
== findings ==
FOV that widens with speed: ASI.
  camerainfo has FOV pairs, but the pair index is a screen-mode switch (speed.exe 0x4713C0 picks [1] when
  [0x982B3C] == 3), not speed. The chase mover (CubicCameraMover::Update 0x47D3C0) eases its FOV in engine
  angle units (65536 = 360 deg) and converts it at 0x47DC58 (call _ftol) before writing the Camera FOV word
  (+0xC4). Adding the extra before that conversion stacks on the game's FOV, its nitro FOV and the Widescreen
  Fix (which only rescales the projection, 0x6CF4EA). Speed = camera anchor +0x10 (m/s).
Shake removal: ASI.
  The speed shake is a hard-coded curve (0x8EDFB0, 0-80 m/s) plus nitro/terrain extras that feed
  Camera::ApplyNoise (0x467420, intensity is linear). Only the per-surface part is in the data (simsurface
  0xF0C9E498), so the plugin scales the intensity at the three ApplyNoise calls of the gameplay mover.
Smoother chase cam: ASI.
  The follow smoothing is hard-coded keyframes (0x8ED460, per mode), not camerainfo. The plugin low-passes the
  camera offset (eye minus target) passed to eCreateLookAtMatrix (call at 0x47DCBC), only in chase modes (2-6),
  with a small maximum deviation and the game's own distance kept.
''')


if __name__ == '__main__':
    main()
