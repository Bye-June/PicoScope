"""
SPC (Short PWM Code) Decoder for HAR3970-2301.

판정 기준 (TAS 규격):
    SAS output: SPC 응답의 Unit Time (UT) = 2.75µs ± 5%  (2.6125 ~ 2.8875µs)

트리거 펄스 (AWG 발사 기준):
    ID1: 57.75µs  (52.25 ~ 63.25µs 범위가 센서 수신 유효)
    ID3: 177.37µs (169.12 ~ 185.62µs 범위가 센서 수신 유효)

동작:
    1. AWG 트리거 펄스(ID별 폭)를 캡처 파형에서 찾는다
    2. 트리거 후 센서 응답의 첫 Sync 펄스(56 × UT)를 찾는다
    3. UT = sync_period / 56 을 계산한다
    4. UT가 2.75µs ± 5% 범위이면 PASS
"""

import numpy as np


# 판정 기준 (TAS 규격)
UT_NOM_US      = 2.75          # SPC nominal UT
UT_TOL_RATIO   = 0.03          # ±3%  (문서: SENT SPC Unit Time 측정 방법_260609)
UT_MIN_US      = UT_NOM_US * (1 - UT_TOL_RATIO)   # 2.6675
UT_MAX_US      = UT_NOM_US * (1 + UT_TOL_RATIO)   # 2.8325

# AWG 트리거 펄스 규격
TRIGGER_SPEC = {
    1: {"nom_us": 57.75,  "min_us": 52.25,  "max_us": 63.25},
    3: {"nom_us": 177.37, "min_us": 169.12, "max_us": 185.62},
}

# Sync 펄스 = 56 UT (범위 ±20% 허용)
SYNC_TICKS   = 56
SYNC_TOL     = 0.20


class SPCDecoder:
    """
    SPC Unit Time 측정 기반 디코더.
    전체 SENT 프레임 디코딩 없이 Sync 주기로 UT만 측정하여 판정.
    """

    def __init__(self, sample_rate_hz: float = 9.766e6):
        self.sample_rate_hz = sample_rate_hz
        self.sample_us      = 1e6 / sample_rate_hz

    # ------------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------------
    def _find_edges(self, voltage_array, threshold):
        is_low = voltage_array < threshold
        fe = np.where((~is_low[:-1]) & is_low[1:])[0]
        re = np.where(is_low[:-1] & (~is_low[1:]))[0]
        return fe, re

    def _build_pulses(self, fe, re):
        """falling edge → 다음 rising edge → (start_idx, end_idx, width_us)"""
        pulses = []
        for f in fe:
            vr = re[re > f]
            if len(vr):
                pulses.append((int(f), int(vr[0]), (vr[0] - f) * self.sample_us))
        return pulses

    def _find_sync(self, fe, re, start_idx):
        """
        start_idx 이후에서 Sync 펄스(≈ 56×UT)를 찾는다.
        반환: (sync_period_us, ut_us, sync_start_sample, sync_end_sample) 또는 None
        sync_start_sample : Sync 페리어 시작 하강 엣지의 절대 샘플 인덱스
        sync_end_sample   : Sync 페리어 종료(다음 하강 엣지)의 절대 샘플 인덱스
        """
        response_fe = fe[fe >= start_idx]
        if len(response_fe) < 2:
            return None

        periods_us = np.diff(response_fe) * self.sample_us
        sync_nom   = SYNC_TICKS * UT_NOM_US         # 2.75 × 56 = 154µs
        sync_min   = sync_nom * (1 - SYNC_TOL)
        sync_max   = sync_nom * (1 + SYNC_TOL)

        for i, p in enumerate(periods_us):
            if sync_min <= p <= sync_max:
                ut = p / SYNC_TICKS
                return float(p), float(ut), int(response_fe[i]), int(response_fe[i + 1])

        return None

    # ------------------------------------------------------------------
    # 메인 API
    # ------------------------------------------------------------------
    def decode_multi_spc_frames(self, voltage_array, requested_ids, threshold=2.5):
        """
        캡처 파형에서 요청된 ID별 SPC 트리거를 찾고 UT를 측정하여 판정.

        반환 형식:
            {
                "pass"   : bool,
                "status" : "success" | "error",
                "details": {
                    "ID1": { "pass": bool, "measured_ut_us": float, ... },
                    "ID3": { ... }
                }
            }
        """
        fe, re = self._find_edges(voltage_array, threshold)
        pulses = self._build_pulses(fe, re)

        results  = {}
        all_pass = True

        for spc_id in sorted(requested_ids):
            spec = TRIGGER_SPEC.get(spc_id)
            if spec is None:
                results[f"ID{spc_id}"] = {
                    "pass": False, "status": "error",
                    "message": f"ID{spc_id}: 지원하지 않는 ID"
                }
                all_pass = False
                continue

            # 1) 트리거 펄스 탐색
            trig_found = None
            for p in pulses:
                if spec["min_us"] <= p[2] <= spec["max_us"]:
                    trig_found = p
                    break

            if trig_found is None:
                results[f"ID{spc_id}"] = {
                    "pass": False, "status": "error",
                    "message": f"ID{spc_id} 트리거 펄스를 찾을 수 없음 (탐색 범위: {spec['min_us']}~{spec['max_us']}µs)",
                    "trigger_width_us": None,
                }
                all_pass = False
                continue

            trig_start, trig_end, trig_width = trig_found

            # 2) 트리거 이후 첫 Sync 탐색
            sync_result = self._find_sync(fe, re, trig_end)

            if sync_result is None:
                results[f"ID{spc_id}"] = {
                    "pass": False, "status": "error",
                    "message": f"ID{spc_id}: 센서 응답에서 Sync 펄스를 찾을 수 없음",
                    "trigger_width_us": float(trig_width),
                }
                all_pass = False
                continue

            sync_period_us, measured_ut_us, sync_start_smp, sync_end_smp = sync_result

            # 3) UT 범위 판정
            ut_pass = (UT_MIN_US <= measured_ut_us <= UT_MAX_US)

            # CSV 저장용 트리밍 범위 (ID별 독립)
            sync_margin = int(UT_NOM_US * 3.0 / self.sample_us)

            result = {
                "pass"            : ut_pass,
                "status"          : "success" if ut_pass else "error",
                "trigger_width_us": float(trig_width),
                "sync_period_us"  : sync_period_us,
                "measured_ut_us"  : measured_ut_us,
                "ut_min_us"       : UT_MIN_US,
                "ut_max_us"       : UT_MAX_US,
                "ut_nom_us"       : UT_NOM_US,
                "ut_error_pct"    : round((measured_ut_us - UT_NOM_US) / UT_NOM_US * 100, 2),
                "trim_start"      : sync_start_smp,
                "trim_end"        : sync_end_smp + sync_margin,
            }

            if not ut_pass:
                result["message"] = (
                    f"ID{spc_id}: UT={measured_ut_us:.3f}µs — "
                    f"범위 초과 ({UT_MIN_US}~{UT_MAX_US}µs)"
                )
                all_pass = False

            results[f"ID{spc_id}"] = result

        return {
            "pass"   : all_pass,
            "status" : "success" if all_pass else "error",
            "details": results,
        }
