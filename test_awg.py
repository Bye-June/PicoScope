"""
AWG 구형파 테스트 - AWG 물리적 출력이 Channel A에 잡히는지 기본 검증
"""
import ctypes, numpy as np, time, sys

dll = ctypes.WinDLL(r"C:\Program Files\Pico Technology\PicoScope 7 T&M Stable\ps6000a.dll")

for fn, ret, args in [
    ("ps6000aOpenUnit",       ctypes.c_uint32, [ctypes.POINTER(ctypes.c_int16), ctypes.c_char_p, ctypes.c_uint32]),
    ("ps6000aCloseUnit",      ctypes.c_uint32, [ctypes.c_int16]),
    ("ps6000aSetChannelOn",   ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_double, ctypes.c_uint32]),
    ("ps6000aSetChannelOff",  ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32]),
    ("ps6000aSetDataBuffers", ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32]),
    ("ps6000aRunBlock",       ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(ctypes.c_double), ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]),
    ("ps6000aIsReady",        ctypes.c_uint32, [ctypes.c_int16, ctypes.POINTER(ctypes.c_int16)]),
    ("ps6000aGetValues",      ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int16)]),
    ("ps6000aGetAdcLimits",   ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int16), ctypes.POINTER(ctypes.c_int16)]),
    ("ps6000aSigGenWaveform", ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint16]),
    ("ps6000aSigGenRange",    ctypes.c_uint32, [ctypes.c_int16, ctypes.c_double, ctypes.c_double]),
    ("ps6000aSigGenTrigger",  ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64]),
    ("ps6000aSigGenFrequency",ctypes.c_uint32, [ctypes.c_int16, ctypes.c_double]),
    ("ps6000aSigGenApply",    ctypes.c_uint32, [ctypes.c_int16]*6 + [ctypes.c_void_p]*4),
    ("ps6000aSigGenSoftwareTriggerControl", ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32]),
]:
    f = getattr(dll, fn); f.restype = ret; f.argtypes = args

PICO_INT16_T        = 1
PICO_RATIO_MODE_RAW = 0x80000000
PICO_SQUARE         = 0x00000012
PICO_ARBITRARY      = 0x10000000

h = ctypes.c_int16(0)
s = dll.ps6000aOpenUnit(ctypes.byref(h), None, 0)
print(f"Open: status={s}, h={h.value}")
if s not in (0, 282): sys.exit(1)

# Ch A ON: ±5V DC
dll.ps6000aSetChannelOn(h.value, 0, 1, ctypes.c_uint32(8), ctypes.c_double(0.0), ctypes.c_uint32(0))
for ch in range(1, 8): dll.ps6000aSetChannelOff(h.value, ctypes.c_uint32(ch))

print("\n=== TEST 1: 구형파 연속 출력 (SQUARE, 400Hz, 0~5V, 트리거 없음) ===")
# 구형파는 버퍼 불필요
s = dll.ps6000aSigGenWaveform(h.value, ctypes.c_uint32(PICO_SQUARE), None, ctypes.c_uint16(0))
print(f"SigGenWaveform(SQUARE): {s}")
s = dll.ps6000aSigGenRange(h.value, ctypes.c_double(5.0), ctypes.c_double(2.5))
print(f"SigGenRange(0~5V): {s}")
# 트리거 없음: PICO_SIGGEN_NONE=0 for trigSource
s = dll.ps6000aSigGenTrigger(h.value, ctypes.c_uint32(0), ctypes.c_uint32(0), ctypes.c_uint64(0), ctypes.c_uint64(0))
print(f"SigGenTrigger(no trigger, continuous): {s}")
freq = ctypes.c_double(400.0)
s = dll.ps6000aSigGenFrequency(h.value, freq)
print(f"SigGenFrequency(400Hz): {s}")
s = dll.ps6000aSigGenApply(h.value,
    ctypes.c_int16(1), ctypes.c_int16(0), ctypes.c_int16(0),  # enabled, no sweep, no trigger
    ctypes.c_int16(1), ctypes.c_int16(0),                     # auto clock
    ctypes.byref(freq), None, None, None)
print(f"SigGenApply: {s}")

if s != 0:
    print("[FAIL] SigGenApply failed"); dll.ps6000aCloseUnit(h.value); sys.exit(1)

print("구형파 출력 중 - 1초 대기 후 캡처...")
time.sleep(1.0)

# 캡처
NUM = 50000; TIMEBASE = 200
buf_max = (ctypes.c_int16 * NUM)(); buf_min = (ctypes.c_int16 * NUM)()
dll.ps6000aSetDataBuffers(h.value, ctypes.c_uint32(0),
    ctypes.cast(buf_max, ctypes.c_void_p), ctypes.cast(buf_min, ctypes.c_void_p),
    ctypes.c_int32(NUM), ctypes.c_uint32(PICO_INT16_T),
    ctypes.c_uint64(0), ctypes.c_uint32(PICO_RATIO_MODE_RAW), ctypes.c_uint32(3))

ti = ctypes.c_double(0)
dll.ps6000aRunBlock(h.value, ctypes.c_uint64(0), ctypes.c_uint64(NUM), ctypes.c_uint32(TIMEBASE), ctypes.byref(ti), ctypes.c_uint32(0), None, None)

ready = ctypes.c_int16(0)
for _ in range(200):
    dll.ps6000aIsReady(h.value, ctypes.byref(ready))
    if ready.value: break
    time.sleep(0.01)

cn = ctypes.c_uint64(NUM); ov = ctypes.c_int16(0)
dll.ps6000aGetValues(h.value, ctypes.c_uint64(0), ctypes.byref(cn), ctypes.c_uint64(1), ctypes.c_uint32(PICO_RATIO_MODE_RAW), ctypes.c_uint32(0), ctypes.byref(ov))

mn = ctypes.c_int16(0); mx = ctypes.c_int16(0)
dll.ps6000aGetAdcLimits(h.value, ctypes.c_uint32(0), ctypes.byref(mn), ctypes.byref(mx))
mv = float(mx.value) if mx.value > 0 else 32512.0

raw = np.array(buf_max[:cn.value], dtype=np.float32)
v = (raw / mv) * 5.0

print(f"\nCh A: V_min={v.min():.3f}V  V_max={v.max():.3f}V  V_mean={v.mean():.3f}V")
fe = np.where((v[:-1] >= 2.5) & (v[1:] < 2.5))[0]
re = np.where((v[:-1] < 2.5) & (v[1:] >= 2.5))[0]
print(f"Falling edges: {len(fe)}, Rising edges: {len(re)}")

if len(fe) > 2:
    print(f"✅ AWG 구형파 출력 확인! 400Hz 주기 캡처됨")
    if len(fe) >= 2:
        period_samples = fe[1] - fe[0]
        period_us = period_samples * TIMEBASE * 2 / 1000
        print(f"   측정 주기: {period_samples}샘플 = {period_us:.1f}us → {1e6/period_us:.0f}Hz")
else:
    print(f"❌ 구형파 미검출 - AWG 출력이 Ch A에 연결되지 않았거나 출력 안됨")
    print(f"   V_mean={v.mean():.3f}V → ", end="")
    if v.mean() < 0.5: print("AWG 출력 0V 근처 (물리적 미연결 또는 AWG 오동작)")
    elif v.mean() > 4.5: print("AWG 출력 5V 근처 (HIGH 고정 상태)")
    else: print("중간 전압 (노이즈 or 미약한 신호)")

dll.ps6000aCloseUnit(h.value)
print("\n[DONE]")
