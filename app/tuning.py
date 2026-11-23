import copy
import math
import struct

from copfly_cfg import CAMERA_SETTING
from vltdb import AttribDB, h32

PVEHICLE = h32('pvehicle')
TUNED_CLASSES = ('engine', 'transmission', 'tires', 'chassis', 'brakes')


class Knob:

    def __init__(self, key, label, help, lo, hi, effects, advanced=False):
        self.key, self.label, self.help, self.lo, self.hi = key, label, help, lo, hi
        self.effects, self.advanced = effects, advanced


GRIP_FIELDS = ('GRIP_SCALE', 'DYNAMIC_GRIP', 'STATIC_GRIP')
KNOBS = [
    Knob('power', 'Engine power', 'Torque multiplier. More = harder acceleration.', 0.5, 50,
         [('engine', 'TORQUE', 'mul')]),
    Knob('gearing', 'Top-speed gearing', 'Taller final drive: more top speed, softer pull per gear.', 0.5, 5,
         [('transmission', 'FINAL_GEAR', 'inv')]),
    Knob('drag', 'Low drag', 'Divides air drag so the car can reach the extra top speed.', 0.5, 10,
         [('chassis', 'DRAG_COEFFICIENT', 'inv')]),
    Knob('grip', 'Tire grip', 'Grip of all four tires.', 0.2, 8,
         [('tires', f, 'mul') for f in GRIP_FIELDS]),
    Knob('brakes', 'Brakes', 'Brake force.', 0.2, 20, [('brakes', 'BRAKES', 'mul')]),
    Knob('downforce', 'Downforce', 'Grows with speed. NEGATIVE = lift: the car gets light and takes off '
         '(the GT2 Fly preset uses -300, type it in the box).', -20, 5,
         [('chassis', 'AERO_COEFFICIENT', 'mul')]),
    Knob('suspension', 'Suspension stiffness', 'Springs and shocks.', 0.3, 4,
         [('chassis', f, 'mul') for f in ('SPRING_STIFFNESS', 'SHOCK_STIFFNESS', 'SHOCK_EXT_STIFFNESS')]),
    Knob('damping', 'Shock damping', 'The shock absorbers only, not the springs. More = the car settles after a bump '
         'instead of bouncing.', 0.3, 4,
         [('chassis', f, 'mul') for f in ('SHOCK_STIFFNESS', 'SHOCK_EXT_STIFFNESS')], advanced=True),
    Knob('travel', 'Suspension travel', 'Ride height and suspension travel together. More = the car does not bottom '
         'out over bumps at high speed (it sits a little higher).', 0.5, 2,
         [('chassis', f, 'mul') for f in ('RIDE_HEIGHT', 'TRAVEL')], advanced=True),
    Knob('rear_grip', 'Rear grip balance', 'Below 1 = the rear breaks loose first (drift). Above 1 = more stable.',
         0.3, 2, [('tires', f, 'rear') for f in GRIP_FIELDS], advanced=True),
    Knob('shift', 'Gear-shift speed', 'How fast gear changes are. 5 = five times quicker.', 0.5, 10,
         [('transmission', 'SHIFT_SPEED', 'inv')], advanced=True),
    Knob('handbrake', 'Handbrake', 'Handbrake (e-brake) strength. A car without one gets a typical handbrake.', 0.2, 5, [('brakes', 'EBRAKE', 'mul')],
         advanced=True),
    Knob('steering', 'Steering lock', 'Maximum steering angle.', 0.5, 2, [('tires', 'STEERING', 'mul')],
         advanced=True),
    Knob('stability', 'Stability assist', 'Lower = slides are not straightened out (drift). A car without any gets '
         'the typical amount.', 0.0, 3,
         [('tires', 'YAW_CONTROL', 'mul')], advanced=True),
    Knob('turn_in', 'Turn-in speed', 'How quickly the car rotates into a corner or a drift.', 0.5, 3,
         [('tires', 'YAW_SPEED', 'mul')], advanced=True),
]
KNOB = {k.key: k for k in KNOBS}

