import numpy as np

# SENT CRC-4 lookup table
# Polynomial: x^4 + x^3 + x^2 + 1 (SAE J2716), Seed: 0101b = 5
# Covers STATUS nibble + all DATA nibbles
_CRC_TABLE = [0, 13, 7, 10, 14, 3, 9, 4, 1, 12, 6, 11, 15, 2, 8, 5]

# Status nibble bit field definitions
# Bits [3:2]: state  — 00=Normal, 01=Overvoltage, 10=Startup
# Bits [1:0]: range  — 11=±50mT, 01=±100mT, 00=±200mT
_STATUS_STATE  = {0b00: "Normal", 0b01: "Overvoltage", 0b10: "Startup", 0b11: "Unknown"}
_STATUS_RANGE  = {0b11: "±50mT",  0b01: "±100mT",     0b00: "±200mT",  0b10: "Unknown"}


class SENTDecoder:
    """
    SENT Protocol Decoder for TLE4998S8D (8PCA00020A_PCB Assy).

    Frame format (F=0, default — 16-bit Hall + 8-bit Temperature):
        SYNC(56UT) | STATUS | H1 | H2 | H3 | H4 | T1 | T2 | CRC
                              D1   D2   D3   D4   D5   D6

    Hall 16-bit  : OUT16 = H1×4096 + H2×256 + H3×16 + H4   (0…65535, midscale=32768 at 0 mT)
    Temperature  : TEMP8 = T1×16 + T2                        (0…255, approx 1 °C/LSB, 0°C≈55)
    Temperature°C: T ≈ TEMP8 − 55
    UT nominal   : 3 µs  (56×UT = 168 µs sync pulse, tolerance ±20%)
    CRC          : 4-bit, poly x^4+x^3+x^2+1, seed=5, covers STATUS+D1-D6
    """

    def __init__(self, sample_rate_hz: float = 10e6, nominal_ut_us: float = 3.0):
        self.sample_rate_hz  = sample_rate_hz
        self.sample_time_us  = (1.0 / sample_rate_hz) * 1e6
        self.nominal_ut_us   = nominal_ut_us

    # ------------------------------------------------------------------
    # Edge detection
    # ------------------------------------------------------------------
    def find_falling_edges(self, voltage_array, threshold: float = 2.5):
        """Return indices where signal transitions HIGH→LOW."""
        is_low = voltage_array < threshold
        return np.where((~is_low[:-1]) & is_low[1:])[0]

    # ------------------------------------------------------------------
    # CRC
    # ------------------------------------------------------------------
    @staticmethod
    def calculate_crc(nibbles) -> int:
        """
        Compute SENT CRC-4 over the given nibble list.
        nibbles should be [STATUS, D1, D2, D3, D4, D5, D6]  (7 nibbles).
        Returns the expected 4-bit CRC value.
        """
        crc = 5  # seed = 0101b
        for n in nibbles:
            crc = _CRC_TABLE[crc ^ int(n)]
        return crc

    # ------------------------------------------------------------------
    # Frame decode
    # ------------------------------------------------------------------
    def decode_frame(self, voltage_array, threshold: float = 2.5) -> dict:
        """
        Decode a single SENT frame from voltage_array.

        Returns a dict with:
            status         : "success" | "error"
            sync_period_us : measured sync pulse length (µs)
            measured_ut_us : actual UT derived from sync pulse (µs)
            status_nibble  : raw 4-bit status value
            status_state   : "Normal" | "Overvoltage" | "Startup"
            status_range   : "±50mT" | "±100mT" | "±200mT"
            data_nibbles   : list[int] — [H1,H2,H3,H4,T1,T2]
            hall_raw       : 16-bit unsigned Hall value (0…65535, 32768=zero field)
            hall_offset    : Hall value relative to midscale (−32768…+32767)
            temp_raw       : 8-bit temperature code (0…255)
            temp_celsius   : approximate die temperature (°C)
            crc_nibble     : received CRC nibble
            crc_expected   : computed CRC nibble
            crc_valid      : bool
        """
        edges = self.find_falling_edges(voltage_array, threshold)
        if len(edges) < 9:  # need sync + 8 nibble edges
            return {"status": "error",
                    "message": f"Too few edges ({len(edges)}) for a SENT frame"}

        periods_samples = np.diff(edges)
        periods_us      = periods_samples * self.sample_time_us

        # --- Sync pulse detection (56×UT, ±20% tolerance) ---
        sync_target_us = 56.0 * self.nominal_ut_us   # default 168 µs
        tolerance_us   = sync_target_us * 0.20

        sync_index = -1
        for i, p_us in enumerate(periods_us):
            if abs(p_us - sync_target_us) <= tolerance_us:
                sync_index = i
                break

        if sync_index == -1:
            return {"status": "error",
                    "message": f"Sync not found (looking for {sync_target_us:.0f}±{tolerance_us:.0f} µs). "
                               f"Shortest periods: {sorted(periods_us[:20])[:5]}"}

        actual_ut_us = periods_us[sync_index] / 56.0

        # --- Check enough nibbles remain ---
        remaining = len(periods_us) - sync_index - 1
        if remaining < 8:
            return {"status": "error",
                    "message": f"Incomplete frame: only {remaining} nibbles after sync (need 8)"}

        # --- Decode 8 nibbles (STATUS + H1..H4 + T1..T2 + CRC) ---
        raw_us = periods_us[sync_index + 1 : sync_index + 9]
        nibble_values = [int(round(p / actual_ut_us)) - 12 for p in raw_us]

        # Validate range 0…15
        for i, nv in enumerate(nibble_values):
            if nv < 0 or nv > 15:
                return {"status": "error",
                        "message": f"Nibble[{i}] out of range: {nv} (actual_ut={actual_ut_us:.3f} µs)",
                        "measured_ut_us": actual_ut_us}

        status_nibble = nibble_values[0]
        data_nibbles  = nibble_values[1:7]   # H1 H2 H3 H4 T1 T2
        crc_nibble    = nibble_values[7]

        # --- Status nibble decode ---
        state_bits = (status_nibble >> 2) & 0x3
        range_bits =  status_nibble       & 0x3

        # --- 16-bit Hall reconstruction ---
        H1, H2, H3, H4 = data_nibbles[0], data_nibbles[1], data_nibbles[2], data_nibbles[3]
        hall_raw    = (H1 << 12) | (H2 << 8) | (H3 << 4) | H4   # 0…65535
        hall_offset = hall_raw - 32768                            # −32768…+32767

        # --- 8-bit Temperature reconstruction ---
        T1, T2   = data_nibbles[4], data_nibbles[5]
        temp_raw  = (T1 << 4) | T2          # 0…255  (0°C≈55, 25°C≈80, ~1°C/LSB)
        temp_c    = temp_raw - 55           # approx °C (not calibrated per datasheet)

        # --- CRC check ---
        crc_expected = self.calculate_crc([status_nibble] + data_nibbles)
        crc_valid    = (crc_nibble == crc_expected)

        return {
            "status":          "success",
            "sync_period_us":  float(periods_us[sync_index]),
            "measured_ut_us":  float(actual_ut_us),
            "status_nibble":   status_nibble,
            "status_state":    _STATUS_STATE.get(state_bits, "Unknown"),
            "status_range":    _STATUS_RANGE.get(range_bits, "Unknown"),
            "data_nibbles":    data_nibbles,
            "hall_raw":        hall_raw,
            "hall_offset":     hall_offset,
            "temp_raw":        temp_raw,
            "temp_celsius":    temp_c,
            "crc_nibble":      crc_nibble,
            "crc_expected":    crc_expected,
            "crc_valid":       crc_valid,
            # CSV 저장용 트리밍 범위 (샘플 인덱스)
            # trim_start : SYNC 펄스 하강 엣지 (주기 시작)
            # trim_end   : 다음 SYNC 펄스 하강 엣지 (주기 종료) → 판정에 사용된 구간과 정확히 일치
            "trim_start": int(edges[sync_index]),
            "trim_end":   int(edges[sync_index + 1]),
        }
