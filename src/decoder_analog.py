import numpy as np

class AnalogAnalyzer:
    """
    Analog Analyzer for CE TOS_PCB Assy (TLE4997A8D).
    Calculates VDD, VOUT, Ratio, and Noise.
    """
    def __init__(self, sample_rate_hz=1e6):
        self.sample_rate_hz = sample_rate_hz

    def analyze(self, vdd_array, vout_array):
        """
        Analyze Analog Hall Sensor outputs.
        Args:
            vdd_array: numpy array of VDD voltages.
            vout_array: numpy array of VOUT voltages.
        Returns:
            dict containing measurement results.
        """
        if len(vdd_array) == 0 or len(vout_array) == 0:
            return {"status": "error", "message": "Empty array"}

        vdd_mean = float(np.mean(vdd_array))
        vout_mean = float(np.mean(vout_array))
        
        ratio = (vout_mean / vdd_mean) if vdd_mean != 0 else 0.0
        
        # Calculate noise on VOUT
        vout_ac = vout_array - vout_mean
        p2p_noise = float(np.max(vout_array) - np.min(vout_array))
        rms_noise = float(np.sqrt(np.mean(vout_ac**2)))
        
        return {
            "status": "success",
            "vdd_mean": vdd_mean,
            "vout_mean": vout_mean,
            "ratio": ratio,
            "p2p_noise": p2p_noise,
            "rms_noise": rms_noise
        }
