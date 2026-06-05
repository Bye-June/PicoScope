import sys
import os
import json
import pprint
import numpy as np
import winsound
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QComboBox, QLabel, QTextEdit,
                             QGroupBox, QGridLayout, QRadioButton, QButtonGroup, QCheckBox,
                             QMessageBox, QStackedWidget, QLineEdit, QSizePolicy)
from PyQt6.QtCore import QTimer, QDateTime, Qt
from PyQt6.QtGui import QIcon
import pyqtgraph as pg
import pyqtgraph.exporters

from src.hw_picoscope import PicoScopeHardware, PICOSDK_AVAILABLE
from src.hw_dmm import DMMHardware
from src.test_sequence import TestSequencer
from src.socket_server import MasterSocketServer

# exe 빌드(PyInstaller frozen) 시 exe 위치 기준, 스크립트 실행 시 현재 디렉토리 기준
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = os.path.join(_BASE_DIR, "config.json")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Universal Hall Sensor Analyzer")
        
        icon_path = os.path.join(getattr(sys, '_MEIPASS', os.path.abspath(".")), 'icon.png')
        self.setWindowIcon(QIcon(icon_path))
        self.setGeometry(0, 580, 1920, 500)

        # PicoScope
        self.hw = PicoScopeHardware()
        self.sequencer = TestSequencer(self.hw)

        # DMM
        self.dmm = DMMHardware()
        self.current_screen = 'PICOSCOPE'  # SELECT 명령으로 변경
        self.dmm_accum_values = []  # DMM Single 누적 통계값 저장
        self._dmm_proxy = None      # DMM 그래프 마우스 이동 SignalProxy
        
        self.channels = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
        self.ui_state = {}
        self.plot_curves = {}
        
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self.monitor_update)
        self.is_monitoring = False
        
        # Socket Server
        self.socket_server = MasterSocketServer(port=8080, parent=self)
        self.socket_server.start_test_requested.connect(self.on_start_test_requested)
        self.socket_server.select_requested.connect(self.on_select_requested)
        self.socket_server.analog_v1_requested.connect(self.on_analog_v1_requested)
        self.socket_server.analog_v2_requested.connect(self.on_analog_v2_requested)
        self.socket_server.analog_i_requested.connect(self.on_analog_i_requested)
        self.socket_server.start()

        self.init_ui()
        self.load_config()

        if not PICOSDK_AVAILABLE:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("드라이버 없음")
            msg.setText("PicoScope 드라이버(DLL)를 찾을 수 없습니다.")
            msg.setInformativeText(
                "스코프 연결 기능을 사용할 수 없습니다.\n\n"
                "해결 방법:\n"
                "1. PicoScope 드라이버를 설치 후 PC를 재부팅 하세요.\n"
                "2. 드라이버 없이 테스트하려면 [No Scope] 체크박스를 사용하세요."
            )
            msg.exec()
        else:
            QTimer.singleShot(500, self.auto_connect_on_startup)

        # DMM 자동 연결 — PicoScope 유무와 무관하게 항상 시도
        QTimer.singleShot(800, self.auto_connect_dmm_on_startup)

    def init_ui(self):
        """QStackedWidget으로 PicoScope / DMM 두 화면을 관리"""
        container = QWidget()
        self.setCentralWidget(container)
        root_layout = QVBoxLayout(container)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── 상단 네비게이션 버튼 바 ──────────────────────────────────
        nav_bar = QWidget()
        nav_bar.setFixedHeight(36)
        nav_bar.setStyleSheet("background-color: #1a1a2e;")
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(6, 3, 6, 3)
        nav_layout.setSpacing(4)

        self.nav_btn_scope = QPushButton("🔬  PicoScope")
        self.nav_btn_dmm   = QPushButton("⚡  34465A  DMM")
        for btn in (self.nav_btn_scope, self.nav_btn_dmm):
            btn.setFixedHeight(28)
            btn.setStyleSheet(
                "QPushButton { background-color: #2a2a4a; color: #aaa; "
                "border: 1px solid #444; border-radius: 4px; padding: 0 14px; font-weight: bold; }"
                "QPushButton:hover { background-color: #3a3a6a; color: #fff; }"
            )
        self.nav_btn_scope.clicked.connect(lambda: self._switch_page('PICOSCOPE'))
        self.nav_btn_dmm.clicked.connect(lambda: self._switch_page('34465A'))
        nav_layout.addWidget(self.nav_btn_scope)
        nav_layout.addWidget(self.nav_btn_dmm)
        nav_layout.addStretch()

        # 상단바 우측에 음향 체크박스 배치 (레이아웃 손상 없이 깔끔하게)
        self.sound_chk = QCheckBox("🔊 Sound Alarm")
        self.sound_chk.setStyleSheet("color: #aaa; font-weight: bold; font-size: 12px; margin-right: 12px;")
        self.sound_chk.setChecked(True)
        self.sound_chk.stateChanged.connect(lambda: self.save_config())
        nav_layout.addWidget(self.sound_chk)

        root_layout.addWidget(nav_bar)

        # ── QStackedWidget ──────────────────────────────────────────
        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack)

        # Page 0: PicoScope
        picoscope_page = self._build_picoscope_page()
        self.stack.addWidget(picoscope_page)   # index 0

        # Page 1: DMM (CE TOS)
        dmm_page = self._build_dmm_page()
        self.stack.addWidget(dmm_page)         # index 1

        self.stack.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # Page 0: PicoScope UI
    # ------------------------------------------------------------------
    def _build_picoscope_page(self) -> QWidget:
        page = QWidget()
        main_layout = QHBoxLayout(page)
        
        left_layout = QVBoxLayout()
        main_layout.addLayout(left_layout, stretch=8)
        
        right_layout = QVBoxLayout()
        main_layout.addLayout(right_layout, stretch=2)

        # 1. Top Control Panel
        conn_layout = QHBoxLayout()
        self.connect_btn = QPushButton("Connect Scope")
        self.connect_btn.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; font-weight: bold; padding: 10px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #42A5F5; }"
            "QPushButton:pressed { background-color: #1565C0; }"
            "QPushButton:disabled { background-color: #555; color: #888; }"
        )
        self.connect_btn.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.connect_btn)

        # PicoScope 연결 상태 LED
        self.scope_led = QLabel()
        self.scope_led.setFixedSize(12, 12)
        self.scope_led.setStyleSheet("background-color: #888888; border-radius: 6px; border: 1px solid #555;")
        conn_layout.addWidget(self.scope_led)

        self.dev_info_label = QLabel("Device: Not Connected")
        self.dev_info_label.setStyleSheet("color: #aaa;")
        conn_layout.addWidget(self.dev_info_label)
        conn_layout.addStretch()
        
        self.no_scope_chk = QCheckBox("No Scope")
        self.no_scope_chk.stateChanged.connect(self.toggle_sim_mode)
        conn_layout.addWidget(self.no_scope_chk)
        
        right_layout.addLayout(conn_layout)

        # 2. Channel Configuration
        config_group = QGroupBox("Channel Configuration")
        grid = QGridLayout()
        mode_options = ["Not Used", "Monitor Only", "Analog VDD", "Analog VOUT", "SENT",
                         "SPC (ID 1)", "SPC (ID 3)", "SPC (ID 1, 3)"]
        probe_options = ["x1", "x10"]
        bw_options = ["20MHz", "Full"]
        
        ch_colors = {
            'A': '#2196F3', # Blue
            'B': '#F44336', # Red
            'C': '#4CAF50', # Green
            'D': '#FFC107', # Yellow
            'E': '#9C27B0', # Purple
            'F': '#9E9E9E', # Grey
            'G': '#00BCD4', # Cyan
            'H': '#E91E63'  # Pink
        }
        for i, ch in enumerate(self.channels):
            row = i
            col_offset = 0
            
            ch_label = QLabel(f"Ch {ch}:")
            ch_label.setStyleSheet(f"color: {ch_colors[ch]}; font-weight: bold; font-size: 12px;")
            grid.addWidget(ch_label, row, col_offset)
            
            c_mode = QComboBox()
            c_mode.addItems(mode_options)
            grid.addWidget(c_mode, row, col_offset + 1)
            
            c_probe = QComboBox()
            c_probe.addItems(probe_options)
            c_probe.setCurrentText("x10")
            grid.addWidget(c_probe, row, col_offset + 2)
            
            c_range = QComboBox()
            grid.addWidget(c_range, row, col_offset + 3)
            
            c_bw = QComboBox()
            c_bw.addItems(bw_options)
            c_bw.setCurrentText("20MHz")
            grid.addWidget(c_bw, row, col_offset + 4)
            
            if col_offset == 0:
                grid.setColumnMinimumWidth(5, 30)

            self.ui_state[ch] = {'mode_cb': c_mode, 'probe_cb': c_probe, 'range_cb': c_range, 'bw_cb': c_bw}
            c_probe.currentTextChanged.connect(lambda text, channel=ch: self.update_range_options(channel))
            self.update_range_options(ch)

        config_group.setLayout(grid)
        right_layout.addWidget(config_group)

        # 3. Action Panel
        action_layout = QGridLayout()
        
        self.mode_group = QButtonGroup(self)
        self.radio_block = QRadioButton("Block Mode")
        self.radio_stream = QRadioButton("Streaming")
        self.radio_block.setChecked(True)
        self.mode_group.addButton(self.radio_block)
        self.mode_group.addButton(self.radio_stream)
        
        action_layout.addWidget(self.radio_block, 0, 0)
        action_layout.addWidget(self.radio_stream, 0, 1)

        self.awg_invert_chk = QCheckBox("AWG Invert")
        self.awg_invert_chk.setToolTip(
            "N채널 MOSFET으로 SPC AWG 신호를 드라이브할 때 체크\n"
            "(AWG HIGH→MOSFET ON→출력 LOW, AWG LOW→MOSFET OFF→출력 HIGH)"
        )
        action_layout.addWidget(self.awg_invert_chk, 0, 2)

        self.monitor_btn = QPushButton("Start Monitor")
        self.monitor_btn.setStyleSheet("background-color: #9C27B0; color: white; font-weight: bold; padding: 10px;")
        self.monitor_btn.setEnabled(False)
        self.monitor_btn.clicked.connect(self.toggle_monitor)
        action_layout.addWidget(self.monitor_btn, 1, 0)

        self.start_btn = QPushButton("Start Test (Decode)")
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 10px;")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.run_test)
        action_layout.addWidget(self.start_btn, 1, 1)
        
        right_layout.addLayout(action_layout)

        # 4. Plot Area
        self.plot_widget = pg.PlotWidget(title="Waveform Monitor")
        self.plot_widget.setLabel('left', 'Voltage (V, offset per ch)')
        self.plot_widget.setLabel('bottom', 'Time', units='ms')
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.addLegend()
        colors = [
            (33, 150, 243),   # A: Blue
            (244, 67, 54),    # B: Red
            (76, 175, 80),    # C: Green
            (255, 193, 7),    # D: Yellow
            (156, 39, 176),   # E: Purple
            (158, 158, 158),  # F: Grey
            (0, 188, 212),    # G: Cyan
            (233, 30, 99)     # H: Magenta/Pink
        ]
        self.ch_offsets = {ch: i * 6.0 for i, ch in enumerate(self.channels)}
        for i, ch in enumerate(self.channels):
            self.plot_curves[ch] = self.plot_widget.plot(pen=colors[i], name=f'Ch {ch}')

        left_layout.addWidget(self.plot_widget)

        # 5. Result Area
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px;"
            "background-color: #1e1e2e; color: #cdd6f4;"
        )
        right_layout.addWidget(self.result_text)

        return page

    # ------------------------------------------------------------------
    # Page 1: DMM (CE TOS) UI
    # ------------------------------------------------------------------
    def _build_dmm_page(self) -> QWidget:
        """좌(DMM 디스플레이) + 우(연결/수동 측정) 분할 레이아웃"""
        self._dmm_mode = 'VOLT'    # 'VOLT' or 'CURR'
        page = QWidget()
        h = QHBoxLayout(page)
        h.setContentsMargins(6, 6, 6, 6)
        h.setSpacing(8)
        h.addWidget(self._build_dmm_display_panel(), stretch=6)
        h.addWidget(self._build_dmm_control_panel(),  stretch=4)
        return page

    # ── 디스플레이 패널 ────────────────────────────────────────────
    def _build_dmm_display_panel(self) -> QWidget:
        """실제 Keysight DMM 화면과 유사한 디스플레이 패널"""
        BG   = '#1a3f5c'   # 짙은 청록 (34465A 실물 디스플레이색)
        GOLD = '#FFD700'
        BLUE = '#90CAF9'
        GRN  = '#66BB6A'

        self.dmm_display_widget = QWidget()
        self.dmm_display_widget.setStyleSheet(f'background-color:{BG}; border-radius:8px;')
        vl = QVBoxLayout(self.dmm_display_widget)
        vl.setContentsMargins(20, 14, 20, 14)
        vl.setSpacing(0)

        # ── 상단 바: 모드(좌) + 트리거(우) — 항상 최상단 고정 ──
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.dmm_disp_mode = QLabel('DC Voltage')
        self.dmm_disp_mode.setStyleSheet(
            f'color:{BLUE};font-size:17px;font-weight:bold;background:transparent;')
        self.dmm_disp_mode.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.dmm_disp_mode)
        top.addStretch()
        self.dmm_disp_trigger = QLabel('● Auto Trigger')
        self.dmm_disp_trigger.setStyleSheet(
            f'color:{GRN};font-size:13px;background:transparent;')
        self.dmm_disp_trigger.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.dmm_disp_trigger)
        vl.addLayout(top)
        vl.addSpacing(6)

        # ── 메인 수치 ──
        val_row = QHBoxLayout()
        val_row.setContentsMargins(0, 0, 0, 0)
        self.dmm_disp_value = QLabel('-----.------')
        self.dmm_disp_value.setStyleSheet(
            f'color:{GOLD};font-size:78px;'
            'font-family:Consolas,"Courier New",monospace;'
            f'font-weight:bold;background:transparent;letter-spacing:2px;')
        self.dmm_disp_value.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        val_row.addWidget(self.dmm_disp_value, stretch=1)

        self.dmm_disp_unit = QLabel('VDC')
        self.dmm_disp_unit.setStyleSheet(
            f'color:{GOLD};font-size:30px;'
            'font-family:Consolas,monospace;'
            f'font-weight:bold;background:transparent;')
        self.dmm_disp_unit.setAlignment(
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        val_row.addWidget(self.dmm_disp_unit)
        vl.addLayout(val_row)
        vl.addSpacing(4)

        # ── 구분선 ──
        sep = QWidget(); sep.setFixedHeight(1)
        sep.setStyleSheet('background-color:#2a5a7c;')
        vl.addWidget(sep)
        vl.addSpacing(8)

        # ── 레인지 / 샘플 정보 ──
        self.dmm_disp_range = QLabel('N = 1  |  Single')
        self.dmm_disp_range.setStyleSheet(
            f'color:{BLUE};font-size:13px;background:transparent;')
        vl.addWidget(self.dmm_disp_range)
        vl.addSpacing(10)

        # ── MIN / MAX ──
        mm_row = QHBoxLayout()
        self.dmm_disp_min = QLabel('MIN :   ------')
        self.dmm_disp_max = QLabel('MAX :   ------')
        for lbl in (self.dmm_disp_min, self.dmm_disp_max):
            lbl.setStyleSheet(
                f'color:{BLUE};font-size:19px;'
                'font-family:Consolas,monospace;'
                'font-weight:bold;background:transparent;')
        mm_row.addWidget(self.dmm_disp_min)
        mm_row.addStretch()
        mm_row.addWidget(self.dmm_disp_max)
        vl.addLayout(mm_row)
        vl.addSpacing(8)

        # ── P-P / STD ──
        pp_row = QHBoxLayout()
        self.dmm_disp_pp  = QLabel('P-P :   ------')
        self.dmm_disp_std = QLabel('STD :   ------')
        for lbl in (self.dmm_disp_pp, self.dmm_disp_std):
            lbl.setStyleSheet(
                'color:#5C8A8A;font-size:14px;'
                'font-family:Consolas,monospace;background:transparent;')
        pp_row.addWidget(self.dmm_disp_pp)
        pp_row.addStretch()
        pp_row.addWidget(self.dmm_disp_std)
        vl.addLayout(pp_row)
        vl.addSpacing(6)

        # ── 1000회 측정 그래프 (평소 숨김) ──
        self.dmm_graph = pg.PlotWidget()
        self.dmm_graph.setBackground('#1a3f5c')
        self.dmm_graph.setMinimumHeight(200)
        self.dmm_graph.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding)   # 남는 세로 공간 모두 채움
        gp = self.dmm_graph.getPlotItem()
        _ax_pen  = pg.mkPen(color='#2a5a7c', width=1)
        _txt_pen = pg.mkPen('#7aaccc')
        for ax in ('bottom', 'left'):
            gp.getAxis(ax).setPen(_ax_pen)
            gp.getAxis(ax).setTextPen(_txt_pen)
        gp.getAxis('top').hide()
        gp.getAxis('right').hide()
        gp.getAxis('bottom').setHeight(30)      # 하단 축 높이 최소화
        gp.setContentsMargins(0, 0, 0, 0)      # PlotItem 내부 마진 제거
        self.dmm_graph.showGrid(x=True, y=True, alpha=0.15)
        self.dmm_graph.hide()          # 1000회 측정 시에만 표시
        vl.addWidget(self.dmm_graph, stretch=1)
        vl.addSpacing(4)

        # ── PASS / FAIL 배너 (비표시 시 공간 없음) ──
        self.dmm_disp_verdict = QLabel('')
        self.dmm_disp_verdict.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dmm_disp_verdict.setFixedHeight(46)
        self.dmm_disp_verdict.setStyleSheet(
            'color:white;font-size:24px;font-weight:bold;border-radius:5px;')
        self.dmm_disp_verdict.setVisible(False)  # 시작 시 숨김 (공간 점유 없음)
        vl.addWidget(self.dmm_disp_verdict)

        return self.dmm_display_widget


    # ── 컨트롤 패널 ───────────────────────────────────────────────
    def _build_dmm_control_panel(self) -> QWidget:
        """연결 설정 + 수동 측정 버튼 + CE TOS 로그"""
        panel = QWidget()
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(6)

        # ── 연결 ──
        conn_group = QGroupBox('DMM Connection (Keysight 34465A)')
        conn_vl = QVBoxLayout()
        conn_vl.setSpacing(4)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel('VISA:'))
        self.dmm_visa_edit = QLineEdit()
        self.dmm_visa_edit.setPlaceholderText('TCPIP0::192.168.1.101::5025::SOCKET')
        r1.addWidget(self.dmm_visa_edit)
        self.dmm_scan_btn = QPushButton('Scan')
        self.dmm_scan_btn.setFixedWidth(110)
        self.dmm_scan_btn.setFixedHeight(30)
        self.dmm_scan_btn.setStyleSheet(
            'QPushButton{background:#546E7A;color:white;font-weight:bold;padding:5px;border-radius:4px;}'
            'QPushButton:hover{background:#607D8B;}'
            'QPushButton:pressed{background:#37474F;}')
        self.dmm_scan_btn.setToolTip('LAN / USB SCPI 장비 스캔')
        self.dmm_scan_btn.clicked.connect(self._scan_dmm_resources)
        r1.addWidget(self.dmm_scan_btn)
        conn_vl.addLayout(r1)

        r2 = QHBoxLayout()
        self.dmm_resource_cb = QComboBox()
        self.dmm_resource_cb.setPlaceholderText('Scan 후 선택...')
        self.dmm_resource_cb.currentIndexChanged.connect(
            lambda _: self.dmm_visa_edit.setText(
                self.dmm_resource_cb.currentData() or ''))
        r2.addWidget(self.dmm_resource_cb, stretch=1)
        self.dmm_connect_btn = QPushButton('Connect')
        self.dmm_connect_btn.setFixedWidth(110)
        self.dmm_connect_btn.setFixedHeight(30)
        self.dmm_connect_btn.setStyleSheet(
            'QPushButton{background:#1565C0;color:white;font-weight:bold;padding:6px;border-radius:4px;}'
            'QPushButton:hover{background:#1976D2;}'
            'QPushButton:pressed{background:#0D47A1;}')
        self.dmm_connect_btn.clicked.connect(self.toggle_dmm_connection)
        r2.addWidget(self.dmm_connect_btn)
        conn_vl.addLayout(r2)

        dmm_status_layout = QHBoxLayout()
        self.dmm_led = QLabel()
        self.dmm_led.setFixedSize(12, 12)
        self.dmm_led.setStyleSheet("background-color: #888888; border-radius: 6px; border: 1px solid #555;")
        dmm_status_layout.addWidget(self.dmm_led)

        self.dmm_status_label = QLabel('Not Connected')
        self.dmm_status_label.setStyleSheet('color:#888;font-weight:bold;font-size:12px;')
        dmm_status_layout.addWidget(self.dmm_status_label)
        dmm_status_layout.addStretch()
        conn_vl.addLayout(dmm_status_layout)
        conn_group.setLayout(conn_vl)
        vl.addWidget(conn_group)

        # ── 수동 측정 ──
        meas_group = QGroupBox('Manual Measurement')
        m_vl = QVBoxLayout()
        m_vl.setSpacing(5)

        # 측정 타입 선택
        mode_row = QHBoxLayout()
        self.dmm_btn_volt = QPushButton('DC VOLTAGE')
        self.dmm_btn_curr = QPushButton('DC CURRENT')
        _ACTIVE  = ('QPushButton{background:#1565C0;color:#fff;'
                    'border:1px solid #1976D2;border-radius:4px;'
                    'font-weight:bold;padding:6px;}'
                    'QPushButton:hover{background:#1976D2;}'
                    'QPushButton:pressed{background:#0D47A1;}')
        _INACTIVE = ('QPushButton{background:#263238;color:#aaa;'
                     'border:1px solid #455A64;border-radius:4px;'
                     'font-weight:bold;padding:6px;}'
                     'QPushButton:hover{background:#37474F;color:#fff;}'
                     'QPushButton:pressed{background:#1C282E;color:#fff;}')
        self.dmm_btn_volt.setStyleSheet(_ACTIVE)
        self.dmm_btn_curr.setStyleSheet(_INACTIVE)
        self.dmm_btn_volt.clicked.connect(lambda: self._set_dmm_mode('VOLT'))
        self.dmm_btn_curr.clicked.connect(lambda: self._set_dmm_mode('CURR'))
        self._dmm_mode_active_style   = _ACTIVE
        self._dmm_mode_inactive_style = _INACTIVE
        mode_row.addWidget(self.dmm_btn_volt)
        mode_row.addWidget(self.dmm_btn_curr)
        m_vl.addLayout(mode_row)

        # 측정 실행 버튼
        btn_row = QHBoxLayout()
        self.dmm_single_btn = QPushButton('⚡  Single')
        self.dmm_1000_btn   = QPushButton('🔁  × 1000  (50 µs)')
        self.dmm_reset_stats_btn = QPushButton('🔄  Reset Stats')
        for btn in (self.dmm_single_btn, self.dmm_1000_btn, self.dmm_reset_stats_btn):
            btn.setFixedHeight(36)
            
        for btn in (self.dmm_single_btn, self.dmm_1000_btn):
            btn.setStyleSheet(
                'QPushButton{background:#2E7D32;color:white;font-weight:bold;'
                'border-radius:4px;font-size:12px;}'
                'QPushButton:hover{background:#388E3C;}'
                'QPushButton:pressed{background:#1B5E20;}'
                'QPushButton:disabled{background:#1a1a1a;color:#555;}')
        self.dmm_reset_stats_btn.setStyleSheet(
            'QPushButton{background:#37474F;color:#eee;font-weight:bold;border-radius:4px;font-size:12px;}'
            'QPushButton:hover{background:#455A64;}'
            'QPushButton:pressed{background:#263238;}'
            'QPushButton:disabled{background:#1a1a1a;color:#555;}')
            
        self.dmm_single_btn.clicked.connect(self._manual_measure_single)
        self.dmm_1000_btn.clicked.connect(self._manual_measure_1000)
        self.dmm_reset_stats_btn.clicked.connect(self.reset_dmm_accum_stats)
        
        btn_row.addWidget(self.dmm_single_btn)
        btn_row.addWidget(self.dmm_1000_btn)
        btn_row.addWidget(self.dmm_reset_stats_btn)
        m_vl.addLayout(btn_row)

        # DMM 미연결 초기 상태: 동작 버튼 비활성화
        for btn in (self.dmm_btn_volt, self.dmm_btn_curr,
                    self.dmm_single_btn, self.dmm_1000_btn, self.dmm_reset_stats_btn):
            btn.setEnabled(False)

        meas_group.setLayout(m_vl)
        vl.addWidget(meas_group)

        # ── CE TOS 로그 ──
        log_hdr = QLabel('CE TOS Measurement Log')
        log_hdr.setStyleSheet('font-weight:bold;font-size:12px;margin-top:4px;')
        vl.addWidget(log_hdr)

        self.dmm_result_text = QTextEdit()
        self.dmm_result_text.setReadOnly(True)
        self.dmm_result_text.setStyleSheet(
            'font-family:Consolas,monospace;'
            'background:#1a1a1a;color:#d4d4d4;font-size:11px;')
        vl.addWidget(self.dmm_result_text)

        return panel

    # ── 측정 모드 전환 ────────────────────────────────────────────
    def _set_dmm_mode(self, mode: str):
        if mode == self._dmm_mode:
            return  # 같은 모드면 무시
        self._dmm_mode = mode
        self.reset_dmm_accum_stats(silent=True)  # 모드 전환 시 누적값 초기화 (단위 혼잡 방지)
        if mode == 'VOLT':
            self.dmm_btn_volt.setStyleSheet(self._dmm_mode_active_style)
            self.dmm_btn_curr.setStyleSheet(self._dmm_mode_inactive_style)
            self.dmm_disp_mode.setText('DC Voltage')
            self.dmm_disp_unit.setText('VDC')
        else:
            self.dmm_btn_volt.setStyleSheet(self._dmm_mode_inactive_style)
            self.dmm_btn_curr.setStyleSheet(self._dmm_mode_active_style)
            self.dmm_disp_mode.setText('DC Current')
            self.dmm_disp_unit.setText('ADC')

    def reset_dmm_accum_stats(self, silent=False):
        """DMM Single 누적 통계 데이터를 초기화하고 화면을 갱신합니다."""
        self.dmm_accum_values = []
        self.dmm_disp_min.setText('MIN :   ------')
        self.dmm_disp_max.setText('MAX :   ------')
        self.dmm_disp_pp.setText('P-P :   ------')
        self.dmm_disp_std.setText('STD :   ------')
        self.dmm_disp_value.setText('-----.------')
        self.dmm_graph.hide()
        if not silent:
            self.dmm_result_text.append(
                "<span style='color:#FF9800; font-weight:bold;'>[SYSTEM] DMM 누적 통계가 초기화되었습니다.</span>"
            )

    def play_verdict_sound(self, passed: bool):
        """판정 결과에 따른 알림음 비동기 재생 (winsound)"""
        if hasattr(self, 'sound_chk') and self.sound_chk.isChecked():
            try:
                if passed:
                    winsound.MessageBeep(winsound.MB_OK)
                else:
                    winsound.MessageBeep(winsound.MB_ICONHAND)
            except Exception as e:
                print(f"[Sound] 사운드 재생 실패: {e}")

    def reset_dmm_border(self):
        """DMM 디스플레이 패널 테두리를 원래대로 되돌립니다."""
        if hasattr(self, 'dmm_display_widget'):
            self.dmm_display_widget.setStyleSheet(
                "background-color:#1a3f5c; border-radius:8px;"
            )

    # ── 디스플레이 업데이트 ───────────────────────────────────────
    def _update_dmm_display(self, value: float, unit: str,
                             min_v=None, max_v=None,
                             std=None, pp=None,
                             n=1, interval_us=None,
                             range_info: str = None,
                             verdict: str = None,
                             values=None,
                             limits=None):
        """DMM 디스플레이 숫자/통계/판정/그래프 갱신

        Args:
            value      : 메인 표시값 (V or A)
            unit       : 'VDC' or 'ADC'
            min_v/max_v: 최소/최대값 (1000회 측정 시)
            std/pp     : 표준편차/피크투피크
            n          : 샘플 수
            interval_us: 샘플링 간격 (µs)
            range_info : 오버라이드 표시 문자열 e.g. '허용: 2400.0~2600.0 mV'
                         None이면 N/interval 자동 표시
            verdict    : 'PASS', 'FAIL', None
            values     : np.ndarray 원시 측정값 (1000회 시 그래프 표시)
            limits     : (lower, upper) 허용 범위 표시 (mV or mA)
        """
        # 1. Auto-Ranging (V -> mV, A -> mA if < 1.0/0.1)
        disp_value = value
        disp_unit = unit
        stat_scale = 1000.0
        
        if unit == 'VDC':
            if abs(value) < 1.0:
                disp_value = value * 1000.0
                disp_unit = 'mVDC'
                stat_scale = 1000.0
                stat_unit = 'mV'
            else:
                disp_value = value
                disp_unit = 'VDC'
                stat_scale = 1.0
                stat_unit = 'V'
        elif unit == 'ADC':
            if abs(value) < 0.1:
                disp_value = value * 1000.0
                disp_unit = 'mADC'
                stat_scale = 1000.0
                stat_unit = 'mA'
            else:
                disp_value = value
                disp_unit = 'ADC'
                stat_scale = 1.0
                stat_unit = 'A'
        else:
            stat_scale = 1.0
            stat_unit = ''

        # 메인 수치 포맷 (7자리 소수점 맞춤)
        if abs(disp_value) < 10:
            txt = f'{disp_value:+10.6f}'
        elif abs(disp_value) < 100:
            txt = f'{disp_value:+10.5f}'
        else:
            txt = f'{disp_value:+10.4f}'
        self.dmm_disp_value.setText(txt)
        self.dmm_disp_unit.setText(disp_unit)

        # 2. Limit Gauge
        gauge_text = ""
        if limits is not None:
            lo, hi = limits
            val_scaled = value * 1000.0
            if hi != lo:
                frac = (val_scaled - lo) / (hi - lo)
                if frac < 0:
                    gauge_text = "Lo < [●------] Hi"
                elif frac > 1:
                    gauge_text = "Lo [------●] > Hi"
                else:
                    idx = int(round(frac * 6))
                    chars = ['-'] * 7
                    chars[idx] = '●'
                    gauge_text = f"Lo [{''.join(chars)}] Hi"
            else:
                gauge_text = "Lo [---●---] Hi"

        # 레인지/샘플 정보
        if range_info:
            full_range_info = f"{range_info}   |   {gauge_text}" if gauge_text else range_info
            self.dmm_disp_range.setText(full_range_info)
        elif n > 1:
            iv = f'{interval_us:.0f}µs' if interval_us else '?'
            info_str = f'N = {n}  |  interval = {iv}'
            full_range_info = f"{info_str}   |   {gauge_text}" if gauge_text else info_str
            self.dmm_disp_range.setText(full_range_info)
        else:
            info_str = 'N = 1  |  Single'
            full_range_info = f"{info_str}   |   {gauge_text}" if gauge_text else info_str
            self.dmm_disp_range.setText(full_range_info)

        # MIN / MAX (메인 스케일에 동기화)
        if min_v is not None and max_v is not None:
            self.dmm_disp_min.setText(f'MIN :  {min_v*stat_scale:+10.4f} {stat_unit}')
            self.dmm_disp_max.setText(f'MAX :  {max_v*stat_scale:+10.4f} {stat_unit}')
        else:
            self.dmm_disp_min.setText('MIN :   ------')
            self.dmm_disp_max.setText('MAX :   ------')

        # P-P / STD (메인 스케일에 동기화)
        if pp is not None:
            self.dmm_disp_pp.setText(f'P-P :  {pp*stat_scale:.4f} {stat_unit}')
        else:
            self.dmm_disp_pp.setText('P-P :   ------')
        if std is not None:
            self.dmm_disp_std.setText(f'STD :  {std*stat_scale:.4f} {stat_unit}')
        else:
            self.dmm_disp_std.setText('STD :   ------')

        # 3. Verdict handling (sound only, no border flash)
        if verdict == 'PASS':
            self.dmm_disp_verdict.setText('✔   PASS')
            self.dmm_disp_verdict.setStyleSheet(
                'color:white;font-size:24px;font-weight:bold;'
                'background:#1B5E20;border-radius:5px;')
            self.dmm_disp_verdict.setVisible(True)
            self.play_verdict_sound(True)
        elif verdict == 'FAIL':
            self.dmm_disp_verdict.setText('✘   FAIL')
            self.dmm_disp_verdict.setStyleSheet(
                'color:white;font-size:24px;font-weight:bold;'
                'background:#B71C1C;border-radius:5px;')
            self.dmm_disp_verdict.setVisible(True)
            self.play_verdict_sound(False)
        else:
            self.dmm_disp_verdict.setVisible(False)   # 공간 없이 숨김

        # ── 그래프 ──
        is_volt = (unit == 'VDC')
        scale   = 1000.0
        unit_s  = 'mV' if is_volt else 'mA'

        if values is not None and len(values) > 1:
            mv = values * scale                        # V→mV or A→mA
            x  = np.arange(len(mv), dtype=float)
            self.dmm_graph.clear()

            # 데이터 라인
            self.dmm_graph.plot(
                x, mv,
                pen=pg.mkPen('#29B6F6', width=1),
                antialias=False
            )

            # 허용 범위 선 (CE TOS 판정 시)
            if limits is not None:
                lo, hi = limits
                for lv, color in ((lo, '#EF5350'), (hi, '#EF5350')):
                    self.dmm_graph.addItem(
                        pg.InfiniteLine(
                            pos=lv, angle=0,
                            pen=pg.mkPen(color, width=1,
                                         style=Qt.PenStyle.DashLine)
                        )
                    )

            # Y축 자동 범위 (P-P의 5배 여유)
            y_min, y_max = float(mv.min()), float(mv.max())
            pad = max((y_max - y_min) * 2.0, 0.05)
            self.dmm_graph.setYRange(y_min - pad, y_max + pad, padding=0)
            self.dmm_graph.setLabel('left',  unit_s, color='#4a7a7a')
            self.dmm_graph.setLabel('bottom', 'Sample', color='#4a7a7a')

            # ── 8. 십자선 (Crosshair) + 호버 툴팁 ──
            # 이미 추가되어 있는 십자선/툴팁 아이템 정리
            for attr in ('_ch_vline', '_ch_hline', '_ch_tooltip'):
                old = getattr(self, attr, None)
                if old is not None:
                    try:
                        self.dmm_graph.removeItem(old)
                    except Exception:
                        pass

            # 수직/수평 십자선
            self._ch_vline = pg.InfiniteLine(
                angle=90, movable=False,
                pen=pg.mkPen('#FFD740', width=1, style=Qt.PenStyle.DashLine))
            self._ch_hline = pg.InfiniteLine(
                angle=0,  movable=False,
                pen=pg.mkPen('#FFD740', width=1, style=Qt.PenStyle.DashLine))
            self._ch_vline.setVisible(False)
            self._ch_hline.setVisible(False)
            self.dmm_graph.addItem(self._ch_vline)
            self.dmm_graph.addItem(self._ch_hline)

            # 툴팁 TextItem
            self._ch_tooltip = pg.TextItem(
                text='', color='#FFD740',
                anchor=(0, 1),
                fill=pg.mkBrush(0, 0, 0, 160))
            self._ch_tooltip.setVisible(False)
            self.dmm_graph.addItem(self._ch_tooltip)

            # 데이터를 클로저로 캐펵 (signal에 연결)
            _mv_ref = mv.copy()
            _x_ref  = x

            def _on_mouse_move(pos, _mv=_mv_ref, _x=_x_ref):
                try:
                    if not self.dmm_graph.sceneBoundingRect().contains(pos):
                        self._ch_vline.setVisible(False)
                        self._ch_hline.setVisible(False)
                        self._ch_tooltip.setVisible(False)
                        return
                    mp    = self.dmm_graph.plotItem.vb.mapSceneToView(pos)
                    xi    = int(round(mp.x()))
                    xi    = max(0, min(xi, len(_mv) - 1))
                    yi    = _mv[xi]
                    self._ch_vline.setPos(xi)
                    self._ch_hline.setPos(yi)
                    self._ch_vline.setVisible(True)
                    self._ch_hline.setVisible(True)
                    self._ch_tooltip.setText(f'idx={xi}\n{yi:.4f} {unit_s}')
                    self._ch_tooltip.setPos(xi, yi)
                    self._ch_tooltip.setVisible(True)
                except Exception:
                    pass

            # 이전 신호 연결 해제를 위해 이전 호버 햄들러 저장
            if hasattr(self, '_dmm_proxy') and self._dmm_proxy is not None:
                try:
                    self._dmm_proxy.disconnect()
                except Exception:
                    pass
            self._dmm_proxy = pg.SignalProxy(
                self.dmm_graph.scene().sigMouseMoved,
                rateLimit=30, slot=lambda args: _on_mouse_move(args[0]))

            self.dmm_graph.show()

        else:
            self.dmm_graph.hide()

    # ── 수동 측정 ─────────────────────────────────────────────────
    def _manual_measure_single(self):
        """수동 단발 측정 — 정밀 설정 사용 (NPLC 10, AutoZero ON)"""
        if not self._ensure_dmm_connected('MANUAL'):
            return
        self.dmm_single_btn.setEnabled(False)
        self.dmm_single_btn.setText('측정 중...')
        self.dmm_disp_trigger.setText('● Measuring (Precision)...')
        self.dmm_disp_trigger.setStyleSheet(
            'color:#FFA726;font-size:13px;background:transparent;')
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            if self._dmm_mode == 'VOLT':
                res  = self.dmm.measure_precision_voltage()
                val  = res['value_v']
                unit = 'VDC'
                # 누적 통계에 추가
                self.dmm_accum_values.append(val)
                n = len(self.dmm_accum_values)
                arr = self.dmm_accum_values
                import numpy as _np
                min_v = min(arr);  max_v = max(arr)
                pp    = max_v - min_v
                std   = float(_np.std(arr)) if n > 1 else 0.0
                self._update_dmm_display(
                    val, unit,
                    min_v=min_v, max_v=max_v, pp=pp, std=std,
                    range_info=f'N={n} | NPLC={res["nplc"]:.0f}  AutoZero=ON'
                )
                self.dmm_result_text.append(
                    f"<span style='color:#90CAF9;'>[Single V]</span>  "
                    f"<b>{val*1000:+10.4f} mV</b>  "
                    f"<span style='color:#888;'>(NPLC={res['nplc']:.0f}  {res['elapsed_ms']:.0f}ms  N={n})</span>"
                )
            else:
                res  = self.dmm.measure_precision_current()
                val  = res['value_a']
                unit = 'ADC'
                self.dmm_accum_values.append(val)
                n = len(self.dmm_accum_values)
                arr = self.dmm_accum_values
                import numpy as _np
                min_v = min(arr);  max_v = max(arr)
                pp    = max_v - min_v
                std   = float(_np.std(arr)) if n > 1 else 0.0
                self._update_dmm_display(
                    val, unit,
                    min_v=min_v, max_v=max_v, pp=pp, std=std,
                    range_info=f'N={n} | NPLC={res["nplc"]:.0f}  AutoZero=ON'
                )
                self.dmm_result_text.append(
                    f"<span style='color:#90CAF9;'>[Single I]</span>  "
                    f"<b>{val*1000:+10.4f} mA</b>  "
                    f"<span style='color:#888;'>(NPLC={res['nplc']:.0f}  {res['elapsed_ms']:.0f}ms  N={n})</span>"
                )
        except Exception as e:
            self.dmm_result_text.append(
                f"<b style='color:#FF9800;'>[Single] 오류:</b> {e}")
        finally:
            QApplication.restoreOverrideCursor()
            self.dmm_single_btn.setEnabled(True)
            self.dmm_single_btn.setText('⚡  Single')
            self.dmm_disp_trigger.setText('● Auto Trigger')
            self.dmm_disp_trigger.setStyleSheet(
                'color:#66BB6A;font-size:13px;background:transparent;')

    def _manual_measure_1000(self):
        """수동 1000회 측정 (50µs 간격)"""
        if not self._ensure_dmm_connected('MANUAL'):
            return
        self.dmm_single_btn.setEnabled(False)
        self.dmm_1000_btn.setEnabled(False)
        self.dmm_1000_btn.setText('측정 중...')
        self.dmm_disp_trigger.setText('● Measuring 1000× ...')
        self.dmm_disp_trigger.setStyleSheet(
            'color:#FFA726;font-size:13px;background:transparent;')
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            if self._dmm_mode == 'VOLT':
                res  = self.dmm.measure_dc_voltage(n_samples=1000, interval_us=50.0)
                val  = res['mean_v']
                unit = 'VDC'
                self._update_dmm_display(
                    val, unit,
                    min_v=res['min_v'], max_v=res['max_v'],
                    std=res['std_v'],   pp=res['peak_to_peak_v'],
                    n=res['n_samples'], interval_us=res['interval_us'],
                    values=res['values']
                )
                self.dmm_result_text.append(
                    f"<span style='color:#90CAF9;'>[×1000 V]</span>  "
                    f"mean=<b>{val*1000:+10.4f} mV</b>  "
                    f"<span style='color:#888;'>min={res['min_v']*1000:.4f}  max={res['max_v']*1000:.4f}  "
                    f"std={res['std_v']*1000:.4f}  {res['elapsed_ms']:.0f}ms</span>"
                )
            else:
                res  = self.dmm.measure_dc_current(n_samples=1000, interval_us=1000.0)
                val  = res['mean_a']
                unit = 'ADC'
                self._update_dmm_display(
                    val, unit,
                    min_v=res['min_a'], max_v=res['max_a'],
                    std=res['std_a'],
                    n=res['n_samples'],
                    values=res['values']
                )
                self.dmm_result_text.append(
                    f"<span style='color:#90CAF9;'>[×1000 I]</span>  "
                    f"mean=<b>{val*1000:+10.4f} mA</b>  "
                    f"<span style='color:#888;'>min={res['min_a']*1000:.4f}  max={res['max_a']*1000:.4f}  "
                    f"std={res['std_a']*1000:.4f}  {res['elapsed_ms']:.0f}ms</span>"
                )
        except Exception as e:
            self.dmm_result_text.append(
                f"<b style='color:#FF9800;'>[×1000] 오류:</b> {e}")
        finally:
            QApplication.restoreOverrideCursor()
            self.dmm_single_btn.setEnabled(True)
            self.dmm_1000_btn.setEnabled(True)
            self.dmm_1000_btn.setText('🔁  × 1000  (50 µs)')
            self.dmm_disp_trigger.setText('● Auto Trigger')
            self.dmm_disp_trigger.setStyleSheet(
                'color:#66BB6A;font-size:13px;background:transparent;')

    # ── Scan ──────────────────────────────────────────────────────
    def _scan_dmm_resources(self):
        """LAN(TCP 5025) + USB SCPI 장비 스캔"""
        self.dmm_scan_btn.setEnabled(False)
        self.dmm_scan_btn.setText('...')
        self.dmm_result_text.append('[Scan] 포트 5025 + USB 스캔 중 (최대 ~5초)...')
        QApplication.processEvents()
        try:
            results = self.dmm.list_resources()   # [(id, idn, visa_addr), ...]
            self.dmm_resource_cb.clear()
            if results:
                for ident, idn, visa_addr in results:
                    self.dmm_resource_cb.addItem(
                        f'{visa_addr}  ({idn})', userData=visa_addr)
                self.dmm_resource_cb.setCurrentIndex(0)
                self.dmm_visa_edit.setText(results[0][2])
                lines = '\n'.join(
                    f'  {"→" if i == 0 else " "} {v}  [{d}]'
                    for i, (_, d, v) in enumerate(results)
                )
                self.dmm_result_text.append(
                    f'[Scan] {len(results)}개 발견:\n{lines}')
            else:
                self.dmm_result_text.append(
                    '[Scan] 장비 미발견.\n  • LAN/USB 연결 및 전원 확인')
        except Exception as e:
            self.dmm_result_text.append(f'[Scan] 오류: {e}')
        finally:
            self.dmm_scan_btn.setEnabled(True)
            self.dmm_scan_btn.setText('Scan')


    def update_range_options(self, ch):
        probe = self.ui_state[ch]['probe_cb'].currentText()
        range_cb = self.ui_state[ch]['range_cb']
        
        current_range = range_cb.currentText()
        range_cb.blockSignals(True)
        range_cb.clear()
        
        if probe == "x10":
            options = ["±500mV", "±1V", "±2V", "±5V", "±10V", "±20V", "±50V", "±100V"]
            default = "±5V"
        else:
            options = ["±50mV", "±100mV", "±200mV", "±500mV", "±1V", "±2V", "±5V", "±10V"]
            default = "±500mV"
            
        range_cb.addItems(options)
        
        # Try to keep the previous selection if it exists in the new options
        if current_range in options:
            range_cb.setCurrentText(current_range)
        else:
            range_cb.setCurrentText(default)
            
        range_cb.blockSignals(False)

    def get_full_config(self):
        config = {}
        for ch, widgets in self.ui_state.items():
            mode = widgets['mode_cb'].currentText()
            if mode != "Not Used":
                config[ch] = {
                    'mode': mode,
                    'probe': widgets['probe_cb'].currentText(),
                    'range': widgets['range_cb'].currentText(),
                    'bw_limit': widgets['bw_cb'].currentText()
                }
        return config

    def apply_hardware_settings(self):
        config = self.get_full_config()
        for ch in self.channels:
            if ch in config:
                self.hw.setup_channel(
                    ch, 
                    enabled=True, 
                    range_str=config[ch]['range'], 
                    probe_str=config[ch]['probe'],
                    bw_limit_str=config[ch]['bw_limit']
                )
            else:
                self.hw.setup_channel(ch, enabled=False)

    # ------------------------------------------------------------------
    # DMM 연결 관리
    # ------------------------------------------------------------------
    def _set_dmm_action_buttons_enabled(self, enabled: bool):
        """DMM 동작 버튼(모드 선택 + 측정 + 리셋) 일괄 활성화/비활성화"""
        for btn in (self.dmm_btn_volt, self.dmm_btn_curr,
                    self.dmm_single_btn, self.dmm_1000_btn, self.dmm_reset_stats_btn):
            btn.setEnabled(enabled)

    def toggle_dmm_connection(self):
        _STYLE_CONN = (
            'QPushButton{background:#1565C0;color:white;font-weight:bold;padding:5px;border-radius:4px;}'
            'QPushButton:hover{background:#1976D2;}'
            'QPushButton:pressed{background:#0D47A1;}')
        _STYLE_DISC = (
            'QPushButton{background:#c62828;color:white;font-weight:bold;padding:5px;border-radius:4px;}'
            'QPushButton:hover{background:#e53935;}'
            'QPushButton:pressed{background:#8E0000;}')
        if self.dmm.is_connected:
            self.dmm.disconnect()
            self.dmm_connect_btn.setText('Connect')
            self.dmm_connect_btn.setStyleSheet(_STYLE_CONN)
            self.dmm_status_label.setText('Not Connected')
            self.dmm_status_label.setStyleSheet('color:#888;font-weight:bold;font-size:12px;')
            self.dmm_led.setStyleSheet("background-color: #888888; border-radius: 6px; border: 1px solid #555;")
            self._set_dmm_action_buttons_enabled(False)   # 연결 해제 → 비활성화
        else:
            self.dmm_connect_btn.setEnabled(False)
            self.dmm_connect_btn.setText("Connecting...")
            self.dmm_status_label.setText("Connecting...")
            self.dmm_status_label.setStyleSheet("color:#FFA726;font-weight:bold;font-size:12px;")
            self.dmm_led.setStyleSheet("background-color: #FFA726; border-radius: 6px; border: 1px solid #555;")
            QApplication.processEvents()

            visa_addr = self.dmm_visa_edit.text().strip()
            if not visa_addr:
                self.dmm_result_text.append('[DMM] VISA 주소를 입력하세요.')
                self.dmm_connect_btn.setEnabled(True)
                self.dmm_connect_btn.setText('Connect')
                self.dmm_led.setStyleSheet("background-color: #888888; border-radius: 6px; border: 1px solid #555;")
                self.dmm_status_label.setText('Not Connected')
                self.dmm_status_label.setStyleSheet('color:#888;font-weight:bold;font-size:12px;')
                return
            success, msg = self.dmm.connect(visa_addr)
            self.dmm_connect_btn.setEnabled(True)
            if success:
                self.dmm_connect_btn.setText('Disconnect')
                self.dmm_connect_btn.setStyleSheet(_STYLE_DISC)
                self.dmm_status_label.setText(f'{msg}')
                self.dmm_status_label.setStyleSheet('color:#4CAF50;font-weight:bold;font-size:12px;')
                self.dmm_led.setStyleSheet("background-color: #4CAF50; border-radius: 6px; border: 1px solid #555;")
                self.dmm_result_text.append(f'[DMM] 연결됨: {msg}')
                self._set_dmm_action_buttons_enabled(True)  # 연결 성공 → 활성화
            else:
                self.dmm_connect_btn.setText('Connect')
                self.dmm_connect_btn.setStyleSheet(_STYLE_CONN)
                self.dmm_status_label.setText('Connection Failed')
                self.dmm_status_label.setStyleSheet('color:#f44336;font-weight:bold;font-size:12px;')
                self.dmm_led.setStyleSheet("background-color: #F44336; border-radius: 6px; border: 1px solid #555;")
                self.dmm_result_text.append(f'[DMM] 연결 실패: {msg}')
                self._set_dmm_action_buttons_enabled(False)  # 연결 실패 → 비활성화 유지

    # ------------------------------------------------------------------
    # SELECT 화면 전환
    # ------------------------------------------------------------------
    def _switch_page(self, screen: str):
        """화면 전환 공통 로직 — 수동 버튼 및 SELECT 명령 모두 여기로"""
        ACTIVE = (
            "QPushButton { background-color: #1565C0; color: #fff; "
            "border: 1px solid #1976D2; border-radius: 4px; padding: 0 14px; font-weight: bold; }"
        )
        INACTIVE = (
            "QPushButton { background-color: #2a2a4a; color: #aaa; "
            "border: 1px solid #444; border-radius: 4px; padding: 0 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #3a3a6a; color: #fff; }"
        )
        if screen == 'PICOSCOPE':
            self.stack.setCurrentIndex(0)
            self.nav_btn_scope.setStyleSheet(ACTIVE)
            self.nav_btn_dmm.setStyleSheet(INACTIVE)
        elif screen == '34465A':
            self.stack.setCurrentIndex(1)
            self.nav_btn_scope.setStyleSheet(INACTIVE)
            self.nav_btn_dmm.setStyleSheet(ACTIVE)
        self.current_screen = screen
        print(f'[Screen] Switched to {screen}')

    def on_select_requested(self, screen: str):
        """마스터 SELECT 명령 → 화면 전환 후 SELECT_ACK 반환"""
        self._switch_page(screen)
        self.socket_server.send_select_ack(screen)

    # ------------------------------------------------------------------
    # CE TOS 측정 핸들러
    # ------------------------------------------------------------------
    def _ensure_dmm_connected(self, sn: str) -> bool:
        """DMM 미연결 시 False 수동 측정은 로그만, CE TOS는 소켓 에러도 전송"""
        if not self.dmm.is_connected:
            if sn != 'MANUAL':   # 수동 측정 시 소켓 에러 미전송
                self.socket_server.send_analog_error(sn, 'DMM_NOT_CONNECTED')
            self.dmm_result_text.append(f'[CE TOS] DMM 연결 안 됨 (SN: {sn})')
            return False
        return True

    def on_analog_v1_requested(self, sn: str, channel: str,
                              target_mv: float, tol_mv: float):
        """Item 1: TOS Output — 1000회 측정, MIN/MAX가 다두 범위 이내인지 판정"""
        if not self._ensure_dmm_connected(sn):
            return
        self.reset_dmm_accum_stats(silent=True)   # 소켓 명령 수신 시 자동 누적 리셋
        lower  = target_mv - tol_mv
        upper  = target_mv + tol_mv
        range_info = f'N=1000 | 허용: {lower:.1f} ~ {upper:.1f} mV'
        self.dmm_disp_mode.setText('DC Voltage  │  CE TOS V1')
        self.dmm_disp_trigger.setText(f'● Measuring 1000× — {sn} {channel}')
        self.dmm_disp_trigger.setStyleSheet(
            'color:#FFA726;font-size:13px;background:transparent;')
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            result = self.dmm.measure_dc_voltage(n_samples=1000, interval_us=50.0)
            min_mv = result['min_v'] * 1000.0
            max_mv = result['max_v'] * 1000.0
            passed = (min_mv >= lower) and (max_mv <= upper)
            verdict = 'PASS' if passed else 'FAIL'

            self._update_dmm_display(
                result['mean_v'], 'VDC',
                min_v=result['min_v'], max_v=result['max_v'],
                std=result['std_v'],   pp=result['peak_to_peak_v'],
                n=result['n_samples'], interval_us=result['interval_us'],
                range_info=range_info, verdict=verdict,
                values=result['values'],
                limits=(lower, upper)
            )
            self.socket_server.send_analog_v1_result(sn, channel, passed, min_mv, max_mv)
            color = '#4CAF50' if passed else '#F44336'
            self.dmm_result_text.append(
                f"<b style='color:{color};'>[V1] {sn} {channel}: {verdict}</b>  "
                f"MIN={min_mv:.3f}mV  MAX={max_mv:.3f}mV  "
                f"<span style='color:#888;'>(허용 {lower:.1f}~{upper:.1f}mV)</span>"
            )
        except Exception as e:
            self.socket_server.send_analog_error(sn, 'MEASUREMENT_FAILED', detail=str(e))
            self.dmm_result_text.append(
                f"<b style='color:#FF9800;'>[V1] {sn} {channel}: 측정 오류</b> — {e}")
        finally:
            QApplication.restoreOverrideCursor()
            self.dmm_disp_mode.setText('DC Voltage')
            self.dmm_disp_trigger.setText('● Auto Trigger')
            self.dmm_disp_trigger.setStyleSheet(
                'color:#66BB6A;font-size:13px;background:transparent;')

    def on_analog_v2_requested(self, sn: str, channel: str,
                              lower_mv: float, upper_mv: float):
        """Item 2: TOS Variation — 정밀 단발 1회 측정 (NPLC=10, AutoZero=ON), 범위 판정"""
        if not self._ensure_dmm_connected(sn):
            return
        self.reset_dmm_accum_stats(silent=True)   # 소켓 명령 수신 시 자동 누적 리셋
        range_info = f'N=1 | NPLC=10  AutoZero=ON | 허용: {lower_mv:.1f}~{upper_mv:.1f} mV'
        self.dmm_disp_mode.setText('DC Voltage  │  CE TOS V2')
        self.dmm_disp_trigger.setText(f'● Measuring (Precision) — {sn} {channel}')
        self.dmm_disp_trigger.setStyleSheet(
            'color:#FFA726;font-size:13px;background:transparent;')
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            res      = self.dmm.measure_precision_voltage(nplc=10.0)
            value_v  = res['value_v']
            value_mv = value_v * 1000.0
            passed   = (lower_mv <= value_mv <= upper_mv)
            verdict  = 'PASS' if passed else 'FAIL'

            self._update_dmm_display(
                value_v, 'VDC',
                range_info=range_info, verdict=verdict
            )
            self.socket_server.send_analog_v2_result(sn, channel, passed, value_mv)
            color = '#4CAF50' if passed else '#F44336'
            self.dmm_result_text.append(
                f"<b style='color:{color};'>[V2] {sn} {channel}: {verdict}</b>  "
                f"{value_mv:.4f}mV  "
                f"<span style='color:#888;'>(허용 {lower_mv:.1f}~{upper_mv:.1f}mV)  NPLC=10  {res['elapsed_ms']:.0f}ms</span>"
            )
        except Exception as e:
            self.socket_server.send_analog_error(sn, 'MEASUREMENT_FAILED', detail=str(e))
            self.dmm_result_text.append(
                f"<b style='color:#FF9800;'>[V2] {sn} {channel}: 측정 오류</b> — {e}")
        finally:
            QApplication.restoreOverrideCursor()
            self.dmm_disp_mode.setText('DC Voltage')
            self.dmm_disp_trigger.setText('● Auto Trigger')
            self.dmm_disp_trigger.setStyleSheet(
                'color:#66BB6A;font-size:13px;background:transparent;')

    def on_analog_i_requested(self, sn: str, channel: str,
                             lower_ma: float, upper_ma: float):
        """Item 3: 소비전류 — 정밀 단발 1회 측정 (NPLC=10, AutoZero=ON), 범위 판정"""
        if not self._ensure_dmm_connected(sn):
            return
        self.reset_dmm_accum_stats(silent=True)   # 소켓 명령 수신 시 자동 누적 리셋
        range_info = f'N=1 | NPLC=10  AutoZero=ON | 허용: {lower_ma:.1f}~{upper_ma:.1f} mA'
        self.dmm_disp_mode.setText('DC Current  │  CE TOS I')
        self.dmm_disp_trigger.setText(f'● Measuring (Precision) — {sn} {channel}')
        self.dmm_disp_trigger.setStyleSheet(
            'color:#FFA726;font-size:13px;background:transparent;')
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            res      = self.dmm.measure_precision_current(nplc=10.0)
            value_a  = res['value_a']
            value_ma = value_a * 1000.0
            passed   = (lower_ma <= value_ma <= upper_ma)
            verdict  = 'PASS' if passed else 'FAIL'

            self._update_dmm_display(
                value_a, 'ADC',
                range_info=range_info, verdict=verdict
            )
            self.socket_server.send_analog_i_result(sn, channel, passed, value_ma)
            color = '#4CAF50' if passed else '#F44336'
            self.dmm_result_text.append(
                f"<b style='color:{color};'>[I]  {sn} {channel}: {verdict}</b>  "
                f"{value_ma:.4f}mA  "
                f"<span style='color:#888;'>(허용 {lower_ma:.1f}~{upper_ma:.1f}mA)  NPLC=10  {res['elapsed_ms']:.0f}ms</span>"
            )
        except Exception as e:
            self.socket_server.send_analog_error(sn, 'MEASUREMENT_FAILED', detail=str(e))
            self.dmm_result_text.append(
                f"<b style='color:#FF9800;'>[I]  {sn} {channel}: 측정 오류</b> — {e}")
        finally:
            QApplication.restoreOverrideCursor()
            self.dmm_disp_mode.setText('DC Current')
            self.dmm_disp_trigger.setText('● Auto Trigger')
            self.dmm_disp_trigger.setStyleSheet(
                'color:#66BB6A;font-size:13px;background:transparent;')


    def auto_connect_on_startup(self):
        """프로그램 시작 시 No Scope 체크박스가 꺼져 있으면 자동 연결 시도"""
        if not self.no_scope_chk.isChecked():
            self.toggle_connection()

    def auto_connect_dmm_on_startup(self):
        """저장된 VISA 주소가 있으면 DMM 자동 연결 시도"""
        visa_addr = self.dmm_visa_edit.text().strip()
        if not visa_addr:
            return
        print(f'[DMM] 자동 연결 시도: {visa_addr}')
        self.dmm_status_label.setText('Connecting...')
        self.dmm_status_label.setStyleSheet('color:#FFA726;font-weight:bold;font-size:12px;')
        self.dmm_led.setStyleSheet("background-color: #FFA726; border-radius: 6px; border: 1px solid #555;")
        QApplication.processEvents()

        success, msg = self.dmm.connect(visa_addr)
        if success:
            self.dmm_connect_btn.setText('Disconnect')
            self.dmm_connect_btn.setStyleSheet(
                'QPushButton{background:#c62828;color:white;font-weight:bold;padding:5px;border-radius:4px;}'
                'QPushButton:hover{background:#e53935;}'
                'QPushButton:pressed{background:#8E0000;}')
            self.dmm_status_label.setText(f'{msg}')
            self.dmm_status_label.setStyleSheet(
                'color:#4CAF50;font-weight:bold;font-size:12px;')
            self.dmm_led.setStyleSheet("background-color: #4CAF50; border-radius: 6px; border: 1px solid #555;")
            self.dmm_result_text.append(f'[DMM] 자동 연결됨: {msg}')
            self._set_dmm_action_buttons_enabled(True)   # 자동 연결 성공 → 버튼 활성화
        else:
            self.dmm_status_label.setText('Auto-connect Failed')
            self.dmm_status_label.setStyleSheet(
                'color:#FF9800;font-weight:bold;font-size:12px;')
            self.dmm_led.setStyleSheet("background-color: #FF9800; border-radius: 6px; border: 1px solid #555;")
            self.dmm_result_text.append(f'[DMM] 자동 연결 실패: {msg}')

    def toggle_connection(self):
        if not self.hw.is_open:
            # 연결 시도 중 즉시 UI 피드백 (블로킹 방지)
            self.connect_btn.setEnabled(False)
            self.connect_btn.setText("Connecting...")
            self.scope_led.setStyleSheet("background-color: #FFA726; border-radius: 6px; border: 1px solid #555;")
            self.dev_info_label.setText("Device: Connecting...")
            self.dev_info_label.setStyleSheet("color: #FFA726; font-weight: bold;")
            QApplication.processEvents()

            success, model, serial = self.hw.open()
            self.connect_btn.setEnabled(True)
            if success:
                self.connect_btn.setText("Disconnect Scope")
                self.connect_btn.setStyleSheet(
                    "QPushButton { background-color: #f44336; color: white; font-weight: bold; padding: 10px; border-radius: 4px; }"
                    "QPushButton:hover { background-color: #EF5350; }"
                    "QPushButton:pressed { background-color: #B71C1C; }"
                    "QPushButton:disabled { background-color: #555; color: #888; }"
                )
                self.scope_led.setStyleSheet("background-color: #4CAF50; border-radius: 6px; border: 1px solid #555;")
                self.dev_info_label.setText(f"Device: {model} (S/N: {serial})")
                self.dev_info_label.setStyleSheet("color: green; font-weight: bold;")
                self.start_btn.setEnabled(True)
                self.monitor_btn.setEnabled(True)
                self.apply_hardware_settings()
            else:
                self.connect_btn.setText("Connect Scope")
                self.scope_led.setStyleSheet("background-color: #F44336; border-radius: 6px; border: 1px solid #555;")
                self.dev_info_label.setText("Device: Connection Failed")
                self.dev_info_label.setStyleSheet("color: red; font-weight: bold;")
        else:
            if self.is_monitoring: self.toggle_monitor()
            self.hw.close()
            self.connect_btn.setText("Connect Scope")
            self.connect_btn.setStyleSheet(
                "QPushButton { background-color: #2196F3; color: white; font-weight: bold; padding: 10px; border-radius: 4px; }"
                "QPushButton:hover { background-color: #42A5F5; }"
                "QPushButton:pressed { background-color: #1565C0; }"
                "QPushButton:disabled { background-color: #555; color: #888; }"
            )
            self.scope_led.setStyleSheet("background-color: #888888; border-radius: 6px; border: 1px solid #555;")
            self.dev_info_label.setText("Device: Not Connected")
            self.dev_info_label.setStyleSheet("color: #aaa;")
            self.start_btn.setEnabled(False)
            self.monitor_btn.setEnabled(False)

    def toggle_sim_mode(self):
        self.hw.sim_mode = self.no_scope_chk.isChecked()

    def toggle_monitor(self):
        config = self.get_full_config()
        if not config:
            self.result_text.setText("No channels configured for monitoring.")
            return

        if not self.is_monitoring:
            self.is_monitoring = True
            self.monitor_btn.setText("Stop Monitor")
            self.monitor_btn.setStyleSheet("background-color: #E91E63; color: white; font-weight: bold; padding: 10px;")
            self.start_btn.setEnabled(False)
            
            # Apply settings before capturing
            self.apply_hardware_settings()

            active_channels = list(config.keys())
            if self.radio_stream.isChecked():
                self.hw.start_streaming(active_channels)
                self.monitor_timer.start(50)
            else:
                self.monitor_timer.start(100)
        else:
            self.is_monitoring = False
            self.monitor_timer.stop()
            if self.radio_stream.isChecked():
                self.hw.stop_streaming()
            self.monitor_btn.setText("Start Monitor")
            self.monitor_btn.setStyleSheet("background-color: #9C27B0; color: white; font-weight: bold; padding: 10px;")
            self.start_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # 공통 파형 표시 헬퍼
    # ------------------------------------------------------------------
    def _draw_waveforms(self, data: dict):
        """
        data: {ch: np.array} 딕셔너리
        - 활성 채널만 표시, 나머지 숨김
        - X축: ms 단위
        - Y축: 채널별 12V 간격 오프셋
        """
        sr = self.hw.sample_rate_hz if self.hw.sample_rate_hz > 0 else 10e6
        active = [ch for ch in self.channels if ch in data and len(data[ch]) > 0]

        # X축 범위: 활성 채널 최대 시간
        n_max = max((len(data[ch]) for ch in active), default=0)
        x_end_ms = n_max / sr * 1000
        self.plot_widget.setXRange(0, x_end_ms if x_end_ms > 0 else 3, padding=0.01)

        # Y축: 사용 채널만 가지고 범위 계산
        # 오프셋은 활성 채널 순서대로 0, 12, 24 ... V
        active_offsets = [self.ch_offsets[ch] for ch in active]
        if active_offsets:
            self.plot_widget.setYRange(
                min(active_offsets) - 1,
                max(active_offsets) + 6,
                padding=0
            )

        for ch in self.channels:
            if ch in active:
                offset = self.ch_offsets[ch]
                x = np.arange(len(data[ch])) / sr * 1000  # ms
                self.plot_curves[ch].setData(x=x, y=data[ch] + offset)
                self.plot_curves[ch].show()
            else:
                self.plot_curves[ch].setData([])
                self.plot_curves[ch].hide()

    def monitor_update(self):
        config = self.get_full_config()
        active_channels = list(config.keys())

        if self.radio_stream.isChecked():
            data = self.hw.get_streaming_latest_values(active_channels)
        else:
            data = self.hw.capture_block(active_channels)

        self._draw_waveforms(data)

    def on_start_test_requested(self, products: list):
        self.result_text.append(f"\n[Socket] Start request for {len(products)} products")
        
        # 1. Stop monitor if running
        if self.is_monitoring:
            self.toggle_monitor()
            
        # 2. Automatically Connect if not connected
        if not self.hw.is_open and not self.no_scope_chk.isChecked():
            self.toggle_connection()
            
        if not self.hw.is_open and not self.no_scope_chk.isChecked():
            self.socket_server.send_error("Oscilloscope is not connected")
            return

        # 3. Run test and save result
        self.run_test(products=products)

    def run_test(self, products=None):
        ui_config = self.get_full_config()
        
        test_config = {}
        if products:
            # Build custom config taking Mode from master, Range/Probe from UI
            for prod in products:
                for ch, mode in prod['channels'].items():
                    ui_ch = ui_config.get(ch, {'range': '±5V', 'probe': 'x10', 'bw_limit': '20MHz'})
                    test_config[ch] = {
                        'mode': mode,
                        'range': ui_ch.get('range', '±5V'),
                        'probe': ui_ch.get('probe', 'x10'),
                        'bw_limit': ui_ch.get('bw_limit', '20MHz')
                    }
        else:
            test_config = ui_config
            
        if not test_config:
            msg = "No channels configured for test."
            self.result_text.setText(msg)
            if products: self.socket_server.send_error(msg)
            return
            
        ts = QDateTime.currentDateTime().toString('HH:mm:ss')
        self.result_text.append(
            f"<span style='color:#888;'>[{ts}]</span> "
            f"<b style='color:#89DCEB;'>Testing...</b>"
        )
        QApplication.processEvents()

        try:
            # Apply hardware settings based on test_config
            for ch in self.channels:
                if ch in test_config:
                    self.hw.setup_channel(ch, enabled=True, 
                        range_str=test_config[ch]['range'], 
                        probe_str=test_config[ch]['probe'],
                        bw_limit_str=test_config[ch]['bw_limit'])
                else:
                    self.hw.setup_channel(ch, enabled=False)
            results = self.sequencer.run_universal_test(
                test_config,
                awg_invert=self.awg_invert_chk.isChecked()
            )
            
            # Update Y-axis based on max range for test plot
            max_v = 0.0
            for ch in list(test_config.keys()):
                range_str = test_config[ch]['range']
                try:
                    val_str = range_str.replace("±", "").replace("mV", "").replace("V", "")
                    target_v = float(val_str)
                    if "mV" in range_str: target_v = target_v / 1000.0
                    if target_v > max_v: max_v = target_v
                except:
                    pass
            # 테스트 파형 표시
            self._draw_waveforms(self.sequencer.last_capture)
                
            QApplication.processEvents() # Ensure plot is drawn
            
            # --- Save Raw Data CSV ---
            timestamp = QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss")
            base_dir = _BASE_DIR
            save_dir = os.path.join(base_dir, "results", QDateTime.currentDateTime().toString("yyyyMMdd"))
            os.makedirs(save_dir, exist_ok=True)

            capture_data = self.sequencer.last_capture
            sr = self.hw.sample_rate_hz if self.hw.sample_rate_hz > 0 else 10e6

            saved_csvs = []
            if capture_data:
                active_chs = sorted(capture_data.keys())
                n = max(len(capture_data[ch]) for ch in active_chs)
                t_us = np.arange(n) / sr * 1e6

                if products:
                    # 제품별 해당 채널만 저장
                    for prod in products:
                        sn = prod['sn']
                        prod_chs = sorted(prod['channels'].keys())
                        prod_chs = [ch for ch in prod_chs if ch in capture_data]

                        header = 'time_us,' + ','.join(f'Ch{ch}_V' for ch in prod_chs)
                        cols = [t_us]
                        for ch in prod_chs:
                            v = capture_data[ch]
                            if len(v) < n:
                                v = np.pad(v, (0, n - len(v)), constant_values=np.nan)
                            cols.append(v[:n])
                        matrix = np.column_stack(cols)

                        csv_path = os.path.join(save_dir, f"{sn}_{timestamp}_raw.csv")
                        np.savetxt(csv_path, matrix, delimiter=',',
                                   header=header, comments='', fmt='%.4f')
                        saved_csvs.append(csv_path)
                        print(f"[CSV] saved: {csv_path}  channels={prod_chs}")
                else:
                    # 수동 검사: 전 채널 저장
                    header = 'time_us,' + ','.join(f'Ch{ch}_V' for ch in active_chs)
                    cols = [t_us]
                    for ch in active_chs:
                        v = capture_data[ch]
                        if len(v) < n:
                            v = np.pad(v, (0, n - len(v)), constant_values=np.nan)
                        cols.append(v[:n])
                    matrix = np.column_stack(cols)

                    csv_path = os.path.join(save_dir, f"MANUAL_{timestamp}_raw.csv")
                    np.savetxt(csv_path, matrix, delimiter=',',
                               header=header, comments='', fmt='%.4f')
                    saved_csvs.append(csv_path)
                    print(f"[CSV] saved: {csv_path}")



            # --- Build HTML log & send result ---
            ts = QDateTime.currentDateTime().toString('HH:mm:ss')

            if products:
                # 소켓 검사: 제품별 채널 로그
                result_parts = ['RESULT']
                for prod in products:
                    sn   = prod['sn']
                    chs  = prod['channels']          # {ch: mode}
                    prod_pass = all(
                        results.get(ch, {}).get('pass', False)
                        for ch in chs
                    )
                    prod_color  = '#a6e3a1' if prod_pass else '#f38ba8'
                    prod_icon   = '✔' if prod_pass else '✘'
                    prod_label  = 'PASS' if prod_pass else 'FAIL'

                    self.result_text.append(
                        f"<span style='color:#888;'>[{ts}]</span> "
                        f"<b style='color:#cba6f7;'>{sn}</b>"
                    )
                    for ch, mode in sorted(chs.items()):
                        r      = results.get(ch, {})
                        passed = r.get('pass', False)
                        status = r.get('status', 'unknown')
                        icon   = '✔' if passed else '✘'
                        color  = '#a6e3a1' if passed else '#f38ba8'
                        label  = 'PASS' if passed else 'FAIL'

                        # 모드별 세부 정보
                        detail = ''
                        if status == 'success':
                            if 'measured_ut_us' in r:   # SENT
                                detail = f"UT={r['measured_ut_us']:.3f}µs"
                            elif 'frames' in r:          # SPC
                                n_ok = sum(1 for f in r.get('frames', []) if f.get('pass', False))
                                n_tot = len(r.get('frames', []))
                                detail = f"{n_ok}/{n_tot} frames OK"
                            elif 'v_mean' in r:          # Analog
                                detail = f"{r['v_mean']*1000:.1f}mV p2p={r.get('p2p_noise',0)*1000:.2f}mV"
                        elif status != 'success':
                            detail = r.get('message', status)

                        detail_html = f"  <span style='color:#888; font-size:11px;'>{detail}</span>" if detail else ''
                        self.result_text.append(
                            f"&nbsp;&nbsp;&nbsp;<b style='color:{color};'>{icon} Ch-{ch}</b> "
                            f"<span style='color:#cdd6f4;'>[{mode}]</span> "
                            f"<b style='color:{color};'>{label}</b>{detail_html}"
                        )
                        if r.get('message') and not passed:
                            self.result_text.append(
                                f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                                f"<span style='color:#FAB387; font-size:11px;'>⚠ {r['message']}</span>"
                            )

                    self.result_text.append(
                        f"&nbsp;&nbsp;<b style='color:{prod_color}; font-size:14px;'>"
                        f"{prod_icon} {sn} → {prod_label}</b>"
                    )
                    self.result_text.append("<hr style='border:0; border-top:1px solid #444;'>")
                    result_parts.append(sn)
                    result_parts.append(prod_label)

                # 빈 자리 채우기 (2제품 고정 포맷)
                while len(result_parts) < 5:
                    result_parts.extend(['', ''])
                self.socket_server.send_result(','.join(result_parts[:5]))

            else:
                # 수동 검사: 전체 채널 로그
                self.result_text.append(
                    f"<span style='color:#888;'>[{ts}]</span> "
                    f"<b style='color:#89b4fa;'>Manual Test — {len(saved_csvs)} CSV saved</b>"
                )
                for ch in sorted(results):
                    r      = results[ch]
                    passed = r.get('pass', False)
                    icon   = '✔' if passed else '✘'
                    color  = '#a6e3a1' if passed else '#f38ba8'
                    label  = 'PASS' if passed else 'FAIL'
                    mode   = test_config.get(ch, {}).get('mode', '')

                    detail = ''
                    if r.get('status') == 'success':
                        if 'measured_ut_us' in r:
                            detail = f"UT={r['measured_ut_us']:.3f}µs"
                        elif 'frames' in r:
                            n_ok  = sum(1 for f in r.get('frames', []) if f.get('pass', False))
                            n_tot = len(r.get('frames', []))
                            detail = f"{n_ok}/{n_tot} frames OK"
                        elif 'v_mean' in r:
                            detail = f"{r['v_mean']*1000:.1f}mV p2p={r.get('p2p_noise',0)*1000:.2f}mV"
                    elif r.get('message'):
                        detail = r['message']

                    detail_html = f"  <span style='color:#888; font-size:11px;'>{detail}</span>" if detail else ''
                    self.result_text.append(
                        f"&nbsp;&nbsp;<b style='color:{color};'>{icon} Ch-{ch}</b> "
                        f"<span style='color:#cdd6f4;'>[{mode}]</span> "
                        f"<b style='color:{color};'>{label}</b>{detail_html}"
                    )

        except Exception as e:
            ts = QDateTime.currentDateTime().toString('HH:mm:ss')
            self.result_text.append(
                f"<span style='color:#888;'>[{ts}]</span> "
                f"<b style='color:#f38ba8;'>❌ Error: {e}</b>"
            )
            if products:
                self.socket_server.send_error(str(e))

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)

                    # DMM 설정
                    dmm_cfg = config.get('__dmm__', {})
                    visa_addr = dmm_cfg.get('visa_address', '')
                    if visa_addr:
                        self.dmm_visa_edit.setText(visa_addr)
                    last_screen = dmm_cfg.get('last_screen', 'PICOSCOPE')
                    self._switch_page(last_screen)

                    # PicoScope 채널 설정
                    for ch, settings in config.items():
                        if ch.startswith('__') or ch not in self.ui_state:
                            continue
                        if not isinstance(settings, dict):
                            continue
                        widgets = self.ui_state[ch]
                        
                        idx_mode = widgets['mode_cb'].findText(settings.get('mode', 'Not Used'))
                        if idx_mode >= 0: widgets['mode_cb'].setCurrentIndex(idx_mode)
                        
                        idx_probe = widgets['probe_cb'].findText(settings.get('probe', 'x10'))
                        if idx_probe >= 0: widgets['probe_cb'].setCurrentIndex(idx_probe)
                        
                        self.update_range_options(ch)
                        
                        idx_range = widgets['range_cb'].findText(settings.get('range', '±5V'))
                        if idx_range >= 0: widgets['range_cb'].setCurrentIndex(idx_range)
                        
                        idx_bw = widgets['bw_cb'].findText(settings.get('bw_limit', '20MHz'))
                        if idx_bw >= 0: widgets['bw_cb'].setCurrentIndex(idx_bw)
            except Exception as e:
                print(f'Failed to load config: {e}')

    def save_config(self):
        full_state = {}
        # PicoScope 채널 설정
        for ch, widgets in self.ui_state.items():
            full_state[ch] = {
                'mode':     widgets['mode_cb'].currentText(),
                'probe':    widgets['probe_cb'].currentText(),
                'range':    widgets['range_cb'].currentText(),
                'bw_limit': widgets['bw_cb'].currentText()
            }
        # DMM / 화면 설정
        full_state['__dmm__'] = {
            'visa_address': self.dmm_visa_edit.text().strip(),
            'last_screen':  self.current_screen,
        }
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(full_state, f, indent=4)
        except Exception as e:
            print(f'Failed to save config: {e}')

    def closeEvent(self, event):
        self.save_config()
        if hasattr(self, 'socket_server'):
            self.socket_server.close()
        if self.is_monitoring:
            self.toggle_monitor()
        self.hw.close()
        if self.dmm.is_connected:
            self.dmm.disconnect()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
