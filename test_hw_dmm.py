"""
test_hw_dmm.py — hw_dmm.py 3개 측정 함수 통합 검증
  1. measure_single_voltage()   — 전압 1회
  2. measure_dc_voltage()       — 전압 1000회 @ 50µs (바이너리)
  3. measure_single_current()   — 전류 1회
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import time
from src.hw_dmm import DMMHardware

VISA = 'USB0::0x2A8D::0x0101::MY64045156::0::INSTR'

P = F = 0
def ok(m):  global P; P+=1; print(f'  [PASS] {m}')
def ng(m):  global F; F+=1; print(f'  [FAIL] {m}')
def sec(t): print(f'\n{"="*60}\n  {t}\n{"="*60}')

dmm = DMMHardware()
dmm.connect(VISA)

# ── 1. 전압 1회 측정 ─────────────────────────────────────────────
sec('1. measure_single_voltage()  — MEAS:VOLT:DC? 10')
try:
    v = dmm.measure_single_voltage(v_range=10.0)
    print(f'  결과: {v:+.6f} V')
    if 0 < abs(v) < 15:
        ok(f'전압 1회 측정 정상: {v:+.6f} V')
    else:
        ng(f'전압 범위 이상: {v} V')
except Exception as e:
    ng(f'measure_single_voltage 실패: {e}')

# ── 2. 전압 1000회 @ 50µs (캐시 없음 — 최초 설정) ───────────────
sec('2. measure_dc_voltage(1000, 50µs)  — 첫 번째 호출 (설정 적용)')
try:
    t0 = time.perf_counter()
    r = dmm.measure_dc_voltage(n_samples=1000, interval_us=50.0, v_range=10.0)
    total_ms = (time.perf_counter() - t0) * 1000

    n = r['n_samples']
    print(f'  샘플 수   : {n}')
    print(f'  elapsed   : {r["elapsed_ms"]:.1f}ms  (total={total_ms:.1f}ms)')
    print(f'  interval  : {r["interval_us"]:.1f}µs')
    print(f'  평균      : {r["mean_v"]:+.6f} V')
    print(f'  피크투피크: {r["peak_to_peak_v"]:.6f} V')

    if n == 1000:     ok(f'샘플 수 1000 ✓')
    else:             ng(f'샘플 수 {n} (기대 1000)')

    if r['interval_us'] == 50.0:   ok('interval_us = 50.0µs ✓')
    else:                           ng(f'interval_us = {r["interval_us"]}µs')

    if r['elapsed_ms'] < 500:     ok(f'소요 시간 {r["elapsed_ms"]:.0f}ms ✓')
    else:                          ng(f'소요 시간 {r["elapsed_ms"]:.0f}ms (느림)')

except Exception as e:
    ng(f'measure_dc_voltage 실패: {e}')

# ── 3. 전압 1000회 @ 50µs (캐시 히트 — 설정 생략 확인) ──────────
sec('3. measure_dc_voltage(1000, 50µs)  — 두 번째 호출 (캐시 히트)')
try:
    t0 = time.perf_counter()
    r2 = dmm.measure_dc_voltage(n_samples=1000, interval_us=50.0, v_range=10.0)
    total_ms2 = (time.perf_counter() - t0) * 1000
    print(f'  elapsed   : {r2["elapsed_ms"]:.1f}ms  (total={total_ms2:.1f}ms)')
    print(f'  평균      : {r2["mean_v"]:+.6f} V')
    if r2['n_samples'] == 1000:
        ok(f'캐시 히트 정상 동작 ({r2["elapsed_ms"]:.0f}ms)')
    else:
        ng(f'캐시 히트 후 샘플 수 {r2["n_samples"]}')
except Exception as e:
    ng(f'캐시 히트 호출 실패: {e}')

# ── 4. 전류 1회 측정 ─────────────────────────────────────────────
sec('4. measure_single_current()  — MEAS:CURR:DC? 0.1')
try:
    a = dmm.measure_single_current(i_range=0.1)
    print(f'  결과: {a:+.9f} A')
    if abs(a) < 0.11:   # 100mA range → 110mA 이상은 이상
        ok(f'전류 1회 측정 정상: {a*1000:+.3f} mA')
    else:
        ng(f'전류 범위 초과 의심: {a:.6f} A')
except Exception as e:
    ng(f'measure_single_current 실패: {e}')

# ── 결과 ─────────────────────────────────────────────────────────
sec('최종 결과')
tot = P + F
print(f'  PASS : {P} / {tot}')
print(f'  FAIL : {F} / {tot}')
if F == 0:
    print('\n  ★ 모든 함수 정상 동작 확인')
else:
    print(f'\n  ✘ {F}개 실패')

dmm.disconnect()
