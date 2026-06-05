import ctypes, numpy as np, time, sys
sys.path.insert(0, '.')

dll = ctypes.WinDLL(r'C:\Program Files\Pico Technology\PicoScope 7 T&M Stable\ps6000a.dll')
def S(fn, ret, args):
    f = getattr(dll, fn); f.restype = ret; f.argtypes = args; return f

open_fn  = S('ps6000aOpenUnit',       ctypes.c_uint32, [ctypes.POINTER(ctypes.c_int16), ctypes.c_char_p, ctypes.c_uint32])
close_fn = S('ps6000aCloseUnit',      ctypes.c_uint32, [ctypes.c_int16])
chon_fn  = S('ps6000aSetChannelOn',   ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_double, ctypes.c_uint32])
buf_fn   = S('ps6000aSetDataBuffers', ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32])
run_fn   = S('ps6000aRunBlock',       ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(ctypes.c_double), ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p])
rdy_fn   = S('ps6000aIsReady',        ctypes.c_uint32, [ctypes.c_int16, ctypes.POINTER(ctypes.c_int16)])
getv_fn  = S('ps6000aGetValues',      ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int16)])
lim_fn   = S('ps6000aGetAdcLimits',   ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int16), ctypes.POINTER(ctypes.c_int16)])

NUM = 100000; TB = 20; PICO_RAW = 0x80000000
RANGE_ENUM = 6; RANGE_V = 1.0; PROBE = 10.0   # +-10V + x10 probe -> +-1V HW range

h = ctypes.c_int16(0)
open_fn(ctypes.byref(h), None, 0)
H = h.value

buf_b = (ctypes.c_int16 * NUM)(); bm_b = (ctypes.c_int16 * NUM)()
buf_c = (ctypes.c_int16 * NUM)(); bm_c = (ctypes.c_int16 * NUM)()

chon_fn(H, 1, 1, RANGE_ENUM, 0.0, 0)
buf_fn(H, 1, ctypes.cast(buf_b, ctypes.c_void_p), ctypes.cast(bm_b, ctypes.c_void_p), NUM, 1, 0, PICO_RAW, 3)
chon_fn(H, 2, 1, RANGE_ENUM, 0.0, 0)
buf_fn(H, 2, ctypes.cast(buf_c, ctypes.c_void_p), ctypes.cast(bm_c, ctypes.c_void_p), NUM, 1, 0, PICO_RAW, 2)

ti = ctypes.c_double(0)
run_fn(H, 0, ctypes.c_uint64(NUM), TB, ctypes.byref(ti), 0, None, None)

ready = ctypes.c_int16(0)
for _ in range(300):
    rdy_fn(H, ctypes.byref(ready))
    if ready.value:
        break
    time.sleep(0.01)

cn = ctypes.c_uint64(NUM); ov = ctypes.c_int16(0)
getv_fn(H, 0, ctypes.byref(cn), 1, PICO_RAW, 0, ctypes.byref(ov))

mn_ = ctypes.c_int16(0); mx_ = ctypes.c_int16(0)
lim_fn(H, 0, ctypes.byref(mn_), ctypes.byref(mx_))
ADC = float(mx_.value) if mx_.value > 0 else 32512.0

def to_v(buf):
    a = np.frombuffer(buf, dtype=np.int16)[:int(cn.value)].astype(np.float32)
    return (a / ADC) * RANGE_V * PROBE

from src.decoder_sent import SENTDecoder
# GetTimebase: TB=20 -> 102.4ns = 9,765,625 Hz
decoder = SENTDecoder(sample_rate_hz=9_765_625, nominal_ut_us=3.0)

channels = [
    ('B', 'SENT_M (TSM_L_SENT)', buf_b),
    ('C', 'SENT_S (TSS_L_SENT)', buf_c),
]

all_pass = True
for ch_id, ch_name, buf in channels:
    v = to_v(buf)
    res = decoder.decode_frame(v, threshold=2.5)
    print(f"=== Ch {ch_id} : {ch_name} ===")

    if res['status'] == 'success':
        ut      = res['measured_ut_us']
        sync_us = res['sync_period_us']
        hall    = res['hall_raw']
        hoffset = res['hall_offset']
        temp_r  = res['temp_raw']
        temp_c  = res['temp_celsius']
        sstate  = res['status_state']
        srange  = res['status_range']
        crc_ok  = res['crc_valid']
        crc_rx  = res['crc_nibble']
        crc_exp = res['crc_expected']

        ut_pass  = 2.4 <= ut <= 3.6
        ch_pass  = ut_pass and crc_ok and (sstate == 'Normal')
        all_pass = all_pass and ch_pass

        tag_ut  = "PASS" if ut_pass  else "FAIL"
        tag_crc = "PASS" if crc_ok   else "FAIL"
        tag_all = "PASS" if ch_pass  else "FAIL"

        print(f"  Sync pulse   : {sync_us:.1f} us  (56 x UT)")
        print(f"  UT           : {ut:.4f} us  [{tag_ut}]  spec: 3.0 us +/-20% (2.4~3.6)")
        print(f"  Hall (16bit) : {hall}  (midscale=32768, offset={hoffset:+d})")
        print(f"  Temperature  : {temp_r} raw  ->  {temp_c} degC  (approx, 1LSB~1degC)")
        print(f"  Status state : {sstate}  /  Mag range: {srange}")
        print(f"  CRC          : rx={crc_rx}  expected={crc_exp}  [{tag_crc}]")
        print(f"  >> RESULT    : {tag_all}")
    else:
        all_pass = False
        print(f"  ERROR: {res['message']}")
        print(f"  >> RESULT    : FAIL")
    print()

print("=" * 40)
print(f"SENT OVERALL: {'PASS' if all_pass else 'FAIL'}")

close_fn(H)
