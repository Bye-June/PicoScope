"""
raw 데이터 CSV 저장 검증 스크립트
"""
import numpy as np
import os
from datetime import datetime
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

# ── raw 데이터 CSV 저장 ──────────────────────────────────────
raw = seq.last_capture
sr  = ps.sample_rate_hz
active_chs = sorted(raw.keys())
n = max(len(raw[ch]) for ch in active_chs)
t_us = np.arange(n) / sr * 1e6

header = 'time_us,' + ','.join(f'Ch{ch}_V' for ch in active_chs)
cols = [t_us]
for ch in active_chs:
    v = raw[ch]
    if len(v) < n:
        v = np.pad(v, (0, n - len(v)), constant_values=np.nan)
    cols.append(v[:n])
matrix = np.column_stack(cols)

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
save_dir = os.path.join('results', datetime.now().strftime('%Y%m%d'))
os.makedirs(save_dir, exist_ok=True)
csv_path = os.path.join(save_dir, f'MANUAL_{timestamp}_raw.csv')
np.savetxt(csv_path, matrix, delimiter=',', header=header, comments='', fmt='%.4f')

ps.close()

# ── 검증 ────────────────────────────────────────────────────
print(f'\n=== raw 데이터 저장 검증 ===')
print(f'저장 경로: {os.path.abspath(csv_path)}')
print(f'파일 크기: {os.path.getsize(csv_path):,} bytes')

# 파일 읽어서 내용 확인
loaded = np.loadtxt(csv_path, delimiter=',', skiprows=1)
print(f'행 수 (샘플 수): {loaded.shape[0]:,}')
print(f'열 수           : {loaded.shape[1]} ({", ".join(["time_us"] + [f"Ch{ch}_V" for ch in active_chs])})')

print(f'\n--- 첫 5행 ---')
with open(csv_path, encoding='utf-8') as f:
    for i, line in enumerate(f):
        print(line.rstrip())
        if i >= 5:
            break

print(f'\n--- 시간축 검증 ---')
t_col = loaded[:, 0]
dt_us = np.diff(t_col)
print(f'시작 시간    : {t_col[0]:.4f} µs')
print(f'끝 시간      : {t_col[-1]:.2f} µs  ({t_col[-1]/1000:.3f} ms)')
print(f'샘플 간격    : {dt_us.mean():.4f} µs  (기대값: {1/sr*1e6:.4f} µs)')
print(f'샘플 간격 일정: {np.allclose(dt_us, dt_us[0], rtol=1e-6)}')

print(f'\n--- 채널별 전압 범위 ---')
for i, ch in enumerate(active_chs):
    v_col = loaded[:, i+1]
    print(f'Ch {ch}: min={v_col.min():.3f}V  max={v_col.max():.3f}V  mean={v_col.mean():.3f}V')
