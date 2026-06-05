import os
pico_path = r"C:\Program Files\Pico Technology\PicoScope 7 T&M Stable"
if os.path.exists(pico_path):
    os.environ["PATH"] = pico_path + os.pathsep + os.environ.get("PATH", "")

from picosdk.PicoDeviceEnums import picoEnum
print(picoEnum.PICO_VOLTAGE_RANGE)
