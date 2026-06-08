"""
verify_34465a.py
────────────────
34465A  50 µs × 1,000회 측정 검증
레퍼런스 코드 기준으로 정확히 구현
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import time
import numpy as np
import pyvisa

VISA    = 'USB0::0x2A8D::0x0101::MY64045156::0::INSTR'
N       = 1000
INT_US  = 50.0
APER_US = 40.0
OVF     = 9.9e+37

P = F = 0
def ok(m):  global P; P+=1; print(f'  [PASS] {m}')
def ng(m):  global F; F+=1; print(f'  [FAIL] {m}')
def inf(m): print(f'  [INFO] {m}')
def sec(t): print(f'\n{"="*60}\n  {t}\n{"="*60}')

# ── 연결 — read_termination 미설정 (USB 기본값 유지) ─────────────
rm  = pyvisa.ResourceManager()
dmm = rm.open_resource(VISA)
dmm.timeout = 10000
# ※ read_termination / write_termination 명시적 설정 안 함
#   USB INSTR은 packet 기반, \n 설정 시 binary read 방해됨

# ── 1. IDN ───────────────────────────────────────────────────────
sec('1. 연결 및 IDN')
idn = dmm.query('*IDN?').strip()
opt = dmm.query('*OPT?').strip()
inf(f'IDN : {idn}')
inf(f'OPT : {opt}')
model = idn.split(',')[1].strip()
fw    = idn.split(',')[3].strip() if len(idn.split(',')) > 3 else '?'
if '34465A' in model: ok(f'모델: {model}  FW: {fw}')
else:                 ng(f'모델 불일치: {model}')

# ── 2. 설정 (레퍼런스 순서 그대로) ───────────────────────────────
sec('2. 설정 명령 적용')

dmm.write('*RST')
dmm.write('*CLS')
time.sleep(0.3)

setup_cmds = [
    ('CONF:VOLT:DC 10',          'DC전압 10V 고정범위'),
    ('SENS:ZERO:AUTO OFF',       'Autozero OFF'),
    (f'VOLT:DC:APER {APER_US}E-6', f'Aperture {APER_US}µs'),
    ('TRIG:SOUR BUS',            'BUS trigger'),
    ('TRIG:DEL 0',               'Trigger delay = 0'),
    ('TRIG:COUN 1',              '트리거 1회'),
    ('SAMP:SOUR TIM',            '타이머 기반 샘플링'),
    (f'SAMP:TIM {INT_US}E-6',   f'샘플 간격 {INT_US:.0f}µs'),
    (f'SAMP:COUN {N}',           f'{N}회 측정'),
    ('FORM:DATA REAL,64',        'Binary 64-bit'),
    ('FORM:BORD SWAP',           'Little-endian'),
]

for cmd, desc in setup_cmds:
    dmm.write(cmd)
    err = dmm.query('SYST:ERR?').strip()
    ec  = int(err.split(',')[0])
    if ec == 0:   ok(f'{cmd:30s}  ← {desc}')
    else:         ng(f'{cmd:30s}  ERR={err}  ← {desc}')

# ── 3. 설정 확인 (레퍼런스의 설정 확인 커맨드) ───────────────────
sec('3. 설정 확인 커맨드 (Readback)')

aperture     = float(dmm.query('VOLT:DC:APER?'))
sample_time  = float(dmm.query('SAMP:TIM?'))
sample_count = int(float(dmm.query('SAMP:COUN?')))
trig_sour    = dmm.query('TRIG:SOUR?').strip()
samp_sour    = dmm.query('SAMP:SOUR?').strip()
error        = dmm.query('SYST:ERR?').strip()

inf(f'VOLT:DC:APER? = {aperture:.2e}  ({aperture*1e6:.1f}µs)')
inf(f'SAMP:TIM?     = {sample_time:.2e}  ({sample_time*1e6:.1f}µs)')
inf(f'SAMP:COUN?    = {sample_count}')
inf(f'TRIG:SOUR?    = {trig_sour}')
inf(f'SAMP:SOUR?    = {samp_sour}')
inf(f'SYST:ERR?     = {error}')

rb_tim_us = sample_time * 1e6

# 기대값 검증
if abs(aperture - APER_US/1e6) < 2e-6:
    ok(f'VOLT:DC:APER? = {aperture*1e6:.1f}µs  (기대 {APER_US:.0f}µs)')
else:
    ng(f'VOLT:DC:APER? = {aperture*1e6:.1f}µs  (기대 {APER_US:.0f}µs)  ← 불일치!')

if abs(sample_time - INT_US/1e6) < 2e-6:
    ok(f'SAMP:TIM? = {sample_time*1e6:.1f}µs  (기대 {INT_US:.0f}µs)  ★ 50µs 확인')
else:
    ng(f'SAMP:TIM? = {sample_time*1e6:.1f}µs  (기대 {INT_US:.0f}µs)  ← 불일치!')

if sample_count == N:
    ok(f'SAMP:COUN? = {sample_count}')
else:
    ng(f'SAMP:COUN? = {sample_count}  (기대 {N})')

if 'BUS' in trig_sour.upper():
    ok(f'TRIG:SOUR? = {trig_sour}')
else:
    ng(f'TRIG:SOUR? = {trig_sour}  (기대 BUS)')

if int(error.split(',')[0]) == 0:
    ok(f'SYST:ERR? = {error}')
else:
    ng(f'SYST:ERR? = {error}')

# ── 4. 측정 (*CLS → INIT → *TRG → *WAI → DATA:POIN? → FETC?) ───
sec('4. 실측  *CLS → INIT → *TRG → *WAI → DATA:POIN? → FETC?')

dmm.timeout = int((N * INT_US/1e6 + 8) * 1000) + 5000

dmm.write('*CLS')
t0 = time.perf_counter()
dmm.write('INIT')
dmm.write('*TRG')
dmm.write('*WAI')

# DATA:POIN? — 저장된 샘플 수 확인
points = int(float(dmm.query('DATA:POIN?')))
if points == N: ok(f'DATA:POIN? = {points}  (기대 {N})')
else:           ng(f'DATA:POIN? = {points}  (기대 {N}  불일치!)')

# FETC? — 바이너리 수신 (#0 Indefinite Length Block 직접 파싱)
# 장비 응답 형식: #0<8000 bytes float64 LE><\n>  (총 8003 bytes)
# query_binary_values는 #0을 "0 bytes"로 잘못 파싱 → 직접 처리
try:
    dmm.write('FETC?')
    raw = dmm.read_raw()   # 8003 bytes: '#'(1) + '0'(1) + data(8000) + '\n'(1)
    elapsed = (time.perf_counter() - t0) * 1000

    if raw[0:1] == b'#' and raw[1:2] == b'0':
        # Indefinite Length Block: #0<data><\n>
        data = raw[2:-1]   # 앞 2바이트(#0) + 끝 1바이트(\n) 제거
        vals = np.frombuffer(data, dtype='<f8')   # little-endian float64
        inf(f'#0 블록: raw={len(raw)}B, data={len(data)}B → {len(vals)} doubles')
    elif raw[0:1] == b'#' and raw[1:2] != b'0':
        # Definite Length Block: #N<N자리 바이트수><data>
        n_digits = int(raw[1:2])
        n_bytes  = int(raw[2:2 + n_digits])
        data     = raw[2 + n_digits : 2 + n_digits + n_bytes]
        vals     = np.frombuffer(data, dtype='<f8')
        inf(f'#N 블록: n_bytes={n_bytes}, data={len(data)}B → {len(vals)} doubles')
    else:
        inf('ASCII fallback')
        vals = np.array([float(v) for v in raw.decode('ascii', errors='replace').strip().split(',')])

    n_got  = len(vals)
    exp_ms = N * INT_US / 1000.0

    if n_got == N: ok(f'샘플 수    = {n_got}  (목표 {N})')
    else:          ng(f'샘플 수    = {n_got}  (목표 {N}  불일치!)')

    if 40 <= elapsed <= 500:
        ok(f'소요 시간  = {elapsed:.1f}ms  (이론 {exp_ms:.0f}ms)')
    else:
        ng(f'소요 시간  = {elapsed:.1f}ms  (이론 {exp_ms:.0f}ms  범위 벗어남!)')

    novld = int(np.sum(np.abs(vals) >= OVF * 0.99))
    if novld == 0: ok('오버플로우 없음')
    else:          ng(f'오버플로우 {novld}개!')

    eff = n_got / elapsed * 1000 if elapsed > 0 else 0
    print()
    print('  ┌─────────────────────────────────────────────────┐')
    print(f'  │  샘플 수          : {n_got:>6} 개                      │')
    print(f'  │  소요 시간        : {elapsed:>8.1f} ms                 │')
    print(f'  │  실효 샘플레이트  : {eff:>8.0f} S/s  (이론 {1/(INT_US/1e6):.0f})    │')
    print(f'  │  SAMP:TIM readback: {rb_tim_us:>8.1f} µs  (목표 50µs)      │')
    print(f'  │  aperture         : {APER_US:>8.1f} µs                 │')
    print(f'  │  전송 방식        :    FORM:DATA REAL,64 / BORD SWAP  │')
    if n_got > 0:
        print(f'  │  평균             : {vals.mean():>+12.6f} V              │')
        print(f'  │  최솟값           : {vals.min():>+12.6f} V              │')
        print(f'  │  최댓값           : {vals.max():>+12.6f} V              │')
        print(f'  │  표준편차         : {vals.std():>12.6f} V              │')
        print(f'  │  피크투피크       : {vals.max()-vals.min():>12.6f} V              │')
    print('  └─────────────────────────────────────────────────┘')

except Exception as e:
    elapsed = (time.perf_counter() - t0) * 1000
    ng(f'FETC? (binary) 실패 ({elapsed:.0f}ms): {e}')

# ── 5. 측정 후 에러 큐 ───────────────────────────────────────────
sec('5. 측정 후 SYST:ERR?')
dmm.timeout = 5000
err_after = dmm.query('SYST:ERR?').strip()
if int(err_after.split(',')[0]) == 0:
    ok(f'측정 후 에러 없음: {err_after}')
else:
    ng(f'측정 후 에러: {err_after}')

# ── 결과 ─────────────────────────────────────────────────────────
sec('최종 결과')
tot = P + F
print(f'  PASS : {P} / {tot}')
print(f'  FAIL : {F} / {tot}')
if F == 0:
    print(f'\n  ★ 모든 검증 통과')
    print(f'  ★ {N}회 × {rb_tim_us:.0f}µs 측정 정상 동작 확인')
else:
    print(f'\n  ✘ {F}개 실패')

dmm.close()
print('\n검증 완료.')
