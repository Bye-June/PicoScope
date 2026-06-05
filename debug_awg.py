"""
AWG 출력 파형 디버깅 스크립트
- Ch A에 AWG 출력 연결된 상태에서 실행
- 파형 전압 레벨 및 LOW 펄스 폭 검증
- ID1=57.75µs, ID3=177.37µs 확인
"""
import ctypes
import numpy as np
import time
import sys

sys.path.insert(0, '.')

# ── DLL 로드 ────────────────────────────────────────────────
dll = ctypes.WinDLL(r'C:\Program Files\Pico Technology\PicoScope 7 T&M Stable\ps6000a.dll')

def bind(fn, ret, args):
    f = getattr(dll, fn); f.restype = ret; f.argtypes = args; return f

open_fn   = bind('ps6000aOpenUnit',       ctypes.c_uint32, [ctypes.POINTER(ctypes.c_int16), ctypes.c_char_p, ctypes.c_uint32])
close_fn  = bind('ps6000aCloseUnit',      ctypes.c_uint32, [ctypes.c_int16])
chon_fn   = bind('ps6000aSetChannelOn',   ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_double, ctypes.c_uint32])
buf_fn    = bind('ps6000aSetDataBuffers', ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32])
run_fn    = bind('ps6000aRunBlock',       ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(ctypes.c_double), ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p])
rdy_fn    = bind('ps6000aIsReady',        ctypes.c_uint32, [ctypes.c_int16, ctypes.POINTER(ctypes.c_int16)])
getv_fn   = bind('ps6000aGetValues',      ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int16)])
lim_fn    = bind('ps6000aGetAdcLimits',   ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int16), ctypes.POINTER(ctypes.c_int16)])
wave_fn   = bind('ps6000aSigGenWaveform', ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint64])
range_fn  = bind('ps6000aSigGenRange',    ctypes.c_uint32, [ctypes.c_int16, ctypes.c_double, ctypes.c_double])
freq_fn   = bind('ps6000aSigGenFrequency',ctypes.c_uint32, [ctypes.c_int16, ctypes.c_double])
apply_fn  = bind('ps6000aSigGenApply',    ctypes.c_uint32, [ctypes.c_int16, ctypes.c_int16, ctypes.c_int16, ctypes.c_int16, ctypes.c_int16, ctypes.c_int16, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p])

# ── 상수 ────────────────────────────────────────────────────
PICO_RAW      = 0x80000000
PICO_DC       = 1
PICO_BW_FULL  = 0
PICO_ARB      = 0x10000000

# Ch A 측정 범위: AWG 출력 0~5V → ±5V range (enum=8), 프로브 없음(×1)
CHA_RANGE_ENUM = 8      # ±5V
CHA_RANGE_V    = 5.0
CHA_PROBE      = 1.0    # 직결, 프로브 없음

NUM    = 100000
TB     = 20   # 102.4 ns/sample = 9.766 MS/s

# ── AWG 파형 생성 ─────────────────────────────────────────
TOTAL_SAMPLES   = 10000
DAC_FREQ_HZ     = 4_000_000.0   # 4 MHz → 0.25 µs/sample
US_PER_SAMPLE   = 1e6 / DAC_FREQ_HZ  # 0.25 µs
REPEAT_FREQ_HZ  = DAC_FREQ_HZ / TOTAL_SAMPLES  # 400 Hz → 2.5 ms/cycle

PULSE_LENGTHS_US = {1: 57.75, 3: 177.37}

waveform = np.ones(TOTAL_SAMPLES, dtype=np.int16) * 32767  # 기본 HIGH
start_us = 200.0   # 200µs 초기 HIGH 후 시작
for sid, length_us in sorted(PULSE_LENGTHS_US.items()):
    s_idx = int(start_us / US_PER_SAMPLE)
    e_idx = s_idx + int(length_us / US_PER_SAMPLE)
    if e_idx < TOTAL_SAMPLES:
        waveform[s_idx:e_idx] = -32768   # LOW
        print(f"  ID{sid}: sample [{s_idx}:{e_idx}] = {e_idx-s_idx} samples = {(e_idx-s_idx)*US_PER_SAMPLE:.2f} µs (target {length_us} µs)")
    start_us += 1000.0

