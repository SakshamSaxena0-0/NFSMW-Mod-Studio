COPFLY_SLOTS = [
    ('COP_SLOT', 0x8AD460, 'COP_IMPACT', 0x69CA30),
    ('DV_SLOT', 0x8AD2F4, 'DV_IMPACT', 0x69C030),
    ('RACER_SLOT', 0x8AD378, 'DV_IMPACT', 0x69C030),
    ('RBCOP_SLOT', 0x8AD020, 'RBCOP_SIM', 0x68BC80),
    ('RBVEH_SLOT', 0x8AC950, 'RBCOP_SIM', 0x68BC80),
]

CAMERA_SLOTS = [
    ('CAM_UPDATE_SLOT', 0x894CD0, 'CAM_UPDATE', 0x47D3C0),
]

CAMERA_CALLS = [
    ('CAM_FOV_CALL', 0x47DC58, 'CAM_FTOL', 0x7C4B80),
    ('CAM_LOOKAT_CALL', 0x47DCBC, 'CAM_LOOKAT', 0x6CF0A0),
    ('CAM_SHAKE_CALL', 0x47C231, 'CAM_NOISE', 0x467420),
    ('CAM_NEAR_SHAKE_CALL', 0x470BC0, 'CAM_NOISE', 0x467420),
    ('CAM_EVENT_SHAKE_CALL', 0x468946, 'CAM_NOISE', 0x467420),
]


def call_target(u32, site):
    first = u32(site)
    rel = u32(site + 1)
    if first is None or rel is None or first & 0xFF != 0xE8:
        return None
    if rel & 0x80000000:
        rel -= 1 << 32
    return (site + 5 + rel) & 0xFFFFFFFF


def header():
    lines = ['#pragma once']
    seen = set()
    for slots in (COPFLY_SLOTS, CAMERA_SLOTS):
        for name, slot, fname, fn in slots:
            lines.append('#define %s ((void **)0x%08X)' % (name, slot))
            if fname not in seen:
                seen.add(fname)
                lines.append('#define %s_ADDR 0x%08X' % (fname, fn))
    for name, site, fname, fn in CAMERA_CALLS:
        lines.append('#define %s ((unsigned char *)0x%08X)' % (name, site))
        if fname not in seen:
            seen.add(fname)
            lines.append('#define %s_ADDR 0x%08X' % (fname, fn))
    return '\n'.join(lines) + '\n'