PRESETS = {
    'Stock': {},
    'Cayman Max': dict(power=20, gearing=4, drag=10, grip=4, brakes=15, downforce=1.5, suspension=2,
                       shift=5, handbrake=3, steering=1.2),
    'BMW GTR Beast': dict(power=8, gearing=3, drag=6, grip=5, brakes=12, downforce=1.0, suspension=1.7),
    'GT2 Fly': dict(power=50, gearing=3, drag=6, grip=6, brakes=5, downforce=-300, suspension=1.0),
    'Gallardo Buff': dict(power=5, gearing=2, drag=2.5, grip=4, brakes=5, downforce=2, suspension=1.25),
    'Supra Drift': dict(power=1.6, grip=1.1, rear_grip=0.75, stability=0.4, turn_in=1.4, steering=1.3,
                        handbrake=1.5),
    'Harder Cops': dict(power=4, gearing=2, drag=2, grip=2, brakes=2.5, downforce=1.5, suspension=1.3),
    'RB19 Rocket': dict(power=10, gearing=1.42, drag=4, grip=3, rear_grip=1.2, brakes=6, downforce=1.5, suspension=1.5,
                        damping=1.4, travel=1.4, shift=2, handbrake=1.5, stability=1.5),
}
PRESET_NITRO = {'Cayman Max', 'BMW GTR Beast', 'GT2 Fly', 'RB19 Rocket'}

CAR_NAMES = {
    'a3': 'Audi A3 3.2 quattro', 'a4': 'Audi A4 3.2 FSI quattro', 'tt': 'Audi TT 3.2 quattro',
    'db9': 'Aston Martin DB9', 'bmwm3gtre46': 'BMW M3 GTR', 'bmwm3gtr': 'BMW M3 GTR (race)',
    'm3gtre46careerstart': 'BMW M3 GTR (prologue)', 'cts': 'Cadillac CTS', 'camaro': 'Chevrolet Camaro SS',
    'cobaltss': 'Chevrolet Cobalt SS', 'corvette': 'Chevrolet Corvette C6', 'corvettec6r': 'Chevrolet Corvette C6.R',
    'viper': 'Dodge Viper SRT-10', 'punto': 'Fiat Punto', 'fordgt': 'Ford GT', 'mustanggt': 'Ford Mustang GT',
    'gallardo': 'Lamborghini Gallardo', 'murcielago': 'Lamborghini Murcielago', 'is300': 'Lexus IS 300',
    'elise': 'Lotus Elise', 'rx7': 'Mazda RX-7', 'rx8': 'Mazda RX-8', 'clk500': 'Mercedes-Benz CLK 500',
    'sl500': 'Mercedes-Benz SL 500', 'sl65': 'Mercedes-Benz SL 65 AMG', 'slr': 'Mercedes-Benz SLR McLaren',
    'eclipsegt': 'Mitsubishi Eclipse GT', 'lancerevo8': 'Mitsubishi Lancer Evolution VIII', 'gto': 'Pontiac GTO',
    '911gt2': 'Porsche 911 GT2', '997s': 'Porsche 911 Carrera S', '911turbo': 'Porsche 911 Turbo S',
    'carreragt': 'Porsche Carrera GT', 'caymans': 'Porsche Cayman S', 'clio': 'Renault Clio V6',
    'imprezawrx': 'Subaru Impreza WRX STi', 'supra': 'Toyota Supra', 'monaro': 'Vauxhall Monaro VXR',
    'gti': 'Volkswagen Golf GTI',
}
HIDDEN_PREFIXES = ('cs_', 'speedtest', 'rx8speedt', 'wrx_demo', 'mustang_demo')

NOS_FIELDS = ('NOS_CAPACITY', 'TORQUE_BOOST', 'FLOW_RATE', 'RECHARGE_MIN', 'RECHARGE_MAX',
              'RECHARGE_MIN_SPEED', 'RECHARGE_MAX_SPEED', 'NOS_DISENGAGE')
PREFERRED_NOS_SLOT = 0xDCE9738A
PREFERRED_NOS_SIBLING = 'bmwm3gtr'


KEEP_KINDS = ('cops', 'traffic', 'walls')
LIGHT_PROP_MASS = 700.0
PROP_MASS_SCALE = 0.05
PROP_KEEP = {'spikestrip'}


