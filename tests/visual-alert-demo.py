#!/usr/bin/env python3
"""Visual demo of all qLine alert states. Run in terminal to see colors."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

if 'NO_COLOR' in os.environ:
    del os.environ['NO_COLOR']

from statusline import render_context_bar, load_config, _alert_state

theme = load_config()

alerts = [
    ('CACHE BUSTED',   {'cache_busting': True, 'sys_overhead_source': 'measured', 'sys_overhead_tokens': 38200, 'cache_hit_rate': 0.12}),
    ('CACHE EXPIRED',  {'cache_expired': True, 'sys_overhead_source': 'measured', 'sys_overhead_tokens': 38200, 'cache_hit_rate': 0.95}),
    ('MICROCOMPACT',   {'microcompact_suspected': True, 'sys_overhead_source': 'measured', 'sys_overhead_tokens': 38200, 'cache_hit_rate': 0.88}),
    ('SYS BLOAT',      {'sys_overhead_tokens': 600000, 'sys_overhead_source': 'measured', 'cache_hit_rate': 0.97}),
    ('HEAVY CONTEXT',  {}),
    ('COMPACT IN ~8',  {'turns_until_compact': 8}),
    ('~35 TURNS LEFT', {'turns_until_compact': 35}),
    ('CACHE DEGRADED', {'cache_degraded': True, 'sys_overhead_source': 'measured', 'sys_overhead_tokens': 38200, 'cache_hit_rate': 0.55}),
    ('HEALTHY',        {}),
]

for label, extra in alerts:
    _alert_state.clear()
    is_heavy = label == 'HEAVY CONTEXT'
    state = {
        'context_used': 980000 if is_heavy else 350000,
        'context_total': 1000000,
        'context_used_corrected': 980000 if is_heavy else 350000,
        'input_tokens': 1100000, 'output_tokens': 219000,
        'last_cache_create': 521,
        **extra,
    }
    bar = render_context_bar(state, theme)
    banner = state.get('_alert_banner')

    print(f'\033[1;37m━━━ {label} ━━━\033[0m')
    print(bar)
    if banner:
        print(banner)
    print()
