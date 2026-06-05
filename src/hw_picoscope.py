import numpy as np
import time
import ctypes
import os

# PicoScope 7 DLL 경로를 환경 변수에 동적으로 추가
pico_path = r"C:\Program Files\Pico Technology\PicoScope 7 T&M Stable"
if os.path.exists(pico_path):
    os.environ["PATH"] = pico_path + os.pathsep + os.environ.get("PATH", "")

try:
    from picosdk.ps6000a import ps6000a as ps
    from picosdk.functions import assert_pico_ok, adc2mV
    from picosdk.PicoDeviceEnums import picoEnum
    PICOSDK_AVAILABLE = True
except Exception as e:
    PICOSDK_AVAILABLE = False
    print(f"Warning: PicoSDK not found or DLL missing ({e}).")

# AWG 함수는 picosdk 래퍼가 uint64 인자를 지원하지 않아 DLL 직접 바인딩 사용
# (debug_awg_image.py와 동일한 방식)
_dll = None
_wave_fn = _range_fn = _freq_fn = _trig_fn = _apply_fn = _soft_fn = None

def _init_awg_dll():
    global _dll, _wave_fn, _range_fn, _freq_fn, _trig_fn, _apply_fn, _soft_fn
    if _dll is not None:
        return True
    dll_path = r"C:\Program Files\Pico Technology\PicoScope 7 T&M Stable\ps6000a.dll"
    if not os.path.exists(dll_path):
        return False
    try:
        _dll = ctypes.WinDLL(dll_path)
        def B(fn, ret, args):
            f = getattr(_dll, fn); f.restype = ret; f.argtypes = args; return f
        _wave_fn  = B('ps6000aSigGenWaveform',  ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint64])
        _range_fn = B('ps6000aSigGenRange',     ctypes.c_uint32, [ctypes.c_int16, ctypes.c_double, ctypes.c_double])
        _freq_fn  = B('ps6000aSigGenFrequency', ctypes.c_uint32, [ctypes.c_int16, ctypes.c_double])
        _trig_fn  = B('ps6000aSigGenTrigger',   ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64])
        _apply_fn = B('ps6000aSigGenApply',     ctypes.c_uint32, [ctypes.c_int16, ctypes.c_int16, ctypes.c_int16, ctypes.c_int16, ctypes.c_int16, ctypes.c_int16, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p])
        _soft_fn  = B('ps6000aSigGenSoftwareTriggerControl', ctypes.c_uint32, [ctypes.c_int16, ctypes.c_uint32])
        return True
    except Exception as ex:
        print(f"[AWG] DLL 직접 바인딩 실패: {ex}")
        return False


