import csv
import numpy as np
import matplotlib.pyplot as plt
import glob

files = sorted(glob.glob("20260429_*.csv"))
if not files:
    print("No CSV files found.")
    exit()

for f in files[:1]:
    time_list = []
    volt_list = []
    with open(f, 'r', encoding='utf-8-sig') as csvfile:
        reader = csv.reader(csvfile)
        # Skip header lines
        next(reader)
        next(reader)
        next(reader) # empty line
        for row in reader:
            if len(row) >= 2:
                try:
                    time_list.append(float(row[0]))
                    volt_list.append(float(row[1]))
                except ValueError:
                    pass
                    
    time = np.array(time_list)
    volt = np.array(volt_list)
    
    plt.figure(figsize=(12, 4))
    plt.plot(time, volt)
    plt.title(f"Waveform from {f}")
    plt.xlabel("Time (ms)")
    plt.ylabel("Voltage (V)")
    plt.grid(True)
    plt.savefig("scratch_plot.png")
    
    # Try running SENT decoder if applicable
    import sys
    sys.path.append('.')
    from src.test_sequence import SENTDecoder
    
    decoder = SENTDecoder(sample_rate_hz=1e7) # ~10MS/s based on 0.1us interval
    decoder.threshold_v = 1.0 # Force threshold to 1.0V since signal is 0 to 2V
    
    result = decoder.decode_frame(volt)
    print(f"File {f} SENT Decode result:")
    print(result)
