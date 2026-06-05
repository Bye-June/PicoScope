"""
socket_server.py — 마스터 VB6 ↔ PicoScope 프로그램 TCP 소켓 서버

수신 명령 (마스터 → 프로그램):
  SELECT,<화면명>                             화면 전환 (PICOSCOPE | 34465A)
  START,SN1,SN2,모드1,모드2,모드3             PicoScope 검사 시작
  CETOS_V1,SN,채널,기준mV,허용mV             TOS Output 전압 측정 (1000회)
  CETOS_V2,SN,채널,하한mV,상한mV             TOS Variation 단발 측정
  CETOS_I,SN,채널,하한mA,상한mA              TOS 소비전류 단발 측정

송신 응답 (프로그램 → 마스터):
  SELECT_ACK,<화면명>
  RESULT,SN1,판정,SN2,판정
  ANALOG_V1_RESULT,SN,채널,판정,MIN_mV,MAX_mV
  ANALOG_V2_RESULT,SN,채널,판정,측정값_mV
  ANALOG_I_RESULT,SN,채널,판정,측정값_mA
  ANALOG_ERROR,SN,에러코드
  ERROR,메시지
"""

from PyQt6.QtNetwork import QTcpServer, QHostAddress
from PyQt6.QtCore import QObject, pyqtSignal


