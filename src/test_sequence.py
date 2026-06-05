import numpy as np
from src.hw_picoscope import PicoScopeHardware
from src.decoder_analog import AnalogAnalyzer
from src.decoder_sent import SENTDecoder
from src.decoder_spc import SPCDecoder

class TestSequencer:
    """
    Orchestrates the universal channel-based test sequence.
    """
    def __init__(self, hw: PicoScopeHardware):
        self.hw = hw
        self.analog = AnalogAnalyzer(sample_rate_hz=hw.sample_rate_hz)
        self.sent = SENTDecoder(sample_rate_hz=hw.sample_rate_hz, nominal_ut_us=3.0)
        self.spc = SPCDecoder(sample_rate_hz=hw.sample_rate_hz)
        self.last_capture = {}  # 마지막 캡처 데이터 보관 (GUI 파형 표시용)
        self._spc_warmed_up = False  # 프로그램 시작 후 SPC 첫 실행 여부

    def run_universal_test(self, channel_config, awg_invert=False):
        """
        Runs the test based on the channel_config dictionary.
        channel_config format: {'A': {'mode': 'SPC/1/3', 'range':...}, 'B': {'mode': 'Analog VDD',...}}
        awg_invert: True이면 AWG 파형을 반전 (N채널 MOSFET 드라이브 시 사용)
        Returns a dictionary of results per channel.
        """
        results = {}
        active_channels = list(channel_config.keys())
        if not active_channels:
            return results
            
        # 1. Determine required AWG sequence for SPC
        spc_ids = set()
        has_spc = False
        for cfg in channel_config.values():
            mode = cfg.get('mode', '')
            if mode.startswith('SPC'):
                has_spc = True
                # UI 형식: "SPC (ID 1)", "SPC (ID 3)" → 숫자 추출
                import re
                nums = re.findall(r'\d+', mode)
                for n in nums:
                    spc_ids.add(int(n))
                        
        spc_id_list = sorted(list(spc_ids))
        
        # 2. Program AWG and Capture ALL channels in ONE shot
        import time
        if has_spc:
            self.hw.setup_awg_multi_pulse(spc_id_list, invert=awg_invert)

            if not self._spc_warmed_up:
                # ── 첫 실행 워밍업 (2회) ──────────────────────────────────
                # 프로그램 시작 후 첫 SPC 트리거 시 센서가 응답하지 않는 하드웨어
                # 특성 대응: 워밍업 2회로 버스 동기화를 보장함
                print("[SPC] 첫 실행 워밍업 시작 (2회)...")
                self.hw.capture_block(active_channels, trigger_awg=True, awg_ids=spc_id_list)
                time.sleep(0.1)   # 100ms: 첫 번째 트리거 후 센서 안정화
                self.hw.capture_block(active_channels, trigger_awg=True, awg_ids=spc_id_list)
                time.sleep(0.1)   # 100ms: 두 번째 트리거 후 안정화
                self._spc_warmed_up = True
                print("[SPC] 워밍업 완료 — 실제 검사 시작")
                # ────────────────────────────────────────────────────────
            else:
                # ── 이후 실행 워밍업 (1회) ───────────────────────────────
                self.hw.capture_block(active_channels, trigger_awg=True, awg_ids=spc_id_list)
                time.sleep(0.05)  # 50ms
                # ────────────────────────────────────────────────────────

            # 실제 검사 캡처
            data = self.hw.capture_block(active_channels, trigger_awg=True, awg_ids=spc_id_list)
        else:
            data = self.hw.capture_block(active_channels, trigger_awg=False)

        self.last_capture = data  # GUI 파형 표시용으로 보관


        # 캡처 후 실제 샘플레이트로 디코더 갱신 (하드웨어에서 GetTimebase로 읽은 값)
        actual_sr = self.hw.sample_rate_hz
        self.sent = SENTDecoder(sample_rate_hz=actual_sr, nominal_ut_us=3.0)
        self.spc  = SPCDecoder(sample_rate_hz=actual_sr)

        # 3. Decode each channel based on its mode
        # First group Analog pairs
        analog_pairs = {} # {vdd_ch: vout_ch}
        for ch, cfg in channel_config.items():
            if cfg['mode'] == "Analog VDD":
                # Find matching VOUT in the same product. 
                # (Assuming they are passed together, but let's just find any VOUT for now, 
                # actually it's better to just decode VDD standalone, but AnalogAnalyzer needs both?)
                # Actually, AnalogAnalyzer in our implementation needs (vdd_data, vout_data).
                # To be safe, let's just analyze them independently if they aren't paired perfectly.
                pass

        # Since AnalogAnalyzer needs both, let's find pairs by assuming A+B, C+D, E+F are pairs
        for ch in active_channels:
            mode = channel_config[ch]['mode']
            
            if mode.upper().startswith("ANALOG"):
                v_mean = float(data[ch].mean())
                v_ac = data[ch] - v_mean
                p2p_noise = float(np.max(data[ch]) - np.min(data[ch]))
                rms_noise = float(np.sqrt(np.mean(v_ac**2)))
                
                results[ch] = {
                    "status": "success",
                    "v_mean": v_mean,
                    "p2p_noise": p2p_noise,
                    "rms_noise": rms_noise,
                    "pass": True # Temporary, finalized at product level
                }
                
            elif mode == "SENT":
                # TOS 판정: UT = 3µs ± 20% (2.4 ~ 3.6µs)
                res = self.sent.decode_frame(data[ch])
                if res['status'] == 'success':
                    ut = res.get('measured_ut_us', 0)
                    res['pass'] = (2.4 <= ut <= 3.6)
                    if not res['pass']:
                        res['message'] = f"UT={ut:.3f}µs — 범위 초과 (2.4~3.6µs)"
                else:
                    res['pass'] = False
                results[ch] = res
                
            elif mode.startswith("SPC"):
                # UI 형식: "SPC (ID 1)", "SPC (ID 3)" → 숫자 추출
                import re
                requested_ids = [int(n) for n in re.findall(r'\d+', mode)]
                if not requested_ids:
                    requested_ids = [1]  # fallback
                    
                res = self.spc.decode_multi_spc_frames(data[ch], requested_ids)
                results[ch] = res

        return results
