"""
AWG 파형 검증 및 이미지 저장 스크립트
- AWG 출력 -> Ch A 직결 (x10 프로브)
- 트리거 모드: 1회 발사
- ID1(57.75us) / ID3(177.37us) LOW 펄스 검증
- 결과를 PNG 이미지로 저장
"""
import ctypes
import numpy as np
import time
import os
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

dll = ctypes.WinDLL(r'C:\Program Files\Pico Technology\PicoScope 7 T&M Stable\ps6000a.dll')
def B(fn, ret, args):
    f = getattr(dll, fn); f.restype = ret; f.argtypes = args; return f

open_fn  = B('ps6000aOpenUnit',        ctypes.c_uint32, [ctypes.POINTER(ctypes.c_int16), ctypes.c_char_p, ctypes.c_uint32])
close_fn = B('ps6000aCloseUnit',       ctypes.c_uint32, [ctypes.c_int16])
chon_fn  = B('ps6000aSetChannelOn',    ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_double, ctypes.c_uint32])
buf_fn   = B('ps6000aSetDataBuffers',  ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32])
run_fn   = B('ps6000aRunBlock',        ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(ctypes.c_double), ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p])
rdy_fn   = B('ps6000aIsReady',         ctypes.c_uint32, [ctypes.c_int16, ctypes.POINTER(ctypes.c_int16)])
getv_fn  = B('ps6000aGetValues',       ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int16)])
lim_fn   = B('ps6000aGetAdcLimits',    ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int16), ctypes.POINTER(ctypes.c_int16)])
wave_fn  = B('ps6000aSigGenWaveform',  ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint64])
range_fn = B('ps6000aSigGenRange',     ctypes.c_uint32, [ctypes.c_int16, ctypes.c_double, ctypes.c_double])
freq_fn  = B('ps6000aSigGenFrequency', ctypes.c_uint32, [ctypes.c_int16, ctypes.c_double])
trig_fn  = B('ps6000aSigGenTrigger',   ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64])
apply_fn = B('ps6000aSigGenApply',     ctypes.c_uint32, [ctypes.c_int16, ctypes.c_int16, ctypes.c_int16, ctypes.c_int16, ctypes.c_int16, ctypes.c_int16, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p])
soft_fn  = B('ps6000aSigGenSoftwareTriggerControl', ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32])

# ── 장치 열기 ──────────────────────────────────────────────
h = ctypes.c_int16(0)
st = open_fn(ctypes.byref(h), None, 0)
H = h.value
if H <= 0:
    print(f"ERROR: 장치 열기 실패 (status={st}). PicoScope 소프트웨어를 종료 후 재실행하세요.")
    exit(1)
print(f"장치 열림: handle={H}")

# ── AWG 파형 생성 ──────────────────────────────────────────
TOTAL     = 10000
DAC_HZ    = 4_000_000.0          # 4 MHz DAC
US_PER_S  = 1e6 / DAC_HZ        # 0.25 us/sample
REP_HZ    = DAC_HZ / TOTAL      # 400 Hz (2.5 ms/cycle)

PULSES = {1: 57.75, 3: 177.37}  # {ID: us}

wf = np.ones(TOTAL, dtype=np.int16) * 32767  # 기본 HIGH
start_us = 200.0
for sid, us in sorted(PULSES.items()):
    s = int(start_us / US_PER_S)
    e = s + int(us / US_PER_S)
    wf[s:e] = -32768   # LOW
    print(f"  ID{sid}: [{s}:{e}] = {(e-s)*US_PER_S:.2f}us LOW")
    start_us += 1000.0

c_wf = (ctypes.c_int16 * TOTAL)(*wf)

# AWG 설정
wave_fn(H, ctypes.c_uint32(0x10000000), ctypes.cast(ctypes.byref(c_wf), ctypes.c_void_p), ctypes.c_uint64(TOTAL))