c_wave = (ctypes.c_int16 * TOTAL_SAMPLES)(*waveform)

# ── 장치 열기 ─────────────────────────────────────────────
h = ctypes.c_int16(0)
st = open_fn(ctypes.byref(h), None, 0)
H = h.value
print(f"\n[장치] Open: status={st}, handle={H}")

# ── AWG 설정 (free-running, 트리거 없음) ──────────────────
print("\n[AWG 설정]")

# 1) 파형 업로드
st = wave_fn(H, ctypes.c_uint32(PICO_ARB),
             ctypes.cast(ctypes.byref(c_wave), ctypes.c_void_p),
             ctypes.c_uint64(TOTAL_SAMPLES))
print(f"  SigGenWaveform : status={st}  {'OK' if st==0 else 'ERROR'}")

# 2) 전압 범위: 0V ~ 5V (pkToPk=5V, offset=2.5V)
st = range_fn(H, ctypes.c_double(5.0), ctypes.c_double(2.5))
print(f"  SigGenRange    : status={st}  {'OK -> 0~5V' if st==0 else f'ERROR (hardware limit?) -> falling back to 0~2V'}")
if st != 0:
    # 하드웨어 한계로 거절되면 안전한 0~2V로 대체
    st2 = range_fn(H, ctypes.c_double(2.0), ctypes.c_double(1.0))
    print(f"  SigGenRange 2V : status={st2}  {'OK -> 0~2V (fallback)' if st2==0 else 'ERROR'}")
    actual_v_range = "0~2V"
else:
    actual_v_range = "0~5V"

# 3) 반복 주파수
st = freq_fn(H, ctypes.c_double(REPEAT_FREQ_HZ))
print(f"  SigGenFrequency: status={st}  ({REPEAT_FREQ_HZ:.0f} Hz = 1 cycle per {1000/REPEAT_FREQ_HZ:.1f} ms)")

# 4) Apply (free-running: triggerEnabled=0)
actual_freq = ctypes.c_double(REPEAT_FREQ_HZ)
st = apply_fn(H,
              ctypes.c_int16(1),   # sigGenEnabled
              ctypes.c_int16(0),   # sweepEnabled
              ctypes.c_int16(0),   # triggerEnabled = 0 → free-running
              ctypes.c_int16(1),   # automaticClockOptimisation
              ctypes.c_int16(0),   # overrideClockAndPrescale
              ctypes.cast(ctypes.byref(actual_freq), ctypes.c_void_p),
              None, None, None)
print(f"  SigGenApply    : status={st}  actual_freq={actual_freq.value:.2f} Hz  {'OK' if st==0 else 'ERROR'}")
print(f"  출력 전압      : {actual_v_range}")
print(f"  파형 주기      : {1000/actual_freq.value:.2f} ms")

# ── Ch A 캡처 ─────────────────────────────────────────────
print("\n[Ch A 캡처]")
buf_a  = (ctypes.c_int16 * NUM)()
buf_am = (ctypes.c_int16 * NUM)()
chon_fn(H, 0, PICO_DC, CHA_RANGE_ENUM, 0.0, PICO_BW_FULL)
buf_fn(H, 0, ctypes.cast(buf_a, ctypes.c_void_p), ctypes.cast(buf_am, ctypes.c_void_p),
       NUM, 1, 0, PICO_RAW, 3)   # action=3: CLEAR_ALL+ADD

ti = ctypes.c_double(0)
run_fn(H, 0, ctypes.c_uint64(NUM), TB, ctypes.byref(ti), 0, None, None)
print(f"  RunBlock: est={ti.value:.1f} ms")