def default_config():
    return {
        'version': 1,
        'cars': {},
        'police': {'enabled': False, 'knobs': {}, 'no_puncture': False},
        'world': {'no_stopping': False, 'keep_cops': False, 'keep_traffic': False, 'keep_walls': False},
        'nitro': {'boost': 3.0, 'all_racers': False},
        'heat': None,
        'copfly': {'installed': False, 'settings': {}},
        'camera': {'fov_speed': False, 'smooth': False, 'settings': {}},
    }


def _flag(v):
    return v is True or (type(v) in (int, float) and v == 1)


def camera_config(cam):
    cam = cam if isinstance(cam, dict) else {}
    out = {'fov_speed': _flag(cam.get('fov_speed')), 'smooth': _flag(cam.get('smooth')), 'settings': {}}
    settings = cam.get('settings')
    for key, v in (settings.items() if isinstance(settings, dict) else ()):
        s = CAMERA_SETTING.get(key)
        if s is None or type(v) not in (bool, int, float) or not math.isfinite(v):
            continue
        v = min(max(float(v), s.lo), s.hi)
        out['settings'][key] = int(round(v)) if s.kind == 'bool' else v
    st = out['settings']
    start = st.get('FovStartSpeed', CAMERA_SETTING['FovStartSpeed'].default)
    if st.get('FovFullSpeed', CAMERA_SETTING['FovFullSpeed'].default) < start + 1:
        st['FovFullSpeed'] = start + 1
    return out


