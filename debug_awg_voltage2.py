"""
AWG 내장 SQUARE 파형 단독 테스트 (SigGenWaveform 호출 없이)
- SigGenRange + SigGenFrequency + SigGenApply 만으로 구성
- 다양한 전압 설정 시 실제 출력 확인
"""
import ctypes, numpy as np, time

dll = ctypes.WinDLL(r'C:\Program Files\Pico Technology\PicoScope 7 T&M Stable\ps6000a.dll')
def B(fn,ret,args): f=getattr(dll,fn); f.restype=ret; f.argtypes=args; return f
open_fn  = B('ps6000aOpenUnit',       ctypes.c_uint32,[ctypes.POINTER(ctypes.c_int16),ctypes.c_char_p,ctypes.c_uint32])
close_fn = B('ps6000aCloseUnit',      ctypes.c_uint32,[ctypes.c_int16])
chon_fn  = B('ps6000aSetChannelOn',   ctypes.c_uint32,[ctypes.c_int16,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_double,ctypes.c_uint32])
buf_fn   = B('ps6000aSetDataBuffers', ctypes.c_uint32,[ctypes.c_int16,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int32,ctypes.c_uint32,ctypes.c_uint64,ctypes.c_uint32,ctypes.c_uint32])
run_fn   = B('ps6000aRunBlock',       ctypes.c_uint32,[ctypes.c_int16,ctypes.c_uint64,ctypes.c_uint64,ctypes.c_uint32,ctypes.POINTER(ctypes.c_double),ctypes.c_uint32,ctypes.c_void_p,ctypes.c_void_p])
rdy_fn   = B('ps6000aIsReady',        ctypes.c_uint32,[ctypes.c_int16,ctypes.POINTER(ctypes.c_int16)])
getv_fn  = B('ps6000aGetValues',      ctypes.c_uint32,[ctypes.c_int16,ctypes.c_uint64,ctypes.POINTER(ctypes.c_uint64),ctypes.c_uint64,ctypes.c_uint32,ctypes.c_uint32,ctypes.POINTER(ctypes.c_int16)])
lim_fn   = B('ps6000aGetAdcLimits',   ctypes.c_uint32,[ctypes.c_int16,ctypes.c_uint32,ctypes.POINTER(ctypes.c_int16),ctypes.POINTER(ctypes.c_int16)])
freq_fn  = B('ps6000aSigGenFrequency',ctypes.c_uint32,[ctypes.c_int16,ctypes.c_double])
range_fn = B('ps6000aSigGenRange',    ctypes.c_uint32,[ctypes.c_int16,ctypes.c_double,ctypes.c_double])
apply_fn = B('ps6000aSigGenApply',    ctypes.c_uint32,[ctypes.c_int16,ctypes.c_int16,ctypes.c_int16,ctypes.c_int16,ctypes.c_int16,ctypes.c_int16,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p])
wave_fn  = B('ps6000aSigGenWaveform', ctypes.c_uint32,[ctypes.c_int16,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint64])

h=ctypes.c_int16(0); open_fn(ctypes.byref(h),None,0); H=h.value
print(f'Handle={H}')

NUM=30000; TB=20; PICO_RAW=0x80000000
HW_RANGE=6; HW_V=1.0; PROBE=10.0  # x10 probe, +-10V 유효

def measure():
    buf=(ctypes.c_int16*NUM)(); bm=(ctypes.c_int16*NUM)()
    chon_fn(H,0,1,HW_RANGE,0.0,0)
    buf_fn(H,0,ctypes.cast(buf,ctypes.c_void_p),ctypes.cast(bm,ctypes.c_void_p),NUM,1,0,PICO_RAW,3)
    ti=ctypes.c_double(0)
    run_fn(H,0,ctypes.c_uint64(NUM),TB,ctypes.byref(ti),0,None,None)
    rdy=ctypes.c_int16(0)
    for _ in range(200):
        rdy_fn(H,ctypes.byref(rdy))
        if rdy.value: break
        time.sleep(0.01)
    cn=ctypes.c_uint64(NUM); ov=ctypes.c_int16(0)
    getv_fn(H,0,ctypes.byref(cn),1,PICO_RAW,0,ctypes.byref(ov))
    mn_=ctypes.c_int16(0); mx_=ctypes.c_int16(0)
    lim_fn(H,0,ctypes.byref(mn_),ctypes.byref(mx_))
    ADC=float(mx_.value) if mx_.value>0 else 32512.0
    raw=np.frombuffer(buf,dtype=np.int16)[:int(cn.value)].astype(np.float32)
    v=(raw/ADC)*HW_V*PROBE
    return float(v.max()), float(v.min()), float(v.mean())

