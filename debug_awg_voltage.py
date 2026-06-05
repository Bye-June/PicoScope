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

h=ctypes.c_int16(0); open_fn(ctypes.byref(h),None,0); H=h.value
print(f'Handle={H}')

NUM=30000; TB=20; PICO_RAW=0x80000000
# Ch A: x10 프로브, +-1V HW range (enum=6) -> 유효 +-10V
HW_RANGE=6; HW_V=1.0; PROBE=10.0

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
    thr=v.mean()
    hi=v[v>=thr]; lo=v[v<thr]
    return (float(hi.mean()) if len(hi)>0 else 0.0), (float(lo.mean()) if len(lo)>0 else 0.0)

af=ctypes.c_double(1000.0)
print()
print("pkToPk / offset  -> 예상범위          status  |  측정 HIGH    LOW     Vpp")
print("-"*75)
cases = [
    (2.0, 0.0, "-1.0 ~ +1.0V"),
    (2.0, 1.0, " 0.0 ~ +2.0V"),
    (4.0, 0.0, "-2.0 ~ +2.0V"),
    (4.0, 2.0, " 0.0 ~ +4.0V"),
    (5.0, 2.5, " 0.0 ~ +5.0V"),
]
for pkToPk, offset, expected in cases:
    s_r = range_fn(H, ctypes.c_double(pkToPk), ctypes.c_double(offset))
    freq_fn(H, ctypes.c_double(1000.0))
    apply_fn(H,1,0,0,1,0,ctypes.cast(ctypes.byref(af),ctypes.c_void_p),None,None,None)
    time.sleep(0.1)
    hi, lo = measure()
    vpp = hi - lo
    ok = "OK" if s_r==0 else f"ERR({s_r})"
    print(f"  {pkToPk:.1f}V / {offset:.1f}V      {expected}    {ok:8s}  {hi:+.3f}V  {lo:+.3f}V  {vpp:.3f}V")

print()
print("=== SigGenRange 수용 한계 확인 ===")
limits = [(1,0),(2,0),(4,0),(6,0),(8,0),(4,2),(5,2.5),(6,3),(8,4)]
for pk, off in limits:
    s = range_fn(H, ctypes.c_double(pk), ctypes.c_double(off))
    result = "OK" if s==0 else "REJECTED"
    print(f"  pkToPk={pk:.0f}V  offset={off:.1f}V  -> {result} (status={s})")

close_fn(H)
