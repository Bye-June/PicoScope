from src.hw_picoscope import PicoScopeHardware
from src.test_sequence import TestSequencer

ps = PicoScopeHardware()
ps.open()
ps.setup_channel('B', enabled=True, range_str='10V', probe_str='x10')
ps.setup_channel('C', enabled=True, range_str='10V', probe_str='x10')
ps.setup_channel('D', enabled=True, range_str='10V', probe_str='x10')

config = {
    'B': {'mode': 'SENT', 'range': '10V', 'probe': 'x10'},
    'C': {'mode': 'SENT', 'range': '10V', 'probe': 'x10'},
    'D': {'mode': 'SPC (ID 1, 3)', 'range': '10V', 'probe': 'x10'},
}
seq = TestSequencer(ps)
results = seq.run_universal_test(config)
ps.close()

print('=== 최종 검사 결과 ===')
for ch, r in results.items():
    passed = r.get('pass', False)
    icon = 'PASS' if passed else 'FAIL'
    if ch in ['B', 'C']:
        ut = r.get('measured_ut_us', 0)
        print(f'  [{icon}] Ch {ch} SENT: UT={ut:.3f}us (기준 2.4~3.6us)')
    else:
        print(f'  [{icon}] Ch {ch} SPC:')
        for id_key, dr in r.get('details', {}).items():
            p = dr.get('pass', False)
            ut = dr.get('measured_ut_us')
            tw = dr.get('trigger_width_us')
            icon2 = 'PASS' if p else 'FAIL'
            ut_str = '{:.3f}us'.format(ut) if ut else 'N/A'
            tw_str = '{:.1f}us'.format(tw) if tw else 'N/A'
            print('         [{}] {}: UT={} (기준 2.6125~2.8875us), trigger={}'.format(icon2, id_key, ut_str, tw_str))
            msg = dr.get('message', '')
            if not p and msg:
                print('             -> ' + msg)
