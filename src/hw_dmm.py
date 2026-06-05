"""
hw_dmm.py — Keysight 34461A / 34465A VISA driver
  - pyvisa + Keysight IO Libraries Suite (visa32.dll) 백엔드 사용
  - 34461A: 최소 샘플링 간격 1000µs (1kS/s)
  - 34465A: 최소 샘플링 간격 20µs  (50kS/s)
"""

import time
import socket
import concurrent.futures
import numpy as np

try:
    import pyvisa
    PYVISA_AVAILABLE = True
except ImportError:
    PYVISA_AVAILABLE = False


class DMMHardware:
    # 모델별 최소 샘플링 간격 (µs)
    MIN_INTERVAL_US = {
        '34461A': 1000.0,
        '34465A': 20.0,
        '34470A': 20.0,
        '34460A': 1000.0,
    }
    DEFAULT_MIN_INTERVAL_US = 1000.0

    # 모델별 최소 NPLC
    MIN_NPLC = {
        '34461A': 0.02,    # 34461A 최소 NPLC
        '34465A': 0.0002,  # 34465A 최소 NPLC (50kS/s 지원)
        '34470A': 0.0001,  # 34470A 최소 NPLC
        '34460A': 0.02,
    }
    DEFAULT_MIN_NPLC = 0.02

    # 모델별 유효 NPLC 이산값 리스트
    VALID_NPLC = {
        '34461A': [0.02, 0.06, 0.2, 0.6, 1, 2, 6, 10, 20, 100],
        '34465A': [0.0002, 0.001, 0.002, 0.006, 0.02, 0.06, 0.2, 0.6, 1, 2, 6, 10, 20, 100],
        '34470A': [0.0001, 0.0002, 0.001, 0.002, 0.006, 0.02, 0.06, 0.2, 0.6, 1, 2, 6, 10, 20, 100],
        '34460A': [0.02, 0.06, 0.2, 0.6, 1, 2, 6, 10, 20, 100],
    }
    DEFAULT_VALID_NPLC = [0.02, 0.06, 0.2, 0.6, 1, 2, 6, 10, 20, 100]

    def __init__(self):
        self.rm = None
        self.inst = None
        self.is_connected = False
        self.model = ''          # e.g. '34461A'
        self.serial = ''
        self.firmware = ''
        self._min_interval_us = self.DEFAULT_MIN_INTERVAL_US
        self._min_nplc        = self.DEFAULT_MIN_NPLC

    # ------------------------------------------------------------------
    # 연결 관리
    # ------------------------------------------------------------------
    def list_resources(self, subnets: list = None, timeout_ms: int = 300) -> list:
        """LAN(TCP 5025) + USB(USBTMC) 동시 스캔으로 SCPI 기기 발견

        동작:
          [LAN]  subnets 대역 .1~.254 포트 5025 TCP 병렬 접속 → *IDN? 확인
          [USB]  NI-VISA rm.list_resources('USB?*::INSTR') → *IDN? 확인
          두 결과를 합쳐서 반환

        Returns:
            [(ip_or_id, idn_str, visa_addr), ...]
              LAN 예: ('192.168.1.101',  'Keysight,...', 'TCPIP0::192.168.1.101::5025::SOCKET')
              USB 예: ('USB::MY60037440', 'Keysight,...', 'USB0::0x2A8D::0x1301::MY60037440::INSTR')
        """
        found = []

        # ── LAN 스캔 (TCP 포트 5025) ────────────────────────────────
        if subnets is None:
            subnets = self._detect_subnets()

        def _probe_tcp(ip: str):
            try:
                with socket.create_connection((ip, 5025), timeout=timeout_ms / 1000):
                    pass
            except OSError:
                return None
            try:
                with socket.create_connection((ip, 5025), timeout=1.0) as s:
                    s.sendall(b'*IDN?\n')
                    s.settimeout(1.0)
                    resp = b''
                    while True:
                        chunk = s.recv(256)
                        if not chunk:
                            break
                        resp += chunk
                        if b'\n' in resp:
                            break
                idn = resp.decode('ascii', errors='ignore').strip()
                if idn:
                    return ip, idn, f'TCPIP0::{ip}::5025::SOCKET'
            except Exception:
                pass
            return None

        all_ips = [f'{s}.{i}' for s in subnets for i in range(1, 255)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            for r in ex.map(_probe_tcp, all_ips):
                if r:
                    found.append(r)

        # ── USB 스캔 (USBTMC / NI-VISA) ────────────────────────────
        if PYVISA_AVAILABLE:
            try:
                if self.rm is None:
                    self.rm = pyvisa.ResourceManager()
                usb_resources = list(self.rm.list_resources('USB?*::INSTR'))
                for visa_addr in usb_resources:
                    try:
                        inst = self.rm.open_resource(visa_addr)
                        inst.timeout = 2000
                        idn = inst.query('*IDN?').strip()
                        inst.close()
                        # USB 식별자: S/N 추출 (USB0::VID::PID::SN::INSTR)
                        parts = visa_addr.split('::')
                        uid = parts[3] if len(parts) >= 4 else visa_addr
                        found.append((f'USB::{uid}', idn, visa_addr))
                    except Exception as e:
                        print(f'[DMM] USB IDN 쿼리 실패 {visa_addr}: {e}')
            except Exception as e:
                print(f'[DMM] USB 스캔 오류: {e}')

        # LAN은 IP 오름차순, USB는 뒤에 붙임
        lan = sorted([r for r in found if r[0].startswith('USB') is False],
                     key=lambda x: x[0])
        usb = [r for r in found if r[0].startswith('USB')]
        return lan + usb

    @staticmethod
    def _detect_subnets() -> list:
        """PC의 IPv4 네트워크 인터페이스에서 서브넷 목록 추출"""
        subnets = set()
        try:
            hostname = socket.gethostname()
            ips = socket.getaddrinfo(hostname, None)
            for info in ips:
                ip = info[4][0]
                if ':' in ip:
                    continue
                if ip.startswith('127.'):
                    continue
                parts = ip.split('.')
                if len(parts) == 4:
                    subnets.add(f'{parts[0]}.{parts[1]}.{parts[2]}')
        except Exception:
            pass
        return list(subnets) or ['192.168.1', '192.168.0']



    def connect(self, visa_address: str) -> tuple:
        """
        DMM에 연결하고 IDN을 확인합니다.
        Returns: (success: bool, message: str)
        """
        if not PYVISA_AVAILABLE:
            return False, 'pyvisa가 설치되지 않았습니다. pip install pyvisa'

        try:
            if self.rm is None:
                self.rm = pyvisa.ResourceManager()

            self.inst = self.rm.open_resource(visa_address)
            self.inst.timeout = 5000  # 5s

            is_socket = 'SOCKET' in visa_address.upper()
            if is_socket:
                self.inst.read_termination  = '\n'
                self.inst.write_termination = '\n'
                self.inst.send_end          = True

            # 기기 초기화
            self.inst.write('*CLS')
            time.sleep(0.1)

            idn = self.inst.query('*IDN?').strip()
            # IDN 형식: Keysight Technologies,34461A,MY60037440,A.03.03-...
            parts = idn.split(',')
            if len(parts) >= 3:
                self.model = parts[1].strip()
                self.serial = parts[2].strip()
                self.firmware = parts[3].strip() if len(parts) > 3 else ''
            else:
                self.model = idn

            self._min_interval_us = self.MIN_INTERVAL_US.get(
                self.model, self.DEFAULT_MIN_INTERVAL_US
            )
            self._min_nplc = self.MIN_NPLC.get(
                self.model, self.DEFAULT_MIN_NPLC
            )

            self.is_connected = True
            msg = f'{self.model} (S/N: {self.serial}) 연결됨 | 최소 간격: {self._min_interval_us:.0f}µs'
            print(f'[DMM] {msg}')
            return True, msg

        except Exception as e:
            self.is_connected = False
            msg = f'연결 실패: {e}'
            print(f'[DMM] {msg}')
            return False, msg

    def disconnect(self):
        """DMM 연결 해제"""
        try:
            if self.inst:
                self.inst.write('*CLS')
                self.inst.close()
        except Exception:
            pass
        finally:
            self.inst = None
            self.is_connected = False
            print('[DMM] 연결 해제')

    def identify(self) -> str:
        """*IDN? 쿼리 결과 반환"""
        if not self.is_connected:
            return 'Not connected'
        return self.inst.query('*IDN?').strip()

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------
    def _clamp_interval(self, interval_us: float) -> float:
        """모델에 따라 샘플링 간격 최솟값 보정"""
        clamped = max(interval_us, self._min_interval_us)
        if clamped != interval_us:
            print(f'[DMM] 간격 보정: {interval_us:.0f}µs → {clamped:.0f}µs '
                  f'({self.model} 최솟값)')
        return clamped

    def _check_connected(self):
        if not self.is_connected or self.inst is None:
            raise RuntimeError('DMM가 연결되지 않았습니다.')

    @staticmethod
    def _check_overflow(values: 'np.ndarray', label: str = '측정값'):
        """SCPI 오버플로우값(9.9E+37) 감지 → 단선/미연결로 판단하여 예외 발생"""
        OVERFLOW = 9.9e+37
        if np.any(np.abs(values) >= OVERFLOW * 0.99):
            raise RuntimeError(
                f'[OVLD] {label} 오버플로우 감지 — 프로브 미연결 또는 단선 상태입니다.'
            )

    def _check_scpi_errors(self, label: str = '측정'):
        """SYST:ERR? 로 SCPI 에러 큐 확인 — 에러가 있으면 RuntimeError 발생

        DMM 디스플레이에 ERROR가 표시될 때 프로브 미연결 등 하드웨어 오류를
        소프트웨어에서 자동으로 감지합니다.
        에러 코드 0 = No error → 정상 통과
        """
        try:
            resp = self.inst.query('SYST:ERR?').strip()
            # 응답 형식: "+0,\"No error\"" 또는 "-261,\"Data questionable\""
            code = int(resp.split(',')[0])
            if code != 0:
                raise RuntimeError(
                    f'[DMM ERR] {label} 실패 — SCPI 에러: {resp}'
                )
        except RuntimeError:
            raise   # 위에서 발생한 에러 그대로 전파
        except Exception:
            pass    # SYST:ERR? 자체 실패 시 무시 (연결 불안정 대비)

    # ------------------------------------------------------------------
    # DC 전압 측정
    # ------------------------------------------------------------------
    def measure_dc_voltage(self,
                           n_samples: int = 1000,
                           interval_us: float = 50.0,
                           v_range: float = 10.0) -> dict:
        """
        DC 전압을 n_samples 회 측정합니다.

        Args:
            n_samples:   측정 횟수 (34461A 최대 10000, 34465A 최대 2000000)
            interval_us: 측정 간격 µs (34461A 최소 1000, 34465A 최소 20)
            v_range:     측정 레인지 V (10 = 10V 레인지)

        Returns:
            {
              'mean_v':       float,   # 평균 [V]
              'min_v':        float,   # 최솟값 [V]
              'max_v':        float,   # 최댓값 [V]
              'std_v':        float,   # 표준편차 [V]
              'peak_to_peak_v': float, # 피크투피크 [V]
              'values':       np.ndarray, # 원시 데이터 [V]
              'elapsed_ms':   float,   # 실제 소요 시간 [ms]
              'n_samples':    int,
              'interval_us':  float,   # 실제 사용된 간격
            }
        """
        self._check_connected()
        actual_interval_us = self._clamp_interval(interval_us)
        interval_s = actual_interval_us / 1e6

        # 유효 NPLC 리스트에서 interval에 맞는 가장 큰 NPLC 선택
        # 조건: aperture(= NPLC / 60Hz) ≤ interval × 0.75  (25% 타이밍 여유)
        valid_list = self.VALID_NPLC.get(self.model, self.DEFAULT_VALID_NPLC)
        nplc = valid_list[0]  # 기본값: 최소 NPLC
        for candidate in reversed(valid_list):   # 큰 값부터 확인
            if candidate / 60.0 <= interval_s * 0.75:   # aperture ≤ 75% of interval
                nplc = candidate
                break
        print(f'[DMM] measure_dc_voltage: interval={actual_interval_us:.0f}µs  '
              f'NPLC={nplc}  model={self.model}')

        # 34465A: SAMP:SOUR TIM 기본 내장 → 정밀 타이밍 제어 가능
        # 34461A 등: DIG 옵션 없으면 TIM 미지원(-203) → IMM 사용
        samp_cmds = (
            ['SAMP:SOUR TIM', f'SAMP:TIM {interval_s:.6f}']
            if self.model == '34465A'
            else ['SAMP:SOUR IMM']
        )
        cmd_seq = [
            '*CLS',
            '*RST',
            f'CONF:VOLT:DC {v_range}',
            f'VOLT:DC:NPLC {nplc}',
            f'SAMP:COUN {n_samples}',
            *samp_cmds,
            'TRIG:SOUR IMM',
            'TRIG:COUN 1',
        ]

        for cmd in cmd_seq:
            self.inst.write(cmd)

        t_start = time.perf_counter()
        self.inst.write('INIT')
        self.inst.write('*WAI')

        # 측정 완료 대기 (최대 n*interval + 5s)
        wait_s = n_samples * interval_s + 5.0
        self.inst.timeout = int(wait_s * 1000) + 5000

        raw = self.inst.query('FETC?')
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        # 벌크 측정은 SCPI 에러 체크 제외:
        # SAMP:SOUR TIM 등이 일부 DMM에서 -203 에러를 발생시켜도
        # 측정값은 정상 반환하는 비치명적 에러임

        values = np.array([float(v) for v in raw.strip().split(',')])
        self._check_overflow(values, 'DC 전압')


        return {
            'mean_v':           float(np.mean(values)),
            'min_v':            float(np.min(values)),
            'max_v':            float(np.max(values)),
            'std_v':            float(np.std(values)),
            'peak_to_peak_v':   float(np.max(values) - np.min(values)),
            'values':           values,
            'elapsed_ms':       elapsed_ms,
            'n_samples':        len(values),
            'interval_us':      actual_interval_us,
        }

    # ------------------------------------------------------------------
    # DC 전류 측정
    # ------------------------------------------------------------------
    def measure_dc_current(self,
                           n_samples: int = 100,
                           interval_us: float = 1000.0,
                           i_range: float = 0.1) -> dict:
        """
        DC 전류를 n_samples 회 측정합니다.
        반드시 DMM을 전류 측정 단자(A)에 직렬 연결 후 사용.

        Args:
            n_samples:   측정 횟수
            interval_us: 측정 간격 µs
            i_range:     측정 레인지 A (0.1 = 100mA 레인지)

        Returns:
            {
              'mean_a':     float,  # 평균 [A]
              'min_a':      float,
              'max_a':      float,
              'std_a':      float,
              'values':     np.ndarray,
              'elapsed_ms': float,
              'n_samples':  int,
            }
        """
        self._check_connected()
        actual_interval_us = self._clamp_interval(interval_us)
        interval_s = actual_interval_us / 1e6

        # 34465A: SAMP:SOUR TIM 기본 내장 → 정밀 타이밍 제어 가능
        # 34461A 등: DIG 옵션 없으면 TIM 미지원(-203) → IMM 사용
        samp_cmds = (
            ['SAMP:SOUR TIM', f'SAMP:TIM {interval_s:.6f}']
            if self.model == '34465A'
            else ['SAMP:SOUR IMM']
        )
        cmd_seq = [
            '*CLS',
            '*RST',
            f'CONF:CURR:DC {i_range}',
            'CURR:DC:NPLC 0.02',
            f'SAMP:COUN {n_samples}',
            *samp_cmds,
            'TRIG:SOUR IMM',
            'TRIG:COUN 1',
        ]

        for cmd in cmd_seq:
            self.inst.write(cmd)

        t_start = time.perf_counter()
        self.inst.write('INIT')
        self.inst.write('*WAI')

        wait_s = n_samples * interval_s + 5.0
        self.inst.timeout = int(wait_s * 1000) + 5000

        raw = self.inst.query('FETC?')
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        # 벌크 측정은 SCPI 에러 체크 제외 (비치명적 에러 오탐 방지)

        values = np.array([float(v) for v in raw.strip().split(',')])
        self._check_overflow(values, 'DC 전류')

        return {
            'mean_a':     float(np.mean(values)),
            'min_a':      float(np.min(values)),
            'max_a':      float(np.max(values)),
            'std_a':      float(np.std(values)),
            'values':     values,
            'elapsed_ms': elapsed_ms,
            'n_samples':  len(values),
        }

    # ------------------------------------------------------------------
    # 단일 즉시 측정 (빠른 확인 / 수동 측정용)
    # ------------------------------------------------------------------
    def measure_single_voltage(self, v_range: float = 10.0) -> float:
        """단일 DC 전압 즉시 측정 (MEAS:VOLT:DC? — 기기 기본값 사용)"""
        self._check_connected()
        raw = self.inst.query(f'MEAS:VOLT:DC? {v_range}')
        return float(raw.strip())

    def measure_single_current(self, i_range: float = 0.1) -> float:
        """단일 DC 전류 즉시 측정 (MEAS:CURR:DC? — 기기 기본값 사용)"""
        self._check_connected()
        raw = self.inst.query(f'MEAS:CURR:DC? {i_range}')
        return float(raw.strip())

    # ------------------------------------------------------------------
    # 정밀 단발 측정 (Item 2 / Item 3 전용)
    #   - NPLC: 10 PLC (50Hz 기준 200ms 적분 → 노이즈 최소화)
    #   - Auto Zero: ON (오프셋 드리프트 보상)
    #   - 측정 시간: ~220ms (50Hz 환경)
    # ------------------------------------------------------------------
    def measure_precision_voltage(self,
                                   v_range: float = 10.0,
                                   nplc:    float = 10.0) -> dict:
        """정밀 단발 DC 전압 측정

        Args:
            v_range: 측정 레인지 V (기본 10 V)
            nplc   : 적분 시간 (PLC 단위, 기본 10 PLC = ~200ms @ 50Hz)

        Returns:
            {
              'value_v'    : float,   # 측정값 [V]
              'nplc'       : float,   # 실제 사용된 NPLC
              'elapsed_ms' : float,   # 소요 시간 [ms]
            }
        """
        self._check_connected()

        cmd_seq = [
            '*CLS',
            f'CONF:VOLT:DC {v_range}',
            f'VOLT:DC:NPLC {nplc}',   # 고정밀 적분
            'VOLT:DC:ZERO:AUTO ON',    # 오프셋 보상 ON (34461A/34465A 공통 표준 명령어)
            'TRIG:SOUR IMM',
            'TRIG:COUN 1',
            'SAMP:COUN 1',
        ]
        for cmd in cmd_seq:
            self.inst.write(cmd)

        # 측정 타임아웃: (NPLC / 50Hz) * 3 + 여유 2s
        timeout_s = (nplc / 50.0) * 3 + 2.0
        self.inst.timeout = int(timeout_s * 1000)

        t_start = time.perf_counter()
        self.inst.write('INIT')
        self.inst.write('*WAI')
        raw = self.inst.query('FETC?')
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        self._check_scpi_errors('정밀 DC 전압 측정')

        value_v = float(raw.strip().split(',')[0])
        self._check_overflow(np.array([value_v]), '정밀 DC 전압')
        return {
            'value_v':    value_v,
            'nplc':       nplc,
            'elapsed_ms': elapsed_ms,
        }

    def measure_precision_current(self,
                                   i_range: float = 0.1,
                                   nplc:    float = 10.0) -> dict:
        """정밀 단발 DC 전류 측정

        Args:
            i_range: 측정 레인지 A (기본 0.1 A = 100 mA)
            nplc   : 적분 시간 (PLC 단위, 기본 10 PLC)

        Returns:
            {
              'value_a'    : float,
              'nplc'       : float,
              'elapsed_ms' : float,
            }
        """
        self._check_connected()

        cmd_seq = [
            '*CLS',
            f'CONF:CURR:DC {i_range}',
            f'CURR:DC:NPLC {nplc}',
            'CURR:DC:ZERO:AUTO ON',    # 오프셋 보상 ON (34461A/34465A 공통 표준 명령어)
            'TRIG:SOUR IMM',
            'TRIG:COUN 1',
            'SAMP:COUN 1',
        ]
        for cmd in cmd_seq:
            self.inst.write(cmd)

        timeout_s = (nplc / 50.0) * 3 + 2.0
        self.inst.timeout = int(timeout_s * 1000)

        t_start = time.perf_counter()
        self.inst.write('INIT')
        self.inst.write('*WAI')
        raw = self.inst.query('FETC?')
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        self._check_scpi_errors('정밀 DC 전류 측정')

        value_a = float(raw.strip().split(',')[0])
        self._check_overflow(np.array([value_a]), '정밀 DC 전류')
        return {
            'value_a':    value_a,
            'nplc':       nplc,
            'elapsed_ms': elapsed_ms,
        }