# 전압: pkToPk=5V, offset=2.5V → 0V~5V
st_r = range_fn(H, ctypes.c_double(5.0), ctypes.c_double(2.5))
actual_vpk = 5.0 if st_r == 0 else 2.0
actual_voff = 2.5 if st_r == 0 else 1.0
if st_r != 0:
    range_fn(H, ctypes.c_double(2.0), ctypes.c_double(1.0))  # fallback
print(f"AWG 전압: 0~{actual_vpk + actual_voff - actual_vpk/2*2 + actual_vpk:.0f}V  (range_status={st_r})")

freq_fn(H, ctypes.c_double(REP_HZ))
# 트리거 모드: SOFT_TRIG (4), RISING (0), 1회
trig_fn(H, ctypes.c_uint32(0), ctypes.c_uint32(4), ctypes.c_uint64(1), ctypes.c_uint64(0))
af = ctypes.c_double(REP_HZ)
apply_fn(H, 1, 0, 1, 1, 0, ctypes.cast(ctypes.byref(af), ctypes.c_void_p), None, None, None)
print(f"AWG 준비 완료: {af.value:.0f}Hz, 트리거 대기 중")

# ── Ch A 캡처 (x10 프로브 기준) ───────────────────────────
# Ch A 설정: enum=6 (±1V HW range), PROBE=10 → 유효 ±10V
# AWG 0~5V + x10 프로브 → scope 입력 0~0.5V → ±1V range에 딱 맞음
NUM       = 100000
TB        = 20          # 102.4 ns/sample = 9.766 MS/s
PICO_RAW  = 0x80000000
HW_RANGE_V = 1.0        # ±1V hardware range
PROBE_X   = 10.0        # x10 probe

buf_a  = (ctypes.c_int16 * NUM)()
buf_am = (ctypes.c_int16 * NUM)()
chon_fn(H, 0, 1, 6, 0.0, 0)   # Ch A = 0, DC = 1, ±1V = 6, BW_FULL = 0
buf_fn(H, 0,
       ctypes.cast(buf_a,  ctypes.c_void_p),
       ctypes.cast(buf_am, ctypes.c_void_p),
       NUM, 1, 0, PICO_RAW, 3)

ti = ctypes.c_double(0)
run_fn(H, 0, ctypes.c_uint64(NUM), TB, ctypes.byref(ti), 0, None, None)
print(f"캡처 시작... 예상시간={ti.value:.1f}ms")

time.sleep(0.002)  # scope 안정화

# AWG 소프트 트리거 발사 (0→1 RISING edge)
soft_fn(H, ctypes.c_uint32(0))
soft_fn(H, ctypes.c_uint32(1))
print("AWG 트리거 발사!")

# 캡처 완료 대기
rdy = ctypes.c_int16(0)
for _ in range(300):
    rdy_fn(H, ctypes.byref(rdy))
    if rdy.value: break
    time.sleep(0.01)

cn  = ctypes.c_uint64(NUM)
ov  = ctypes.c_int16(0)
getv_fn(H, 0, ctypes.byref(cn), 1, PICO_RAW, 0, ctypes.byref(ov))

mn_ = ctypes.c_int16(0); mx_ = ctypes.c_int16(0)
lim_fn(H, 0, ctypes.byref(mn_), ctypes.byref(mx_))
ADC_MAX = float(mx_.value) if mx_.value > 0 else 32512.0

N = int(cn.value)
raw = np.frombuffer(buf_a, dtype=np.int16)[:N].astype(np.float32)
v   = (raw / ADC_MAX) * HW_RANGE_V * PROBE_X    # 실제 전압 (V)

sample_us = 102.4 / 1000.0   # 0.1024 us/sample
t_us      = np.arange(N) * sample_us
t_ms      = t_us / 1000.0

close_fn(H)