af=ctypes.c_double(1000.0)

# 파형 타입 상수
PICO_SQUARE    = 0x00000012
PICO_SINE      = 0x00000011
PICO_DC        = 0x00000400
PICO_ARBITRARY = 0x10000000

print()
print("--- 테스트 1: SQUARE 파형, SigGenWaveform 없이 ---")
cases = [(2.0,0.0),(4.0,0.0),(4.0,2.0),(5.0,2.5)]
for pk,off in cases:
    # WaveType을 SQUARE로 설정 (SigGenWaveform 먼저 호출)
    s_w = wave_fn(H, ctypes.c_uint32(PICO_SQUARE), None, ctypes.c_uint64(0))
    s_r = range_fn(H, ctypes.c_double(pk), ctypes.c_double(off))
    s_f = freq_fn(H, ctypes.c_double(1000.0))
    s_a = apply_fn(H,1,0,0,1,0,ctypes.cast(ctypes.byref(af),ctypes.c_void_p),None,None,None)
    time.sleep(0.15)
    vmax, vmin, vmean = measure()
    print(f"  SQUARE pk={pk:.1f} off={off:.1f} -> wave={s_w} range={s_r} apply={s_a} | max={vmax:.3f}V min={vmin:.3f}V Vpp={vmax-vmin:.3f}V")

print()
print("--- 테스트 2: DC 모드로 offset 단독 확인 ---")
for off in [0.0, 1.0, 2.0, 2.5, 3.0]:
    s_w = wave_fn(H, ctypes.c_uint32(PICO_DC), None, ctypes.c_uint64(0))
    s_r = range_fn(H, ctypes.c_double(1.0), ctypes.c_double(off))
    s_a = apply_fn(H,1,0,0,1,0,ctypes.cast(ctypes.byref(af),ctypes.c_void_p),None,None,None)
    time.sleep(0.15)
    vmax, vmin, vmean = measure()
    print(f"  DC offset={off:.1f}V -> wave={s_w} range={s_r} | mean={vmean:.3f}V (expected {off:.1f}V)")

print()
print("--- 테스트 3: ARBITRARY 버퍼 (all-HIGH) 전압 확인 ---")
# 버퍼 전체를 +32767 (HIGH) 으로 채움
BUF=1000
wf_hi=np.ones(BUF,dtype=np.int16)*32767
wf_lo=np.ones(BUF,dtype=np.int16)*(-32767)
c_hi=(ctypes.c_int16*BUF)(*wf_hi)
c_lo=(ctypes.c_int16*BUF)(*wf_lo)

for label, buf_ptr, expected_level in [
    ("ALL +32767 (max HIGH)", c_hi, "offset + pkToPk/2"),
    ("ALL -32767 (max LOW) ", c_lo, "offset - pkToPk/2"),
]:
    s_w = wave_fn(H, ctypes.c_uint32(PICO_ARBITRARY),
                  ctypes.cast(ctypes.byref(buf_ptr), ctypes.c_void_p), ctypes.c_uint64(BUF))
    s_r = range_fn(H, ctypes.c_double(4.0), ctypes.c_double(2.0))  # 0~4V
    s_f = freq_fn(H, ctypes.c_double(400.0))
    s_a = apply_fn(H,1,0,0,1,0,ctypes.cast(ctypes.byref(af),ctypes.c_void_p),None,None,None)
    time.sleep(0.15)
    vmax, vmin, vmean = measure()
    print(f"  ARB {label}: wave={s_w} range={s_r} | mean={vmean:.3f}V (expected {expected_level})")

close_fn(H)