class MasterSocketServer(QObject):

    # ------------------------------------------------------------------
    # 시그널 정의
    # ------------------------------------------------------------------
    # PicoScope 기존 검사
    start_test_requested = pyqtSignal(list)
    # 화면 전환: 'PICOSCOPE' 또는 '34465A'
    select_requested = pyqtSignal(str)
    # CE TOS Item 1: (sn, channel, target_mv, tolerance_mv)
    analog_v1_requested = pyqtSignal(str, str, float, float)
    # CE TOS Item 2: (sn, channel, lower_mv, upper_mv)
    analog_v2_requested = pyqtSignal(str, str, float, float)
    # CE TOS Item 3: (sn, channel, lower_ma, upper_ma)
    analog_i_requested = pyqtSignal(str, str, float, float)

    VALID_SCREENS   = {'PICOSCOPE', '34465A'}
    VALID_V_CHANNELS = {'TSM', 'TSS', 'TSM_R', 'TSS_R'}
    VALID_I_CHANNELS = {'VCC_M', 'VCC_R'}

    # ------------------------------------------------------------------
    def __init__(self, port: int = 8080, parent=None):
        super().__init__(parent)
        self.server = QTcpServer(self)
        self.port = port
        self.client_socket = None

        self.server.newConnection.connect(self._handle_new_connection)

    # ------------------------------------------------------------------
    # 서버 생명주기
    # ------------------------------------------------------------------
    def start(self) -> bool:
        if self.server.listen(QHostAddress.SpecialAddress.Any, self.port):
            print(f'[Socket] Server listening on port {self.port}')
            return True
        print(f'[Socket] Failed to start server on port {self.port}')
        return False

    def close(self):
        if self.client_socket:
            self.client_socket.disconnectFromHost()
        self.server.close()

    # ------------------------------------------------------------------
    # 연결 / 해제
    # ------------------------------------------------------------------
    def _handle_new_connection(self):
        socket = self.server.nextPendingConnection()
        self.client_socket = socket
        print(f'[Socket] Master connected from {socket.peerAddress().toString()}')
        socket.readyRead.connect(self._read_data)
        socket.disconnected.connect(self._handle_disconnect)

    def _handle_disconnect(self):
        if self.client_socket:
            print(f'[Socket] Master disconnected')
            self.client_socket.deleteLater()
            self.client_socket = None

    # ------------------------------------------------------------------
    # 데이터 수신
    # ------------------------------------------------------------------
    def _read_data(self):
        if not self.client_socket:
            return
        raw = self.client_socket.readAll().data().decode('utf-8').strip()
        if not raw:
            return
        # 한 번에 여러 줄이 올 수 있으므로 줄 단위 처리
        for line in raw.splitlines():
            line = line.strip()
            if line:
                print(f'[Socket] RX: {line}')
                self._parse_command(line)

    # ------------------------------------------------------------------
    # 명령 파싱 (분기)
    # ------------------------------------------------------------------
    def _parse_command(self, data: str):
        parts = [p.strip() for p in data.split(',')]
        cmd = parts[0].upper()

        dispatch = {
            'SELECT':    self._parse_select,
            'START':     self._parse_start,
            'ANALOG_V1':  self._parse_analog_v1,
            'ANALOG_V2':  self._parse_analog_v2,
            'ANALOG_I':   self._parse_analog_i,
        }

        handler = dispatch.get(cmd)
        if handler:
            handler(parts)
        else:
            self._send_raw(f'ERROR,Unknown command: {cmd}')

    # ------------------------------------------------------------------
    # SELECT — 화면 전환
    # ------------------------------------------------------------------
    def _parse_select(self, parts: list):
        # SELECT,<화면명>   (총 2칸)
        if len(parts) != 2:
            self._send_raw(f'ERROR,SELECT requires 2 fields, got {len(parts)}')
            return
        screen = parts[1].upper()
        if screen not in self.VALID_SCREENS:
            self._send_raw(f'ERROR,Unknown screen: {parts[1]}. Use PICOSCOPE or 34465A')
            return
        self.select_requested.emit(screen)
        # ACK는 슬롯에서 send_select_ack() 호출로 전송

    # ------------------------------------------------------------------
    # START — PicoScope 검사
    # ------------------------------------------------------------------
    def _parse_start(self, parts: list):
        # START,SN1,SN2,모드1,모드2,모드3   (총 6칸)
        if len(parts) != 6:
            self._send_raw(
                f'ERROR,START requires 6 fields, got {len(parts)}'
            )
            return

        sns       = [parts[1], parts[2]]
        mode_pin1 = parts[3]
        mode_pin2 = parts[4]
        mode_pin3 = parts[5]

        ch_triplets = [('A', 'B', 'C'), ('D', 'E', 'F')]

        def parse_mode(mode_str: str) -> str:
            m = mode_str.upper()
            if m.startswith('SPC'):
                ids = [x for x in m.split('/')[1:] if x.isdigit()]
                return 'SPC (ID ' + ', '.join(ids) + ')' if ids else 'SPC (ID 1, 3)'
            return mode_str

        mode1 = parse_mode(mode_pin1)
        mode2 = parse_mode(mode_pin2)
        mode3 = parse_mode(mode_pin3)

        products = []
        for i in range(2):
            sn = sns[i]
            if sn:
                ch1, ch2, ch3 = ch_triplets[i]
                channels = {}
                if mode1: channels[ch1] = mode1
                if mode2: channels[ch2] = mode2
                if mode3: channels[ch3] = mode3
                products.append({'sn': sn, 'channels': channels})

        if not products:
            self._send_raw('ERROR,No valid products/channels provided')
            return

        self.start_test_requested.emit(products)

    # ------------------------------------------------------------------
    # CETOS_V1 — TOS Output (1000회 측정, MIN/MAX 판정)
    # ------------------------------------------------------------------
    def _parse_analog_v1(self, parts: list):
        # CETOS_V1,SN,채널,기준mV,허용mV   (총 5칸)
        if len(parts) != 5:
            self._send_raw(
                f'ERROR,ANALOG_V1 requires 5 fields, got {len(parts)}'
            )
            return
        sn      = parts[1]
        channel = parts[2].upper()
        if channel not in self.VALID_V_CHANNELS:
            self.send_analog_error(sn, 'UNKNOWN_CHANNEL')
            return
        try:
            target_mv  = float(parts[3])
            tolerance_mv = float(parts[4])
        except ValueError:
            self.send_analog_error(sn, 'INVALID_COMMAND')
            return

        self.analog_v1_requested.emit(sn, channel, target_mv, tolerance_mv)

    # ------------------------------------------------------------------
    # CETOS_V2 — TOS Variation (단발 1회 측정, 범위 판정)
    # ------------------------------------------------------------------
    def _parse_analog_v2(self, parts: list):
        # CETOS_V2,SN,채널,하한mV,상한mV   (총 5칸)
        if len(parts) != 5:
            self._send_raw(
                f'ERROR,ANALOG_V2 requires 5 fields, got {len(parts)}'
            )
            return
        sn      = parts[1]
        channel = parts[2].upper()
        if channel not in self.VALID_V_CHANNELS:
            self.send_analog_error(sn, 'UNKNOWN_CHANNEL')
            return
        try:
            lower_mv = float(parts[3])
            upper_mv = float(parts[4])
        except ValueError:
            self.send_analog_error(sn, 'INVALID_COMMAND')
            return

        self.analog_v2_requested.emit(sn, channel, lower_mv, upper_mv)

    # ------------------------------------------------------------------
    # CETOS_I — TOS 소비전류 (단발 1회 측정, 범위 판정)
    # ------------------------------------------------------------------
    def _parse_analog_i(self, parts: list):
        # CETOS_I,SN,채널,하한mA,상한mA   (총 5칸)
        if len(parts) != 5:
            self._send_raw(
                f'ERROR,ANALOG_I requires 5 fields, got {len(parts)}'
            )
            return
        sn      = parts[1]
        channel = parts[2].upper()
        if channel not in self.VALID_I_CHANNELS:
            self.send_analog_error(sn, 'UNKNOWN_CHANNEL')
            return
        try:
            lower_ma = float(parts[3])
            upper_ma = float(parts[4])
        except ValueError:
            self.send_analog_error(sn, 'INVALID_COMMAND')
            return

        self.analog_i_requested.emit(sn, channel, lower_ma, upper_ma)

    # ------------------------------------------------------------------
    # 응답 전송 메서드 (외부에서 슬롯으로 호출)
    # ------------------------------------------------------------------
    def send_select_ack(self, screen: str):
        """SELECT_ACK,<PICOSCOPE|DMM>"""
        self._send_raw(f'SELECT_ACK,{screen}')

    def send_error(self, message: str):
        """ERROR,<메시지>  — PicoScope 검사 오류 등 일반 오류 응답"""
        self._send_raw(f'ERROR,{message}')

    def send_result(self, result_string: str):
        """RESULT,SN1,판정,SN2,판정  (PicoScope 기존)"""
        self._send_raw(result_string)

    def send_analog_v1_result(self, sn: str, channel: str,
                              passed: bool, min_mv: float, max_mv: float):
        """ANALOG_V1_RESULT,SN,채널,PASS/FAIL,MIN_mV,MAX_mV"""
        verdict = 'PASS' if passed else 'FAIL'
        self._send_raw(
            f'ANALOG_V1_RESULT,{sn},{channel},{verdict},{min_mv:.3f},{max_mv:.3f}'
        )

    def send_analog_v2_result(self, sn: str, channel: str,
                              passed: bool, value_mv: float):
        """ANALOG_V2_RESULT,SN,채널,PASS/FAIL,측정값_mV"""
        verdict = 'PASS' if passed else 'FAIL'
        self._send_raw(
            f'ANALOG_V2_RESULT,{sn},{channel},{verdict},{value_mv:.3f}'
        )

    def send_analog_i_result(self, sn: str, channel: str,
                             passed: bool, value_ma: float):
        """ANALOG_I_RESULT,SN,채널,PASS/FAIL,측정값_mA"""
        verdict = 'PASS' if passed else 'FAIL'
        self._send_raw(
            f'ANALOG_I_RESULT,{sn},{channel},{verdict},{value_ma:.3f}'
        )

    def send_analog_error(self, sn: str, error_code: str, detail: str = ''):
        """ANALOG_ERROR,SN,에러코드[,상세내용]
        
        detail: SCPI 에러 문자열 등 추가 정보 (있을 때만 4번째 필드로 추가)
        """
        if detail:
            # 쉼표가 포함될 수 있으므로 세미콜론으로 대체하여 파싱 혼선 방지
            safe_detail = str(detail).replace(',', ';')
            self._send_raw(f'ANALOG_ERROR,{sn},{error_code},{safe_detail}')
        else:
            self._send_raw(f'ANALOG_ERROR,{sn},{error_code}')


    # ------------------------------------------------------------------
    # 내부 전송 헬퍼
    # ------------------------------------------------------------------
    def _send_raw(self, message: str):
        print(f'[Socket] TX: {message}')
        if self.client_socket and self.client_socket.isOpen():
            self.client_socket.write(f'{message}\n'.encode('utf-8'))
            self.client_socket.flush()