# ── 분석 ──────────────────────────────────────────────────
v_max = v.max(); v_min = v.min(); v_mean = v.mean()
print(f"\n측정값: min={v_min:.3f}V  max={v_max:.3f}V  mean={v_mean:.3f}V")

# 중간값 기준으로 HIGH/LOW 판단
THR = (v_max + v_min) / 2.0
is_lo = v < THR
fe = np.where((~is_lo[:-1]) & is_lo[1:])[0]
re = np.where(is_lo[:-1] & (~is_lo[1:]))[0]

pulses = []
for f_ in fe:
    vr = re[re > f_]
    if len(vr) > 0:
        w = (vr[0] - f_) * sample_us
        if w > 5.0:
            pulses.append((f_, vr[0], w))

# ── 이미지 저장 ────────────────────────────────────────────
out_dir = os.path.join("results", datetime.now().strftime("%Y%m%d"))
os.makedirs(out_dir, exist_ok=True)
ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
img = os.path.join(out_dir, f"AWG_verify_{ts}.png")

fig, axes = plt.subplots(3, 1, figsize=(16, 10), facecolor='#1e1e1e')
fig.suptitle('AWG 파형 검증  (AWG Output → Ch A)', color='white', fontsize=14, fontweight='bold')

COLOR_HI = '#4CAF50'   # green
COLOR_LO = '#F44336'   # red
COLOR_AN = '#FFC107'   # amber

HIGH_V = v_max * 1.05
LOW_V  = v_min - abs(v_max) * 0.2

for ax in axes:
    ax.set_facecolor('#2b2b2b')
    ax.tick_params(colors='white')
    ax.yaxis.label.set_color('white')
    ax.xaxis.label.set_color('white')
    ax.spines['bottom'].set_color('#555')
    ax.spines['left'].set_color('#555')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.axhline(THR, color='#666', linestyle='--', linewidth=0.8, label=f'임계값 {THR:.2f}V')

# ── Plot 1: 전체 파형 (10ms) ──────────────────────────────
ax1 = axes[0]
ax1.plot(t_ms, v, color='#2196F3', linewidth=0.6, label='Ch A (AWG 출력)')
ax1.set_xlim(0, t_ms[-1])
ax1.set_ylim(LOW_V, HIGH_V)
ax1.set_ylabel('전압 (V)', color='white')
ax1.set_xlabel('시간 (ms)', color='white')
ax1.set_title('전체 파형 (10ms)', color='#aaa', fontsize=10)
for f_, e_, w in pulses:
    ax1.axvspan(t_ms[f_], t_ms[min(e_, N-1)], alpha=0.3, color=COLOR_LO)

# 검증 결과 텍스트
status_lines = []
pass_all = True
for sid, target_us in sorted(PULSES.items()):
    found = [(f_,e_,w) for f_,e_,w in pulses if abs(w - target_us) < target_us * 0.15]
    if found:
        best = min(found, key=lambda x: abs(x[2]-target_us))
        err = (best[2]-target_us)/target_us*100
        status_lines.append(f"ID{sid}: {best[2]:.2f}us (목표 {target_us}us, 오차 {err:+.1f}%)  PASS")
    else:
        status_lines.append(f"ID{sid}: 미감지  FAIL")
        pass_all = False

result_color = '#4CAF50' if pass_all else '#F44336'
result_text  = '\n'.join(status_lines)
ax1.text(0.02, 0.95, result_text, transform=ax1.transAxes,
         color=result_color, fontsize=9, fontfamily='monospace',
         verticalalignment='top',
         bbox=dict(boxstyle='round', facecolor='#333', alpha=0.8))
ax1.legend(loc='upper right', facecolor='#333', labelcolor='white', fontsize=8)

