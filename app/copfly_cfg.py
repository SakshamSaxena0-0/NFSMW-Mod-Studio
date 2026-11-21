class Setting:
    def __init__(self, key, label, default, lo, hi, step, kind, help, comment):
        self.key, self.label, self.default, self.lo, self.hi, self.step = key, label, default, lo, hi, step
        self.kind, self.help, self.comment = kind, help, comment


SETTINGS = [
    Setting('MinImpactSpeed', 'Minimum hit strength', 4.0, 0, 30, 0.5, 'float',
            'How hard the two cars must meet, in m/s of closing speed (4 = ~14 km/h). Gentle bumps do nothing.',
            'how hard the two cars must meet (m/s of closing speed; 4 = ~14 km/h). Gentle bumps do nothing'),
    Setting('MinPlayerSpeed', 'Your minimum speed', 5.0, 0, 30, 0.5, 'float',
            'You must be driving at least this fast, in m/s (5 = 18 km/h). Standing still never launches a cop.',
            'you must be driving at least this fast (m/s; 5 = 18 km/h). Standing still never launches a cop'),
    Setting('ContactMargin', 'Contact gap', 0.1, 0, 1, 0.05, 'float',
            'How close the two car bodies must get, in metres. Lower = must really touch. '
            'Raise to 0.2 if fast side-swipes do not trigger.',
            'contact tolerance in metres between the two car bodies. Lower = must touch more firmly'),
    Setting('UpSpeed', 'Launch height', 14.0, 0, 60, 1, 'float',
            'Upward throw in m/s for a full-speed hit (scaled down for softer hits).',
            'upward throw in m/s for a full-speed hit (scales down for softer hits). Higher = flies higher'),
    Setting('PushFactor', 'Carry your speed', 0.5, 0, 2, 0.05, 'float',
            'How much of your own speed the cop is thrown along with.',
            'how much of your own speed the cop is thrown along with'),
    Setting('ForwardKick', 'Push away', 5.0, 0, 40, 1, 'float',
            'Extra throw away from your car in m/s (side hit = sideways, front hit = forward).',
            'extra throw in m/s, away from your car (side hit = sideways, front hit = forward)'),
    Setting('Spin', 'Spin', 3.0, 0, 15, 0.5, 'float', 'How fast the cop tumbles in the air.',
            'how fast the cop tumbles'),
    Setting('Wreck', 'Wreck the cop', 0, 0, 1, 1, 'bool',
            'Also wreck the cop (smoke, fire, out of the chase). Off = it lands and keeps chasing.',
            '1 = the cop is also wrecked (smoke/fire, disabled), 0 = it lands and keeps chasing'),
    Setting('Log', 'Write a log file', 1, 0, 1, 1, 'bool', 'Writes contacts and launches to NFSMWCopFly.log.',
            'writes contacts and launches to NFSMWCopFly.log'),
]
DEFAULTS = {s.key: s.default for s in SETTINGS}


def _fmt(s, v):
    if s.kind in ('int', 'bool'):
        return str(int(round(float(v))))
    return ('%.2f' % float(v)).rstrip('0').rstrip('.')


def ini_text(values, launch=True, keep=None):
    keep = keep or {}
    v = dict(DEFAULTS, **(values or {}))
    lines = ['[CopFly]',
             '; NFSMW CopFly - hit a cop car with your car and it gets thrown into the air.',
             '; Only real contact counts: each car\'s own body box (its size and the way it faces) must touch',
             '; the cop\'s, so front, rear and side hits all work the same way and nothing happens from a distance.',
             'Enabled = 1          ; 0 turns the mod off',
             ('Launch = %d' % bool(launch)).ljust(21) + '; 1 = hitting a cop car throws it into the air',
             ('KeepSpeedCops = %d' % bool(keep.get('cops'))).ljust(21) + '; 1 = hitting cop cars does not slow you down',
             ('KeepSpeedTraffic = %d' % bool(keep.get('traffic'))).ljust(21) + '; 1 = hitting traffic (and other racers) does not slow you down',
             ('KeepSpeedWalls = %d' % bool(keep.get('walls'))).ljust(21) + '; 1 = you slide along walls at full speed (head-on hits still stop you)']
    for s in SETTINGS:
        lines.append(('%s = %s' % (s.key, _fmt(s, v[s.key]))).ljust(21) + '; ' + s.comment)
    lines.append('UpAxis = 1           ; physics up axis, leave at 1')
    return '\n'.join(lines) + '\n'