class PicoScopeHardware:
    """
    Hardware abstraction for PicoScope 6804E (ps6000a API).
    Includes a simulation mode for development without hardware.
    """
    def __init__(self):
        self.handle = ctypes.c_int16()
        self.is_open = False
        self.sim_mode = False  # Only enabled via 'No Scope' checkbox
        self.num_samples = 30000  # 30,000 samples @ ~10MS/s = ~3ms capture (SPC 2.2ms + 여유)
        self.sample_rate_hz = 10_000_000  # ~10 MS/s (PicoScope shows ~9.77 MS/s at TB~10)
        self._channel_settings = {} # Store { ch: {'range_mv': 5000.0, 'probe': 1} }

    def open(self):
        if self.sim_mode:
            print("[SIM] PicoScope Opened")
            self.is_open = True
            return True, "SIM-6804E", "SIM-12345"

        if not PICOSDK_AVAILABLE:
            print("[ERROR] PicoSDK not available. Cannot connect to oscilloscope.")
            return False, "", ""

        status = ps.ps6000aOpenUnit(ctypes.byref(self.handle), None, picoEnum.PICO_DEVICE_RESOLUTION["PICO_DR_8BIT"])
        if status != 0:
            return False, "", ""
        
        self.is_open = True
        model = self.get_device_info(picoEnum.PICO_INFO["PICO_VARIANT_INFO"])
        serial = self.get_device_info(picoEnum.PICO_INFO["PICO_BATCH_AND_SERIAL"])
        return True, model, serial

    def get_device_info(self, info_type):
        if self.sim_mode:
            return "Simulated"
        
        string_buffer = ctypes.create_string_buffer(256)
        required_size = ctypes.c_int16(0)
        status = ps.ps6000aGetUnitInfo(self.handle, string_buffer, 256, ctypes.byref(required_size), info_type)
        if status == 0:
            return string_buffer.value.decode('utf-8')
        return "Unknown"

    def close(self):
        if not self.is_open:
            return
        if self.sim_mode:
            print("[SIM] PicoScope Closed")
        else:
            ps.ps6000aCloseUnit(self.handle)
        self.is_open = False

    def setup_channel(self, channel: str, enabled: bool = True, range_str: str = "±5V", probe_str: str = "x10", bw_limit_str: str = "20MHz"):
        # Parse range and probe
        # Hardware mapping
        # 2: 50mV, 3: 100mV, 4: 200mV, 5: 500mV, 6: 1V, 7: 2V, 8: 5V, 9: 10V, 10: 20V
        HW_RANGES = [
            (2, 50.0), (3, 100.0), (4, 200.0), (5, 500.0),
            (6, 1000.0), (7, 2000.0), (8, 5000.0), (9, 10000.0), (10, 20000.0)
        ]
        
        # Parse target signal range
        try:
            val_str = range_str.replace("±", "").replace("mV", "").replace("V", "")
            target_v = float(val_str)
            if "mV" in range_str:
                target_mv = target_v
            else:
                target_mv = target_v * 1000.0
        except:
            target_mv = 5000.0

        probe_scale = 10 if probe_str == "x10" else 1
        
        # Calculate required hardware range at the BNC
        hw_target_mv = target_mv / probe_scale
        
        # Find the smallest hardware range that can cover the hw_target_mv
        range_enum_val = 8 # Default to 5V
        range_mv = 5000.0
        for enum_val, mv in HW_RANGES:
            if mv >= (hw_target_mv - 0.1): # tiny tolerance
                range_enum_val = enum_val
                range_mv = mv
                break
                
        self._channel_settings[channel] = {'range_mv': range_mv, 'probe': probe_scale}

        if self.sim_mode:
            print(f"[SIM] Ch {channel} setup: enabled={enabled}, range={range_str}, probe={probe_str}")
            return

        ch_enum = picoEnum.PICO_CHANNEL[f"PICO_CHANNEL_{channel}"]
        bw_limit = picoEnum.PICO_BANDWIDTH_LIMITER["PICO_BW_20MHZ"] if bw_limit_str == "20MHz" else picoEnum.PICO_BANDWIDTH_LIMITER["PICO_BW_FULL"]
        coupling = picoEnum.PICO_COUPLING["PICO_DC"]
        
        status = ps.ps6000aSetChannelOn(
            self.handle, ch_enum, coupling, range_enum_val, 0.0, bw_limit
        )
        assert_pico_ok(status)

    def setup_awg_multi_pulse(self, spc_ids, invert=False):
        if self.sim_mode:
            return

        # ID별 트리거 펄스 길이 (us)
        pulse_lengths_us = {
            0: 12.0,
            1: 57.75,
            2: 90.0,
            3: 177.37
        }

        TOTAL_SAMPLES = 10000
        DAC_FREQ_HZ   = 4_000_000.0   # 4 MHz → 0.25 us/sample
        us_per_sample = 1_000_000.0 / DAC_FREQ_HZ

        # 파형 버퍼 생성 (기본 HIGH = +32767, LOW = -32768)
        waveform = np.ones(TOTAL_SAMPLES, dtype=np.int16) * 32767

        current_start_us = 200.0  # 200µs 초기 HIGH 후 첫 펄스 시작
        for spc_id in spc_ids:
            if spc_id not in pulse_lengths_us:
                continue
            length_us = pulse_lengths_us[spc_id]
            start_idx = int(current_start_us / us_per_sample)
            end_idx   = start_idx + int(length_us / us_per_sample)
            if end_idx < TOTAL_SAMPLES:
                waveform[start_idx:end_idx] = -32768   # LOW (0 V)
            current_start_us += 1000.0   # ID 간 1 ms 간격

        # N채널 MOSFET 사용 시 파형 반전
        # (AWG HIGH → MOSFET ON → 출력 LOW, AWG LOW → MOSFET OFF → 출력 HIGH)
        if invert:
            waveform = np.clip(-waveform.astype(np.int32), -32768, 32767).astype(np.int16)
            print("[AWG] 파형 반전 적용 (MOSFET 모드)")

        c_waveform = (ctypes.c_int16 * TOTAL_SAMPLES)(*waveform)

        if not _init_awg_dll():
            print("[AWG] DLL 직접 바인딩 불가 — AWG 기능 사용 불가")
            return

        H = self.handle.value
        AWG_WAVE_TYPE_ARBITRARY = 0x10000000
        target_freq_hz = DAC_FREQ_HZ / TOTAL_SAMPLES  # 400.0 Hz

        try:
            # 1) 파형 버퍼 업로드 (c_uint64 필수 — picosdk 래퍼는 uint64 미지원)
            st = _wave_fn(H, ctypes.c_uint32(AWG_WAVE_TYPE_ARBITRARY),
                          ctypes.cast(ctypes.byref(c_waveform), ctypes.c_void_p),
                          ctypes.c_uint64(TOTAL_SAMPLES))
            if st != 0: print(f"[AWG] SigGenWaveform status={st}")

            # 2) 전압 범위: pkToPk=5V, offset=2.5V → 0V~5V
            st = _range_fn(H, ctypes.c_double(5.0), ctypes.c_double(2.5))
            if st != 0:
                print(f"[AWG] SigGenRange status={st}")
            else:
                print(f"[AWG] SigGenRange OK (0~5V)")

            # 3) 트리거: SOFT_TRIG(4), RISING(0), 1회
            st = _trig_fn(H, ctypes.c_uint32(0), ctypes.c_uint32(4),
                          ctypes.c_uint64(1), ctypes.c_uint64(0))
            if st != 0: print(f"[AWG] SigGenTrigger status={st}")

            # 4) 재생 주파수
            st = _freq_fn(H, ctypes.c_double(target_freq_hz))
            if st != 0: print(f"[AWG] SigGenFrequency status={st}")

            # 5) Apply
            af = ctypes.c_double(target_freq_hz)
            st = _apply_fn(H, ctypes.c_int16(1), ctypes.c_int16(0), ctypes.c_int16(1),
                           ctypes.c_int16(1), ctypes.c_int16(0),
                           ctypes.cast(ctypes.byref(af), ctypes.c_void_p), None, None, None)
            if st != 0:
                print(f"[AWG] SigGenApply status={st}")
            else:
                print(f"[AWG] Setup OK — IDs={spc_ids}, {TOTAL_SAMPLES}smp @ {af.value:.0f}Hz")

        except Exception as e:
            print(f"[AWG] Setup Error: {e}")


    def capture_block(self, channels, trigger_awg=False, awg_ids=None):
        """
        Block 모드로 1회 캡처합니다. (선택적으로 AWG 트리거 수행)
        """
        if self.sim_mode:
            time.sleep(0.05) # Simulate capture time
            return self._generate_sim_data(channels, mode="block", awg_pulse=trigger_awg, awg_ids=awg_ids)
        
        # --- REAL HARDWARE BLOCK CAPTURE ---
        maxSamples = self.num_samples
        timebase = 20  # 102.4ns/sample = 9.766 MS/s (PicoScope 소프트웨어와 동일: ~9.77 MS/s)

        # --- 실제 샘플 간격 조회 (SENT 디코더 정밀도를 위해 필수) ---
        try:
            time_ns = ctypes.c_double(0.0)
            max_smp = ctypes.c_uint64(0)
            tb_status = ps.ps6000aGetTimebase(
                self.handle, timebase, ctypes.c_uint64(maxSamples),
                ctypes.cast(ctypes.byref(time_ns), ctypes.c_void_p),
                ctypes.cast(ctypes.byref(max_smp), ctypes.c_void_p),
                ctypes.c_uint64(0)
            )
            if tb_status == 0 and time_ns.value > 0:
                self.sample_rate_hz = 1e9 / time_ns.value
                print(f"[HW] Timebase={timebase}: {time_ns.value:.1f}ns/smp -> {self.sample_rate_hz/1e6:.3f} MS/s")
            else:
                # PicoScope 소프트웨어 측정값 기반 폴백: ~9.77 MS/s ≈ 10 MS/s
                self.sample_rate_hz = 10_000_000
                print(f"[HW] GetTimebase failed({tb_status}), using fallback 10 MS/s")
        except Exception as ex:
            self.sample_rate_hz = 10_000_000
            print(f"[HW] GetTimebase error: {ex}, using fallback 10 MS/s")

        buffer_max = {}
        buffer_min = {}
        for i, ch in enumerate(channels):
            ch_enum = picoEnum.PICO_CHANNEL[f"PICO_CHANNEL_{ch}"]
            buffer_max[ch] = (ctypes.c_int16 * maxSamples)()
            buffer_min[ch] = (ctypes.c_int16 * maxSamples)()
            
            # Action: PICO_CLEAR_ALL (0x01) | PICO_ADD (0x02)
            # Only clear all on the very first channel in the list
            action = 3 if i == 0 else 2
            s = ps.ps6000aSetDataBuffers(
                self.handle, ch_enum,
                ctypes.cast(buffer_max[ch], ctypes.c_void_p),
                ctypes.cast(buffer_min[ch], ctypes.c_void_p),
                maxSamples,
                picoEnum.PICO_DATA_TYPE.get("PICO_INT16_T", 0),   # 1 (int16)
                0,                                                  # waveform index
                picoEnum.PICO_RATIO_MODE.get("PICO_RATIO_MODE_RAW", 0),  # 0x80000000
                action
            )
            if s != 0:
                print(f"[HW] SetDataBuffers ch={ch} status={s}")

        timeIndisposedMs = ctypes.c_double()
        status = ps.ps6000aRunBlock(self.handle, 0, maxSamples, timebase, ctypes.byref(timeIndisposedMs), 0, None, None)
        assert_pico_ok(status)

        # AWG 소프트 트리거 발사 (DLL 직접 호출)
        if trigger_awg and _soft_fn is not None:
            H = self.handle.value
            _soft_fn(H, ctypes.c_uint32(0))  # LOW
            _soft_fn(H, ctypes.c_uint32(1))  # HIGH → RISING edge!
            print(f"[AWG] SoftTrigger fired (0->1 RISING edge)")

        ready = ctypes.c_int16(0)
        check = ctypes.c_int16(0)
        while ready.value == check.value:
            ps.ps6000aIsReady(self.handle, ctypes.byref(ready))

        c_maxSamples = ctypes.c_uint64(maxSamples)
        overflow = ctypes.c_int16()
        
        status = ps.ps6000aGetValues(self.handle, 0, ctypes.byref(c_maxSamples), 1, picoEnum.PICO_RATIO_MODE.get("PICO_RATIO_MODE_RAW", 0), 0, ctypes.byref(overflow))
        assert_pico_ok(status)

        # Get ADC limits for conversion
        minADC = ctypes.c_int16()
        maxADC = ctypes.c_int16()
        ps.ps6000aGetAdcLimits(self.handle, picoEnum.PICO_DEVICE_RESOLUTION.get("PICO_DR_8BIT", 0), ctypes.byref(minADC), ctypes.byref(maxADC))
        max_adc_val = float(maxADC.value) if maxADC.value > 0 else 32512.0

        data = {}
        for ch in channels:
            settings = self._channel_settings.get(ch, {'range_mv': 5000.0, 'probe': 1})
            range_v = settings['range_mv'] / 1000.0
            probe_scale = settings['probe']
            
            adc_arr = np.ctypeslib.as_array(buffer_max[ch])
            v_arr = (adc_arr / max_adc_val) * range_v * probe_scale
            data[ch] = v_arr

        return data

    def start_streaming(self, channels):
        """
        Streaming 모드를 시작합니다.
        """
        if self.sim_mode:
            print("[SIM] Streaming Started")
            self._streaming_active = True
            return True
            
        # Real implementation: ps6000aRunStreaming
        return True

    def stop_streaming(self):
        if self.sim_mode:
            print("[SIM] Streaming Stopped")
            self._streaming_active = False
            return
        
        # Real implementation: ps6000aStop
        pass

    def get_streaming_latest_values(self, channels):
        """
        Streaming 중 최신 데이터를 가져옵니다.
        """
        if self.sim_mode:
            if getattr(self, '_streaming_active', False):
                time.sleep(0.05) # Simulate data arrival rate
                return self._generate_sim_data(channels, mode="stream")
            return {ch: np.array([]) for ch in channels}
            
        # Real implementation: ps6000aGetStreamingLatestValues
        return self._generate_sim_data(channels, mode="stream")

    def _generate_sim_data(self, channels, mode="block", awg_pulse=False, awg_ids=None):
        data = {}
        t = np.arange(self.num_samples) / self.sample_rate_hz

        for ch in channels:
            v = np.ones(self.num_samples) * 5.0

            # Streaming 모드일 때는 파형이 계속 흐르는 것처럼 위상을 약간씩 변경
            if mode == "stream":
                phase = time.time() * 10
                v += np.sin(t * 2 * np.pi * 1000 + phase) * 0.1

            # AWG Pulse가 요청된 채널(SPC 등)인 경우 가짜 멀티 펄스 삽입
            if awg_pulse and awg_ids:
                start_idx = 100
                for spc_id in awg_ids:
                    pulse_width = 57.75 if spc_id == 1 else 177.37
                    pulse_samples = int((pulse_width * 1e-6) * self.sample_rate_hz)
                    v[start_idx:start_idx+pulse_samples] = 0.0
                    # 1ms gap
                    start_idx += pulse_samples + int(1e-3 * self.sample_rate_hz)
            elif mode == "block" and not awg_pulse:
                # 일반 Block 모드 (SENT 파형 흉내)
                sync_samples = int(168e-6 * self.sample_rate_hz)
                v[100:100+sync_samples] = 0.0

            v += np.random.normal(0, 0.05, self.num_samples)
            data[ch] = v

        return data

