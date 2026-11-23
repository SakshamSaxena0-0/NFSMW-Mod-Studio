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

CAMERA_SETTINGS = [
    Setting('FovMaxExtra', 'Extra FOV at full speed', 12.0, 0, 30, 0.5, 'float',
            'How many degrees wider the view gets at full speed. 0 = no change.',
            'extra field of view in degrees at full speed (0 to 30)'),
    Setting('FovStartSpeed', 'Widening starts at', 15.0, 0, 100, 1, 'float',
            'Speed in m/s where the view starts to widen (15 = 54 km/h).',
            'speed in m/s where the widening starts (15 = 54 km/h)'),
    Setting('FovFullSpeed', 'Full widening at', 70.0, 1, 150, 1, 'float',
            'Speed in m/s where the view is at its widest (70 = 252 km/h).',
            'speed in m/s where it reaches FovMaxExtra (70 = 252 km/h)'),
    Setting('FovResponse', 'Response time', 0.35, 0.02, 5, 0.01, 'float',
            'Seconds the view takes to follow a speed change. Lower = snappier, higher = smoother.',
            'seconds the field of view takes to follow a speed change (0.02 to 5)'),
    Setting('SmoothAmount', 'Smoothing', 0.5, 0, 1, 0.05, 'float',
            'How much the chase camera is smoothed. 0 = stock, 1 = the most (still light, it never strays far from '
            'the stock camera).',
            '0 = stock follow, 1 = the most smoothing (it never strays far from the stock camera)'),
    Setting('ShakeScale', 'Shake amount', 0.0, 0, 1, 0.05, 'float',
            'All camera shake of the driving views (at speed, with nitro, on rough roads). 0 = none, 1 = stock.',
            'camera shake: 0 = none, 1 = stock'),
    Setting('Log', 'Write a camera log', 0, 0, 1, 1, 'bool',
            'Adds camera lines to NFSMWCopFly.log every 2 seconds while you drive. Only for testing.',
            '1 = add camera lines to NFSMWCopFly.log (for testing)'),
]
CAMERA_DEFAULTS = {s.key: s.default for s in CAMERA_SETTINGS}
CAMERA_SETTING = {s.key: s for s in CAMERA_SETTINGS}


def _fmt(s, v):
    if s.kind in ('int', 'bool'):
        return str(int(round(float(v))))
    return ('%.2f' % float(v)).rstrip('0').rstrip('.')


def camera_text(camera=None):
    camera = camera or {}
    v = dict(CAMERA_DEFAULTS, **(camera.get('settings') or {}))
    lines = ['', '[Camera]',
             '; Camera tweaks for the driving views (chase, bumper and hood). Both are off by default.',
             ('FovSpeed = %d' % bool(camera.get('fov_speed'))).ljust(21) + '; 1 = the field of view widens as you go faster']
    lines += [('%s = %s' % (s.key, _fmt(s, v[s.key]))).ljust(21) + '; ' + s.comment for s in CAMERA_SETTINGS[:4]]
    lines.append(('SmoothCam = %d' % bool(camera.get('smooth'))).ljust(21) + '; 1 = smoother chase camera and less shake')
    lines += [('%s = %s' % (s.key, _fmt(s, v[s.key]))).ljust(21) + '; ' + s.comment for s in CAMERA_SETTINGS[4:]]
    return '\n'.join(lines) + '\n'


def ini_text(values, launch=True, keep=None, camera=None):
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
    return '\n'.join(lines) + '\n' + camera_text(camera)