# ── Plot 2: ID1 펄스 확대 ─────────────────────────────────
ax2 = axes[1]
id1_pulses = [(f_,e_,w) for f_,e_,w in pulses if abs(w-57.75) < 20]
if id1_pulses:
    p = id1_pulses[0]
    center_us = (p[0] + p[1]) / 2 * sample_us
    zoom_us   = 400.0
    z_start   = max(0, int((center_us - zoom_us) / sample_us))
    z_end     = min(N, int((center_us + zoom_us) / sample_us))
    ax2.plot(t_us[z_start:z_end], v[z_start:z_end], color='#FF9800', linewidth=1.2)
    ax2.axvspan(t_us[p[0]], t_us[min(p[1], N-1)], alpha=0.35, color=COLOR_LO, label=f'ID1 LOW = {p[2]:.2f}us')
    ax2.set_xlim(t_us[z_start], t_us[z_end])
    ax2.set_ylim(LOW_V, HIGH_V)
    ax2.set_title(f'ID1 펄스 확대  (목표: 57.75us)', color='#aaa', fontsize=10)
    ax2.annotate(f'{p[2]:.2f} us', xy=(t_us[p[0]], THR), xytext=(t_us[p[0]] + 15, HIGH_V * 0.7),
                 arrowprops=dict(arrowstyle='->', color=COLOR_AN), color=COLOR_AN, fontsize=10)
    ax2.legend(loc='upper right', facecolor='#333', labelcolor='white', fontsize=9)
else:
    ax2.text(0.5, 0.5, 'ID1 펄스 미감지', transform=ax2.transAxes,
             color='#F44336', fontsize=14, ha='center', va='center')
ax2.set_ylabel('전압 (V)', color='white')
ax2.set_xlabel('시간 (us)', color='white')

# ── Plot 3: ID3 펄스 확대 ─────────────────────────────────
ax3 = axes[2]
id3_pulses = [(f_,e_,w) for f_,e_,w in pulses if abs(w-177.37) < 30]
if id3_pulses:
    p = id3_pulses[0]
    center_us = (p[0] + p[1]) / 2 * sample_us
    zoom_us   = 600.0
    z_start   = max(0, int((center_us - zoom_us) / sample_us))
    z_end     = min(N, int((center_us + zoom_us) / sample_us))
    ax3.plot(t_us[z_start:z_end], v[z_start:z_end], color='#E91E63', linewidth=1.2)
    ax3.axvspan(t_us[p[0]], t_us[min(p[1], N-1)], alpha=0.35, color=COLOR_LO, label=f'ID3 LOW = {p[2]:.2f}us')
    ax3.set_xlim(t_us[z_start], t_us[z_end])
    ax3.set_ylim(LOW_V, HIGH_V)
    ax3.set_title(f'ID3 펄스 확대  (목표: 177.37us)', color='#aaa', fontsize=10)
    ax3.annotate(f'{p[2]:.2f} us', xy=(t_us[p[0]], THR), xytext=(t_us[p[0]] + 30, HIGH_V * 0.7),
                 arrowprops=dict(arrowstyle='->', color=COLOR_AN), color=COLOR_AN, fontsize=10)
    ax3.legend(loc='upper right', facecolor='#333', labelcolor='white', fontsize=9)
else:
    ax3.text(0.5, 0.5, 'ID3 펄스 미감지', transform=ax3.transAxes,
             color='#F44336', fontsize=14, ha='center', va='center')
ax3.set_ylabel('전압 (V)', color='white')
ax3.set_xlabel('시간 (us)', color='white')

plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.savefig(img, dpi=150, bbox_inches='tight', facecolor='#1e1e1e')
plt.close()

print(f"\n이미지 저장 완료: {os.path.abspath(img)}")
print(f"\n=== AWG 검증 결과 ===")
print(f"HIGH 레벨 : {v_max:.3f}V")
print(f"LOW  레벨 : {v_min:.3f}V")
print(f"신호 진폭 : {v_max - v_min:.3f}V")
for line in status_lines:
    print(f"  {line}")
print(f"\n종합: {'PASS' if pass_all else 'FAIL'}")
