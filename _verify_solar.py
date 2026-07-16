import ast, sys
sys.path.insert(0, '.')

src = open('app.py', encoding='utf-8').read()
ast.parse(src)
print("syntax OK")

checks = [
    ('_render_solar_section defined', 'def _render_solar_section()'),
    ('main() calls solar section',    '_render_solar_section()'),
    ('Generate Solar Layout button',  'Generate Solar Layout'),
    ('build_solar_preview_figure',    'build_solar_preview_figure'),
    ('build_summary_table',           'build_summary_table'),
    ('st.pyplot solar fig',           'st.pyplot(solar_fig'),
    ('Full Engineering Summary',      'Full Engineering Summary'),
    ('Download Solar DXF button',     'Download Solar DXF'),
    ('Download JSON Report button',   'Download JSON Report'),
]

all_ok = True
for name, token in checks:
    found = token in src
    print(('OK  ' if found else 'FAIL') + '  ' + name)
    all_ok = all_ok and found

print()
from solar_layout.panel_renderer import draw_panels_on_axes, draw_usable_boundary_on_axes
print("OK    panel_renderer imports")
from solar_layout.plot_integration import build_solar_preview_figure, build_summary_table
print("OK    plot_integration imports")
from solar_layout import SOLAR_MODULE_ENABLED
print("OK    SOLAR_MODULE_ENABLED =", SOLAR_MODULE_ENABLED)

print()
print("ALL CHECKS PASSED" if all_ok else "SOME CHECKS FAILED")
