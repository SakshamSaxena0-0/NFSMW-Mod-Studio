import copfly_cfg
import tuning as T

BUILTIN_PROFILES = [
    ('Full Mod Pack', 'Everything from the reels: Cayman S and Corvette C6 maxed out, BMW M3 GTR beast, flying '
                      'Porsche 911 GT2, Gallardo buff, Supra drift setup, unlimited nitro, tougher cops, '
                      'spike-proof tires, heat 10 and CopFly.'),
    ('Clean Game', 'Everything off: stock cars, no nitro or police changes, CopFly removed. '
                   'Heat settings are left as they are.'),
]


def builtin_profile(name):
    cfg = T.default_config()
    if name == 'Full Mod Pack':
        for car, preset in (('caymans', 'Cayman Max'), ('corvette', 'Cayman Max'), ('911gt2', 'GT2 Fly'),
                            ('bmwm3gtre46', 'BMW GTR Beast'), ('bmwm3gtr', 'BMW GTR Beast'),
                            ('gallardo', 'Gallardo Buff'), ('supra', 'Supra Drift')):
            cfg['cars'][car] = {'enabled': True, 'knobs': dict(T.PRESETS[preset]),
                                'nitro': preset in T.PRESET_NITRO}
        cfg['police'] = {'enabled': True, 'knobs': dict(T.PRESETS['Harder Cops']), 'no_puncture': True}
        cfg['heat'] = {'override': True, 'min': 1, 'max': 10, 'action_mode': True}
        cfg['copfly'] = {'installed': True, 'settings': dict(copfly_cfg.DEFAULTS)}
    return cfg
