import csv
import time
from pathlib import Path

import pyvisa


RESOURCE = "USB0::0x2A8D::0x0101::MY64045156::0::INSTR"

LOW_LIMIT = 2.400
HIGH_LIMIT = 2.600

SAMPLE_COUNT = 1000
SAMPLE_INTERVAL = 50e-6      # 50 us
APERTURE = 40e-6             # 40 us
DMM_RANGE = 10               # 10 V range


def query_error(inst, label=""):
    err = inst.query("SYST:ERR?").strip()
    print(f"{label}SYST:ERR? -> {err}")
    return err


def is_no_error(err: str) -> bool:
    return err.startswith("+0") or err.startswith("0")


def main():
    rm = pyvisa.ResourceManager()
    print("Available VISA resources:")
    for r in rm.list_resources():
        print("  ", r)

    print("\nOpening:", RESOURCE)
    inst = rm.open_resource(RESOURCE)
    inst.timeout = 20000

    try:
        print("\n--- ID CHECK ---")
        idn = inst.query("*IDN?").strip()
        print("*IDN? ->", idn)

        opt = inst.query("*OPT?").strip()
        print("*OPT? ->", opt)

        print("\n--- RESET / CONFIGURE ---")
        inst.write("*RST")
        inst.write("*CLS")

        # Basic DC voltage setting
        inst.write(f"CONF:VOLT:DC {DMM_RANGE}")
        inst.write(f"VOLT:DC:RANG {DMM_RANGE}")
        inst.write("VOLT:DC:RANG:AUTO OFF")

        # High-speed setting
        inst.write("VOLT:DC:ZERO:AUTO OFF")
        inst.write(f"VOLT:DC:APER {APERTURE}")

        # Trigger and sampling setting
        inst.write("TRIG:SOUR BUS")
        inst.write("TRIG:DEL 0")
        inst.write("TRIG:COUN 1")

        inst.write("SAMP:SOUR TIM")
        inst.write(f"SAMP:TIM {SAMPLE_INTERVAL}")
        inst.write(f"SAMP:COUN {SAMPLE_COUNT}")

        # Data transfer format: ASCII first for easy debugging
        inst.write("FORM:DATA ASC")

        print("\n--- READBACK CHECK ---")
        applied_range = inst.query("VOLT:DC:RANG?").strip()
        applied_aper = float(inst.query("VOLT:DC:APER?"))
        sample_source = inst.query("SAMP:SOUR?").strip()
        applied_timer = float(inst.query("SAMP:TIM?"))
        applied_count = int(float(inst.query("SAMP:COUN?")))

        print(f"VOLT:DC:RANG? -> {applied_range}")
        print(f"VOLT:DC:APER? -> {applied_aper:.9f} s = {applied_aper * 1e6:.3f} us")
        print(f"SAMP:SOUR?    -> {sample_source}")
        print(f"SAMP:TIM?     -> {applied_timer:.9f} s = {applied_timer * 1e6:.3f} us")
        print(f"SAMP:COUN?    -> {applied_count}")

        err = query_error(inst, label="After config: ")
        if not is_no_error(err):
            print("\nCONFIG ERROR: 설정 오류가 있습니다. 아래 출력 내용을 보내주세요.")
            return

        if abs(applied_aper - APERTURE) > 2e-6:
            print("\nFAIL: 40 us aperture가 정확히 적용되지 않았습니다.")
            return

        if abs(applied_timer - SAMPLE_INTERVAL) > 2e-6:
            print("\nFAIL: 50 us sample interval이 정확히 적용되지 않았습니다.")
            return

        if applied_count != SAMPLE_COUNT:
            print("\nFAIL: sample count가 1000으로 적용되지 않았습니다.")
            return

        print("\nSETTING CHECK: PASS")
        print("\n이제 DMM 입력에 측정할 신호를 연결하세요.")
        input("준비되면 Enter를 누르세요...")

        print("\n--- ACQUIRE 1000 SAMPLES ---")
        inst.write("*CLS")
        inst.write("INIT")
        inst.write("*TRG")
        inst.write("*WAI")

        points = int(float(inst.query("DATA:POIN?")))
        print("DATA:POIN? ->", points)

        if points != SAMPLE_COUNT:
            print(f"FAIL: expected {SAMPLE_COUNT} points, got {points}")
            query_error(inst, label="After acquisition: ")
            return

        raw = inst.query("FETC?").strip()
        values = [float(x) for x in raw.split(",") if x.strip()]

        print("Received samples:", len(values))

        if len(values) != SAMPLE_COUNT:
            print(f"FAIL: expected {SAMPLE_COUNT} values, got {len(values)}")
            return

        v_min = min(values)
        v_max = max(values)
        v_avg = sum(values) / len(values)

        out_indexes = [
            i for i, v in enumerate(values)
            if v < LOW_LIMIT or v > HIGH_LIMIT
        ]

        passed = len(out_indexes) == 0

        print("\n--- RESULT ---")
        print(f"MIN  = {v_min:.9f} V")
        print(f"MAX  = {v_max:.9f} V")
        print(f"AVG  = {v_avg:.9f} V")
        print(f"OUT-OF-RANGE COUNT = {len(out_indexes)}")
        if out_indexes:
            print(f"FIRST FAIL INDEX = {out_indexes[0]}, VALUE = {values[out_indexes[0]]:.9f} V")

        print("TEMP RESULT =", "PASS" if passed else "FAIL")

        out_path = Path("34465A_TOS_TEST_RESULT.csv")
        with out_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["index", "voltage_V", "pass_2p4_to_2p6"])
            for i, v in enumerate(values):
                writer.writerow([i, f"{v:.9f}", LOW_LIMIT <= v <= HIGH_LIMIT])

        print(f"\nCSV saved: {out_path.resolve()}")

        query_error(inst, label="Final: ")

    finally:
        inst.close()
        rm.close()


if __name__ == "__main__":
    main()
