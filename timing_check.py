import numpy as np
from src.hw_picoscope import PicoScopeHardware

ps = PicoScopeHardware()
ps.open()
ps.setup_channel('B', enabled=True, range_str='10V', probe_str='x10')
ps.setup_channel('C', enabled=True, range_str='10V', probe_str='x10')
ps.setup_channel('D', enabled=True, range_str='10V', probe_str='x10')
ps.setup_awg_multi_pulse([1, 3])
data = ps.capture_block(['B','C','D'], trigger_awg=True)
ps.close()

sample_us = 1e6 / ps.sample_rate_hz
total_us = len(data['B']) * sample_us
print(f"Sample rate: {ps.sample_rate_hz/1e6:.3f} MS/s")
print(f"Sample interval: {sample_us:.4f} us")
print(f"Total capture: {total_us/1000:.2f} ms")
print()

for ch in ['B', 'C', 'D']:
    v = data[ch]
    THR = (v.max() + v.min()) / 2.0
    is_low = v < THR
    fe = np.where((~is_low[:-1]) & is_low[1:])[0]
    re = np.where(is_low[:-1] & (~is_low[1:]))[0]

    print(f"=== Channel {ch} ===")
    print(f"  max={v.max():.2f}V  min={v.min():.2f}V  THR={THR:.2f}V")
    print(f"  falling edges: {len(fe)}")

    if ch in ['B', 'C']:
        periods = np.diff(fe) * sample_us
        sync_periods = periods[(periods > 100) & (periods < 250)]
        if len(sync_periods):
            avg_sync = float(np.mean(sync_periods))
            ut = avg_sync / 56.0
            # 1 frame: sync + 8 nibbles (avg 20 ticks each) = sync + 160 ticks
            frame_time = avg_sync + 8 * 20 * ut
            print(f"  Sync period: {avg_sync:.1f} us")
            print(f"  UT: {ut:.3f} us")
            print(f"  Est. frame time: {frame_time:.0f} us")
            print(f"  SENT min capture (2 frames): {frame_time*2:.0f} us = {frame_time*2/1000:.2f} ms")

    if ch == 'D':
        pulses = []
        for f in fe:
            vr = re[re > f]
            if len(vr):
                w = (vr[0] - f) * sample_us
                pulses.append((f * sample_us, w))

        awg_pulses = [(s, w) for s, w in pulses if w > 30]
        resp_pulses = [(s, w) for s, w in pulses if w < 30]

        print(f"  AWG trigger pulses:")
        for s, w in awg_pulses:
            print(f"    start={s:.1f}us  width={w:.1f}us")

        if awg_pulses:
            last_end = awg_pulses[-1][0] + awg_pulses[-1][1]
            print(f"  Last AWG ends at: {last_end:.1f} us")

        if resp_pulses:
            last_resp = resp_pulses[-1][0]
            print(f"  Response pulses: {len(resp_pulses)} (decoder needs 8 per ID)")
            print(f"  Last response at: {last_resp:.1f} us")
            print(f"  SPC min capture: {last_resp + 300:.0f} us = {(last_resp+300)/1000:.2f} ms")

        # Falling edge periods within each response window
        if len(awg_pulses) >= 2:
            id1_end = awg_pulses[0][0] + awg_pulses[0][1]
            id3_start = awg_pulses[1][0]
            id3_end = awg_pulses[1][0] + awg_pulses[1][1]

            id1_resp = [s for s, w in resp_pulses if id1_end < s < id3_start]
            id3_resp = [s for s, w in resp_pulses if s > id3_end]

            print(f"\n  ID1 response: {len(id1_resp)} edges (window {id1_end:.0f}~{id3_start:.0f} us)")
            if len(id1_resp) >= 2:
                periods_id1 = np.diff(id1_resp)
                print(f"    Periods: {[f'{p:.1f}' for p in periods_id1]}")

            print(f"  ID3 response: {len(id3_resp)} edges (window {id3_end:.0f}~ us)")
            if len(id3_resp) >= 2:
                periods_id3 = np.diff(id3_resp)
                print(f"    Periods: {[f'{p:.1f}' for p in periods_id3]}")
    print()