def normalize(cfg):
    out = default_config()
    for k, v in (cfg or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != 'cars':
            out[k].update(copy.deepcopy(v))
        else:
            out[k] = copy.deepcopy(v)
    if 'keep_speed' in out['world']:
        old = bool(out['world'].pop('keep_speed'))
        out['world']['keep_cops'] = out['world']['keep_cops'] or old
        out['world']['keep_traffic'] = out['world']['keep_traffic'] or old
    out['camera'] = camera_config(out.get('camera'))
    return out


def chain(db, key):
    out = []
    while key and db.has(PVEHICLE, key) and key not in out:
        out.append(key)
        key = db.coll(PVEHICLE, key)['parent']
    return out


def class_refs(db, vehicle, cls):
    for k in chain(db, vehicle):
        e = db.coll(PVEHICLE, k)['entries'].get(h32(cls))
        if e is not None:
            return db.refs(e)
    return []


def player_cars(db):
    racers = h32('racers')
    out = []
    for key in sorted(db.collections_of(PVEHICLE), key=lambda k: db.coll(PVEHICLE, k)['off']):
        name = db.name(key)
        if name.startswith(HIDDEN_PREFIXES) or key == racers:
            continue
        if racers not in chain(db, key)[1:]:
            continue
        if not class_refs(db, key, 'engine'):
            continue
        out.append((name, CAR_NAMES.get(name, name)))
    return out


def cop_vehicles(db):
    cops = h32('cops')
    return [k for k in db.collections_of(PVEHICLE)
            if cops in chain(db, k) and not db.name(k).startswith('cs_') and '_nis' not in db.name(k)]


VEHICLE_GROUPS = {'default', 'cars', 'racers', 'cops', 'traffic', 'tractors', 'truck', 'van', 'street',
                  'challenge_traffic', 'choppers', 'trailers'}
VEHICLE_NAMES = {
    'semi': 'Semi truck', 'semia': 'Semi truck (trailer A)', 'semib': 'Semi truck (trailer B)',
    'semicmt': 'Cement truck (semi)', 'semicon': 'Container truck (semi)', 'semicrate': 'Crate truck (semi)',
    'semilog': 'Log truck (semi)', 'trafamb': 'Ambulance', 'traffire': 'Fire truck', 'trafgarb': 'Garbage truck',
    'trafcemtr': 'Cement mixer', 'trafdmptr': 'Dump truck', 'trafnews': 'News van', 'trafpizza': 'Pizza car',
    'traftaxi': 'Taxi', 'trafminivan': 'Minivan', 'trafpickupa': 'Pickup truck', 'trafsuva': 'SUV',
    'trafcamper': 'Camper', 'trafstwag': 'Station wagon', 'copmidsize': 'Police Ford Crown Victoria',
    'copgto': 'Police Pontiac GTO', 'copsport': 'Police Chevrolet Corvette', 'copcross': "Cross's Corvette",
    'copghost': 'Undercover Ford Crown Victoria', 'copgtoghost': 'Undercover Pontiac GTO',
    'copsportghost': 'Undercover Chevrolet Corvette',
}


def other_vehicles(db):
    cars, racers = h32('cars'), {n for n, _ in player_cars(db)}
    out = []
    for key in sorted(db.collections_of(PVEHICLE), key=lambda k: db.coll(PVEHICLE, k)['off']):
        name = db.name(key)
        if name in racers or name in VEHICLE_GROUPS or name.startswith(HIDDEN_PREFIXES) or '_nis' in name:
            continue
        if cars in chain(db, key) and class_refs(db, key, 'engine'):
            out.append(name)
    return out


def shared_vehicles(db, name):
    mine = car_targets(db, name)
    return [n for n in other_vehicles(db) if n != name and car_targets(db, n) & mine]


def car_targets(db, name):
    return {(cls, k) for cls in TUNED_CLASSES for k in class_refs(db, h32(name), cls)}


def shared_with(db, name, cars):
    mine = car_targets(db, name)
    return [n for n, _ in cars if n != name and car_targets(db, n) & mine]


def unlimited_slot(db):
    nos = h32('nos')
    used = set()
    for k in db.collections_of(PVEHICLE):
        e = db.coll(PVEHICLE, k)['entries'].get(nos)
        if e is not None:
            used |= set(db.refs(e))
    free = [k for k in db.collections_of(nos) if k not in used]
    if PREFERRED_NOS_SLOT in free:
        return PREFERRED_NOS_SLOT
    return free[0] if free else None


def nitro_route(db, name):
    nos = h32('nos')
    key = h32(name)
    if not db.has(PVEHICLE, key):
        return None, 'car not found'
    c = db.coll(PVEHICLE, key)
    if nos in c['entries']:
        return 'own', None
    own = set(c['entries'])
    order = lambda k: (db.name(k) != PREFERRED_NOS_SIBLING, db.coll(PVEHICLE, k)['off'])
    for k in sorted(db.collections_of(PVEHICLE), key=order):
        v = db.coll(PVEHICLE, k)
        if (v['parent'] == c['parent'] and v['off'] < c['off'] and nos in v['entries']
                and set(v['entries']) - own == {nos}):
            return 'via', db.name(k)
    return None, 'not possible for this car (use "Unlimited nitro for every racer" instead)'


def _typical(db, cls, field, n, cache):
    key = (cls, field, n)
    if key not in cache:
        rows = []
        for car, _ in player_cars(db):
            refs = class_refs(db, h32(car), cls)
            addrs = db.field_addrs(h32(cls), refs[0], h32(field)) if refs else None
            if addrs and len(addrs) == n:
                v = [struct.unpack_from('<f', db.d, a)[0] for a in addrs]
                if any(v):
                    rows.append(v)
        cache[key] = [sum(c) / len(rows) for c in zip(*rows)] if rows else None
    return cache[key]


def _knob_mults(knobs):
    out = {}
    for key, value in knobs.items():
        knob = KNOB.get(key)
        if knob is None or value is None:
            continue
        value = float(value)
        if value == 1.0:
            continue
        for cls, field, how in knob.effects:
            m_all, m_rear = out.get((cls, field), (1.0, 1.0))
            if how == 'mul':
                m_all *= value
            elif how == 'inv':
                m_all /= value if value else 1e-6
            elif how == 'rear':
                m_rear *= value
            out[(cls, field)] = (m_all, m_rear)
    return out


def apply_config(db, cfg, log=print):
    cfg = normalize(cfg)
    buf = bytearray(db.d)
    stats = dict(fields=0, cars=0, nitro=[], skipped=[], edits=[])
    edits = stats['edits']

    typical = {}

    def tune(label, targets, knobs, owner):
        mults = _knob_mults(knobs)
        if not mults:
            return
        for cls, coll_key in sorted(targets):
            if (cls, coll_key) in owner:
                msg = '%s shares its %s data with %s, so it keeps %s\'s tune' % (
                    label, cls, owner[(cls, coll_key)], owner[(cls, coll_key)])
                if msg not in stats['skipped']:
                    stats['skipped'].append(msg)
                continue
            owner[(cls, coll_key)] = label
            for (fcls, field), (m_all, m_rear) in mults.items():
                if fcls != cls:
                    continue
                addrs = db.field_addrs(h32(cls), coll_key, h32(field))
                if not addrs:
                    continue
                base = [struct.unpack_from('<f', db.d, a)[0] for a in addrs]
                if not any(base) and m_all != 1.0:
                    base = _typical(db, cls, field, len(addrs), typical) or base
                for i, a in enumerate(addrs):
                    m = m_all * (m_rear if (i == 1 and len(addrs) == 2) else 1.0)
                    struct.pack_into('<f', buf, a, base[i] * m)
                stats['fields'] += 1
                edits.append(('field', h32(cls), coll_key, h32(field)))

    owner = {}
    for name, car in cfg['cars'].items():
        if car.get('enabled') and db.has(PVEHICLE, h32(name)):
            tune(name, car_targets(db, name), car.get('knobs', {}), owner)
            stats['cars'] += 1
    if cfg['police'].get('enabled'):
        targets = set()
        for v in cop_vehicles(db):
            targets |= {(cls, k) for cls in TUNED_CLASSES for k in class_refs(db, v, cls)}
        tune('police', targets, cfg['police'].get('knobs', {}), owner)

    nos = h32('nos')
    want = [n for n, c in cfg['cars'].items() if c.get('nitro')]
    boost = float(cfg['nitro'].get('boost', 3.0))
    values = dict(NOS_CAPACITY=10000.0,
                  TORQUE_BOOST=boost, FLOW_RATE=3.0, RECHARGE_MIN=50.0, RECHARGE_MAX=30.0,
                  RECHARGE_MIN_SPEED=50.0, RECHARGE_MAX_SPEED=100.0, NOS_DISENGAGE=2.0)
    defs = db.classdefs(nos)

    def write_nos(coll_key):
        lay = db.coll(nos, coll_key)['layout']
        for f, v in values.items():
            d = defs.get(h32(f))
            if d and lay is not None:
                struct.pack_into('<f', buf, db.B + lay + d[1], v)
                edits.append(('field', nos, coll_key, h32(f)))

    if want:
        slot = unlimited_slot(db)
        if slot is None:
            stats['skipped'].append('unlimited nitro: no free nitro slot in this attributes.bin')
            want = []
        else:
            write_nos(slot)
        give = {}
        for name in want:
            route, extra = nitro_route(db, name)
            if route == 'own':
                give[name] = None
            elif route == 'via':
                give[name] = extra
                give.setdefault(extra, None)
            else:
                stats['skipped'].append('%s nitro: %s' % (name, extra))
        for name, via in give.items():
            key = h32(name)
            if via is None:
                e = db.coll(PVEHICLE, key)['entries'][nos]
                for a in db.ref_slots(e):
                    struct.pack_into('<I', buf, a, slot)
                edits.append(('ref', key, nos))
            else:
                struct.pack_into('<I', buf, db.V + db.coll(PVEHICLE, key)['off'] + 8, h32(via))
                edits.append(('parent', key))
            stats['nitro'].append(name)
    if cfg['nitro'].get('all_racers'):
        e = None
        for k in chain(db, h32('racers')):
            e = db.coll(PVEHICLE, k)['entries'].get(nos)
            if e is not None:
                break
        for k in (db.refs(e) if e else []):
            write_nos(k)
        stats['nitro'].append('every racer')

    if cfg['police'].get('no_puncture'):
        f = h32('BEHAVIOR_MECHANIC_DAMAGE')
        try:
            src = db.coll(PVEHICLE, h32('default'))['entries'][f]['ptr']
            dst = db.coll(PVEHICLE, h32('racers'))['entries'][f]['ptr']
            ok = (struct.unpack_from('<I', db.d, db.B + dst + 8)[0] == h32('DamageRacer') and
                  struct.unpack_from('<I', db.d, db.B + src + 8)[0] == h32('DamageVehicle'))
        except (KeyError, TypeError):
            ok = False
        recs = _string_fixups(db, {src + 12, dst + 12}) if ok else {}
        if ok and len(recs) == 2:
            buf[db.B + dst:db.B + dst + 12] = db.d[db.B + src:db.B + src + 12]
            struct.pack_into('<I', buf, recs[dst + 12] + 8, struct.unpack_from('<I', db.d, recs[src + 12] + 8)[0])
            edits.append(('stringkey', h32('racers'), f))
        else:
            stats['skipped'].append('spike-proof tires: damage behaviour not found as expected, skipped')

    stats['props'] = 0
    if (cfg.get('world') or {}).get('no_stopping'):
        sm = h32('smackable')
        for k in db.collections_of(sm) if sm in db.classes else []:
            if db.name(k) in PROP_KEEP:
                continue
            m = db.field_addrs(sm, k, h32('MASS'))
            mass = struct.unpack_from('<f', db.d, m[0])[0] if m else 0.0
            if not 0.0 < mass <= LIGHT_PROP_MASS:
                continue
            struct.pack_into('<f', buf, m[0], mass * PROP_MASS_SCALE)
            edits.append(('field', sm, k, h32('MASS')))
            d = db.field_addrs(sm, k, h32('DETACH_FORCE'))
            if d and struct.unpack_from('<f', db.d, d[0])[0] > 1.0:
                struct.pack_into('<f', buf, d[0], 1.0)
                edits.append(('field', sm, k, h32('DETACH_FORCE')))
            stats['props'] += 1
    return bytes(buf), stats


def _string_fixups(db, offs):
    out = {}
    for p in range(db.ptr_start, db.ptr_end - 11, 12):
        off, typ = struct.unpack_from('<IH', db.d, p)
        if typ == 3 and off in offs:
            out[off] = p
    return out


def remove_mods(cur, orig, cfg):
    mod_bytes, stats = apply_config(orig, cfg, log=lambda *a: None)
    mod = AttribDB(mod_bytes)
    buf = bytearray(cur.d)
    kept = 0
    for e in stats['edits']:
        kind = e[0]
        if kind == 'field':
            _, cls, key, field = e
            ao, ac = orig.field_addrs(cls, key, field), cur.field_addrs(cls, key, field)
            if not ac or len(ac) != len(ao) or [cur.d[a:a + 4] for a in ac] != [mod.d[a:a + 4] for a in ao]:
                kept += 1
                continue
            for a, b in zip(ac, ao):
                buf[a:a + 4] = orig.d[b:b + 4]
        elif kind == 'ref':
            _, key, entry = e
            ec = cur.coll(PVEHICLE, key)['entries'].get(entry) if cur.has(PVEHICLE, key) else None
            if (ec is None or ec['ptr'] is None
                    or cur.refs(ec) != mod.refs(mod.coll(PVEHICLE, key)['entries'][entry])):
                kept += 1
                continue
            for a, k in zip(cur.ref_slots(ec), orig.refs(orig.coll(PVEHICLE, key)['entries'][entry])):
                struct.pack_into('<I', buf, a, k)
        elif kind == 'parent':
            key = e[1]
            if not cur.has(PVEHICLE, key) or cur.coll(PVEHICLE, key)['parent'] != mod.coll(PVEHICLE, key)['parent']:
                kept += 1
                continue
            struct.pack_into('<I', buf, cur.V + cur.coll(PVEHICLE, key)['off'] + 8, orig.coll(PVEHICLE, key)['parent'])
        elif kind == 'stringkey':
            _, key, field = e
            po = orig.coll(PVEHICLE, key)['entries'][field]['ptr']
            pm = mod.coll(PVEHICLE, key)['entries'][field]['ptr']
            ec = cur.coll(PVEHICLE, key)['entries'].get(field) if cur.has(PVEHICLE, key) else None
            pc = ec['ptr'] if ec else None
            ro = _string_fixups(orig, {po + 12})
            rc = _string_fixups(cur, {pc + 12}) if pc is not None else {}
            text, at = b'', -1
            if po + 12 in ro:
                so = struct.unpack_from('<I', orig.d, ro[po + 12] + 8)[0]
                text = orig.d[orig.B + so:].split(b'\0', 1)[0]
                at = cur.d.find(b'\0' + text + b'\0', cur.B)
            if (pc is None or pc + 12 not in rc or not text or at < 0
                    or cur.d[cur.B + pc:cur.B + pc + 12] != mod.d[mod.B + pm:mod.B + pm + 12]):
                kept += 1
                continue
            buf[cur.B + pc:cur.B + pc + 12] = orig.d[orig.B + po:orig.B + po + 12]
            struct.pack_into('<I', buf, rc[pc + 12] + 8, at + 1 - cur.B)
    return bytes(buf), kept