ready = ctypes.c_int16(0)
for _ in range(300):
    rdy_fn(H, ctypes.byref(ready))
    if ready.value: break
    time.sleep(0.01)

cn = ctypes.c_uint64(NUM); ov = ctypes.c_int16(0)
getv_fn(H, 0, ctypes.byref(cn), 1, PICO_RAW, 0, ctypes.byref(ov))

mn_ = ctypes.c_int16(0); mx_ = ctypes.c_int16(0)
lim_fn(H, 0, ctypes.byref(mn_), ctypes.byref(mx_))
ADC_MAX = float(mx_.value) if mx_.value > 0 else 32512.0

raw = np.frombuffer(buf_a, dtype=np.int16)[:int(cn.value)].astype(np.float32)
v   = (raw / ADC_MAX) * CHA_RANGE_V * CHA_PROBE

sample_us = 102.4 / 1000.0  # TB=20 → 102.4 ns

# ── 파형 분석 ─────────────────────────────────────────────
print(f"\n[Ch A 전압 분석]")
print(f"  범위: min={v.min():.3f}V  max={v.max():.3f}V  mean={v.mean():.3f}V")

THR = v.mean()  # 중간값을 기준으로 HIGH/LOW 판단
print(f"  판정 임계값: {THR:.3f}V (신호 중간값)")

is_lo = v < THR
fe = np.where((~is_lo[:-1]) & is_lo[1:])[0]   # 하강 에지
re = np.where( is_lo[:-1]  & (~is_lo[1:]))[0]  # 상승 에지
print(f"  하강 에지: {len(fe)}개  /  상승 에지: {len(re)}개")

# LOW 펄스 폭 측정
pulses = []
for f_edge in fe:
    valid_r = re[re > f_edge]
    if len(valid_r) > 0:
        width_us = (valid_r[0] - f_edge) * sample_us
        pulses.append((f_edge, valid_r[0], width_us))

print(f"\n[LOW 펄스 목록]")
if pulses:
    for i, (s, e, w) in enumerate(pulses[:20]):
        t_us = s * sample_us
        print(f"  펄스 {i+1:2d}: t={t_us:.1f}µs  width={w:.2f}µs", end='')
        # ID 판별
        for sid, target in PULSE_LENGTHS_US.items():
            if abs(w - target) < target * 0.20:
                err_pct = (w - target) / target * 100
                print(f"  → ID{sid} 목표={target}µs 오차={err_pct:+.1f}%", end='')
        print()
else:
    print("  LOW 펄스 없음! AWG 출력 확인 필요")

# ── ID별 검증 결과 ─────────────────────────────────────────
print(f"\n[ID별 검증 결과]")
all_pass = True
for sid, target_us in sorted(PULSE_LENGTHS_US.items()):
    tol = target_us * 0.10   # ±10% tolerance
    found = [(s,e,w) for s,e,w in pulses if abs(w - target_us) <= tol]
    if found:
        best = min(found, key=lambda x: abs(x[2]-target_us))
        err = (best[2]-target_us)/target_us*100
        print(f"  ID{sid}: 목표={target_us}µs  측정={best[2]:.2f}µs  오차={err:+.1f}%  → PASS")
    else:
        # 가장 가까운 펄스 찾기
        if pulses:
            nearest = min(pulses, key=lambda x: abs(x[2]-target_us))
            print(f"  ID{sid}: 목표={target_us}µs  가장 가까운={nearest[2]:.2f}µs  → FAIL (±10% 초과)")
        else:
            print(f"  ID{sid}: 펄스 없음  → FAIL")
        all_pass = False

print(f"\n{'='*45}")
print(f"AWG 파형 검증: {'PASS' if all_pass else 'FAIL'}")
print(f"출력 전압    : {actual_v_range}")
if not all_pass and len(pulses) > 0:
    print(f"\n힌트: 측정된 펄스들 = {[round(p[2],1) for p in pulses[:10]]} µs")

close_fn(H)
