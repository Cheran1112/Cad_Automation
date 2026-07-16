import sys
sys.path.insert(0, '.')

src = open('app.py', encoding='utf-8').read()

checks = [
    ('solar import block',          'from solar_layout import'),
    ('_SOLAR_AVAILABLE set True',   '_SOLAR_AVAILABLE = True'),
    ('solar session-state keys',    '_KEY_SOLAR_RESULT'),
    ('init_state includes solar',   '_KEY_SOLAR_DXF_NAME,'),
    ('_render_solar_section def',   'def _render_solar_section()'),
    ('guard _SOLAR_AVAILABLE',      'if not _SOLAR_AVAILABLE or not SOLAR_MODULE_ENABLED'),
    ('guard polyline check',        'if polyline is None or metrics is None'),
    ('section header',              '7 - Solar Layout Planning'),
    ('Run Solar Layout button',     'Run Solar Layout'),
    ('Download Solar DXF button',   'Download Solar DXF'),
    ('Download JSON button',        'Download JSON Report'),
    ('main() calls solar section',  '_render_solar_section()'),
]

all_ok = True
for name, token in checks:
    ok = token in src
    print(('OK  ' if ok else 'FAIL') + '  ' + name)
    if not ok:
        all_ok = False

print()

# Also verify the solar module itself imports cleanly under venv
try:
    from solar_layout import (
        SOLAR_MODULE_ENABLED, SpacingRules, run_solar_layout,
        build_solar_report, solar_report_to_json,
        apply_solar_overlay, save_solar_dxf, solar_dxf_to_bytes,
    )
    print('OK    solar_layout package imports cleanly')
    print('OK    SOLAR_MODULE_ENABLED =', SOLAR_MODULE_ENABLED)
except Exception as e:
    print('FAIL  solar_layout import error:', e)
    all_ok = False

print()
print('ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED')
