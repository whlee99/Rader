"""
src/setup/view/setup_window.py
Setup UI 메인 윈도우 — 3개 탭 구성.

탭 1: 브로커 연결 & 장치 감지
탭 2: 장치현장구성 (장치 위치 매핑 + Calibration + 즉시 전송)
탭 3: 설정 보기 (전송된 config JSON 표시)
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QTabWidget, QGroupBox,
    QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QSpinBox, QDoubleSpinBox,
    QTextEdit,
    QScrollArea, QFrame,
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, Slot

from ..viewmodel.setup_viewmodel import SetupViewModel, DeviceSnapshot
from ..model.config_model import RaderConfig

STYLESHEET = """
QWidget          { background-color:#2E2E2E; color:#FFFFFF; font-family:Arial; font-size:12px; }
QTabWidget::pane { border:1px solid #555; }
QTabBar::tab     { background:#3a3a3a; color:#aaa; padding:6px 14px; border:1px solid #555; }
QTabBar::tab:selected { background:#2E2E2E; color:#fff; border-bottom:none; }
QGroupBox        { font-size:13px; font-weight:bold; border:1px solid #555;
                   border-radius:5px; margin-top:1ex; }
QGroupBox::title { subcontrol-origin:margin; subcontrol-position:top center; padding:0 4px; }
QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox {
    background:#3a3a3a; border:1px solid #666; border-radius:3px;
    padding:3px 6px; color:white; }
QComboBox        { background:#3a3a3a; border:1px solid #666; border-radius:3px;
                   padding:3px 6px; color:white; }
QComboBox QAbstractItemView { background:#3a3a3a; color:white; }
QPushButton      { background:#555; border:1px solid #777; padding:4px 12px; border-radius:3px; }
QPushButton:hover   { background:#666; }
QPushButton:pressed { background:#777; }
QPushButton#startBtn { background:#2e7d32; color:white; font-weight:bold; }
QPushButton#stopBtn  { background:#c62828; color:white; font-weight:bold; }
QPushButton#pushBtn  { background:#1565c0; color:white; font-weight:bold; }
QTableWidget     { background:#3a3a3a; gridline-color:#555; }
QHeaderView::section { background:#444; border:1px solid #555; padding:4px; }
"""

_CONN_STYLE = {True: "color:#4caf50; font-weight:bold;",
               False: "color:#aaa;   font-weight:bold;"}

# S1 위치 선택지
S1_POSITION_OPTIONS = ["(unset)", "L", "R"]
# S2 위치 선택지 — config에 저장되는 값이므로 영어로 고정
S2_POSITION_OPTIONS = ["(unset)", "pos1", "pos2", "pos3", "pos4", "pos5",
                        "pos6", "pos7", "pos8", "pos9", "pos10"]


class SetupWindow(QMainWindow):
    def __init__(self, vm: SetupViewModel):
        super().__init__()
        self._vm = vm
        self.setWindowTitle("Srader Setup — 초기 설정 도구")
        self.resize(820, 660)
        self._build_ui()
        self._bind()

    # ─────────────────────────────────────────────────────────────────────────
    # UI 구성
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        self._tabs.addTab(self._tab_connection(),   "① 브로커 연결")
        self._tabs.addTab(self._tab_field_config(), "② 장치현장구성")
        self._tabs.addTab(self._tab_config_view(),  "③ 설정 보기")

    # ── 탭 1: 브로커 연결 ─────────────────────────────────────────────────────
    def _tab_connection(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)

        # 연결 설정
        conn_box = QGroupBox("브로커 연결 설정")
        conn_lay = QHBoxLayout(conn_box)

        conn_lay.addWidget(QLabel("Broker IP :"))
        self.broker_edit = QLineEdit("192.168.0.203")
        self.broker_edit.setFixedWidth(160)
        conn_lay.addWidget(self.broker_edit)

        conn_lay.addWidget(QLabel("Port :"))
        self.port_edit = QLineEdit("1883")
        self.port_edit.setFixedWidth(60)
        conn_lay.addWidget(self.port_edit)

        conn_lay.addSpacing(16)
        self.conn_btn = QPushButton("연결")
        self.conn_btn.setObjectName("startBtn")
        self.conn_btn.setFixedWidth(90)
        self.conn_btn.clicked.connect(self._on_connect)
        conn_lay.addWidget(self.conn_btn)

        self.disconn_btn = QPushButton("해제")
        self.disconn_btn.setObjectName("stopBtn")
        self.disconn_btn.setFixedWidth(90)
        self.disconn_btn.setEnabled(False)
        self.disconn_btn.clicked.connect(self._on_disconnect)
        conn_lay.addWidget(self.disconn_btn)

        conn_lay.addSpacing(16)
        self.conn_status_lbl = QLabel("● 미연결")
        self.conn_status_lbl.setStyleSheet(_CONN_STYLE[False])
        conn_lay.addWidget(self.conn_status_lbl)
        conn_lay.addStretch()
        lay.addWidget(conn_box)

        # 감지된 장치 목록
        dev_box = QGroupBox("수신된 장치 목록 (자동 감지)")
        dev_lay = QVBoxLayout(dev_box)

        self.device_table = QTableWidget(0, 4)
        self.device_table.setHorizontalHeaderLabels(["MAC 주소", "타입", "마지막 수신", "최신 값"])
        self.device_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.device_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.device_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.device_table.setEditTriggers(QTableWidget.NoEditTriggers)
        dev_lay.addWidget(self.device_table)

        clr_dev_btn = QPushButton("목록 지우기")
        clr_dev_btn.setFixedWidth(90)
        clr_dev_btn.clicked.connect(self._vm.clear_devices)
        dev_lay.addWidget(clr_dev_btn, alignment=Qt.AlignRight)
        lay.addWidget(dev_box, stretch=1)

        # 로그
        log_box = QGroupBox("수신 로그")
        log_lay = QVBoxLayout(log_box)
        self.conn_log = QTextEdit()
        self.conn_log.setReadOnly(True)
        self.conn_log.setFont(QFont("Consolas", 8))
        self.conn_log.setFixedHeight(100)
        log_lay.addWidget(self.conn_log)
        clr = QPushButton("지우기")
        clr.setFixedWidth(70)
        clr.clicked.connect(self.conn_log.clear)
        log_lay.addWidget(clr, alignment=Qt.AlignRight)
        lay.addWidget(log_box)

        return w

    # ── 탭 2: 장치현장구성 (매핑 + Calibration) ────────────────────────────────
    def _tab_field_config(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        lay.setContentsMargins(4, 4, 4, 4)

        # ─ 장치 매핑 ─────────────────────────────────────────────────────────
        info = QLabel(
            "수신된 MAC 별로 물리 위치를 지정하세요.  "
            "S1: ESP32 1대 = TFmini 1개, 역할(L/R) 지정  |  "
            "S2: 물리 위치 레이블 + 활성 센서 수"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa; font-size:11px;")
        lay.addWidget(info)

        # S1 매핑 테이블
        s1_box = QGroupBox("S1 장치 매핑 (TFmini Plus)")
        s1_lay = QVBoxLayout(s1_box)

        self.s1_table = QTableWidget(0, 3)
        self.s1_table.setHorizontalHeaderLabels(["MAC 주소", "역할 (L / R)", "마지막 수신"])
        self.s1_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.s1_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.s1_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.s1_table.setFixedHeight(130)
        s1_lay.addWidget(self.s1_table)
        lay.addWidget(s1_box)

        # S2 매핑 테이블
        s2_box = QGroupBox("S2 장치 매핑 (VL53L5CX)")
        s2_lay = QVBoxLayout(s2_box)

        self.s2_table = QTableWidget(0, 3)
        self.s2_table.setHorizontalHeaderLabels(["MAC 주소", "물리 위치", "마지막 수신"])
        self.s2_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.s2_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.s2_table.setEditTriggers(QTableWidget.NoEditTriggers)
        s2_lay.addWidget(self.s2_table)
        lay.addWidget(s2_box, stretch=1)

        # 구분선
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#555;")
        lay.addWidget(sep)

        # ─ Calibration 파라미터 (좌) ↔ 기울기 미리보기 (우) ─────────────────
        mid_row = QHBoxLayout()
        mid_row.setSpacing(8)

        # 왼쪽: Calibration 파라미터
        param_box = QGroupBox("Calibration 파라미터")
        form      = QFormLayout(param_box)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        form.setLabelAlignment(Qt.AlignRight)

        self.gap_spin = QDoubleSpinBox()
        self.gap_spin.setRange(0.01, 20.0)
        self.gap_spin.setSingleStep(0.1)
        self.gap_spin.setDecimals(2)
        self.gap_spin.setSuffix(" m")
        self.gap_spin.setValue(0.5)
        self.gap_spin.setToolTip("S1-L 과 S1-R 센서 사이의 물리적 거리 (미터)")
        form.addRow("sensor_gap  (S1-L/R 사이 거리, m) :", self.gap_spin)

        self.tilt_limit_spin = QDoubleSpinBox()
        self.tilt_limit_spin.setRange(0.1, 90.0)
        self.tilt_limit_spin.setSingleStep(0.5)
        self.tilt_limit_spin.setDecimals(1)
        self.tilt_limit_spin.setSuffix(" °")
        self.tilt_limit_spin.setValue(15.0)
        form.addRow("tilt_limit_deg (기울기 경보 한계) :", self.tilt_limit_spin)

        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(5, 500)
        self.threshold_spin.setSingleStep(5)
        self.threshold_spin.setSuffix(" cm")
        self.threshold_spin.setValue(30)
        self.threshold_spin.setToolTip("S2 장애물 경보 발생 기준 거리 (센티미터)")
        form.addRow("threshold  (장애물 경보 거리, cm) :", self.threshold_spin)

        mid_row.addWidget(param_box, stretch=1)

        # 오른쪽: 기울기 실시간 미리보기
        tilt_box = QGroupBox("기울기 실시간 미리보기 (탭①에서 수신 중이어야 동작)")
        tilt_lay = QVBoxLayout(tilt_box)

        vals_row = QHBoxLayout()
        self.s1l_lbl   = QLabel("S1-L: -- cm")
        self.s1r_lbl   = QLabel("S1-R: -- cm")
        self.tilt_lbl  = QLabel("기울기: --°")
        self.tilt_lbl.setStyleSheet("font-size:18px; font-weight:bold; color:#FFC107;")
        vals_row.addWidget(self.s1l_lbl)
        vals_row.addStretch()
        vals_row.addWidget(self.tilt_lbl)
        vals_row.addStretch()
        vals_row.addWidget(self.s1r_lbl)
        tilt_lay.addLayout(vals_row)

        self.baseline_lbl = QLabel("현재 baseline_offset: 0.000°")
        self.baseline_lbl.setStyleSheet("color:#aaa; font-size:11px;")
        tilt_lay.addWidget(self.baseline_lbl)

        baseline_btn = QPushButton("현재 상태를 수평 기준으로 저장 (Baseline 캡처)")
        baseline_btn.clicked.connect(self._on_capture_baseline)
        tilt_lay.addWidget(baseline_btn)
        tilt_lay.addStretch()

        mid_row.addWidget(tilt_box, stretch=1)
        lay.addLayout(mid_row)

        # ─ Apply 버튼 & 전송 상태 ─────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.apply_status_lbl = QLabel("")
        self.apply_status_lbl.setWordWrap(True)
        btn_row.addWidget(self.apply_status_lbl, stretch=1)

        apply_btn = QPushButton("▶  Apply  —  매핑 & 파라미터 적용 후 즉시 전송")
        apply_btn.setObjectName("pushBtn")
        apply_btn.setFixedHeight(32)
        apply_btn.clicked.connect(self._on_apply_all)
        btn_row.addWidget(apply_btn)
        lay.addLayout(btn_row)

        scroll.setWidget(w)
        return scroll

    # ── 탭 3: 설정 보기 ──────────────────────────────────────────────────────
    def _tab_config_view(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)

        view_box = QGroupBox("전송된 Config JSON")
        view_lay = QVBoxLayout(view_box)
        self.config_preview = QTextEdit()
        self.config_preview.setReadOnly(True)
        self.config_preview.setFont(QFont("Consolas", 9))
        view_lay.addWidget(self.config_preview)
        lay.addWidget(view_box, stretch=1)

        return w

    # ─────────────────────────────────────────────────────────────────────────
    # ViewModel 바인딩
    # ─────────────────────────────────────────────────────────────────────────
    def _bind(self):
        self._vm.device_list_updated.connect(self._on_device_list)
        self._vm.tilt_preview_updated.connect(self._on_tilt_preview)
        self._vm.log_signal.connect(self._append_log)
        self._vm.mqtt_connected.connect(self._on_mqtt_connected)
        self._vm.mqtt_disconnected.connect(self._on_mqtt_disconnected)
        self._vm.publish_result.connect(self._on_publish_result)
        self._vm.config_preview_updated.connect(self.config_preview.setPlainText)

    # ─────────────────────────────────────────────────────────────────────────
    # 슬롯
    # ─────────────────────────────────────────────────────────────────────────
    @Slot()
    def _on_connect(self):
        broker = self.broker_edit.text().strip()
        port   = int(self.port_edit.text().strip() or "1883")
        self._vm.connect_broker(broker, port)
        self.conn_btn.setEnabled(False)
        self.disconn_btn.setEnabled(True)

    @Slot()
    def _on_disconnect(self):
        self._vm.disconnect_broker()

    @Slot()
    def _on_mqtt_connected(self):
        self.conn_status_lbl.setText("● 수신 중")
        self.conn_status_lbl.setStyleSheet(_CONN_STYLE[True])

    @Slot()
    def _on_mqtt_disconnected(self):
        self.conn_status_lbl.setText("● 미연결")
        self.conn_status_lbl.setStyleSheet(_CONN_STYLE[False])
        self.conn_btn.setEnabled(True)
        self.disconn_btn.setEnabled(False)

    @Slot(list)
    def _on_device_list(self, snapshots: list):
        """탭 1 장치 목록 + 탭 2 매핑 테이블 동기 갱신"""
        # ── 탭 1: 장치 목록 ──────────────────────────────────────────────────
        self.device_table.setRowCount(len(snapshots))
        for row, snap in enumerate(snapshots):
            self.device_table.setItem(row, 0, QTableWidgetItem(snap.mac))
            self.device_table.setItem(row, 1, QTableWidgetItem(snap.dtype))
            self.device_table.setItem(row, 2, QTableWidgetItem(snap.last_seen))
            if snap.dtype == "S1":
                val_text = "  /  ".join(f"{v} cm" for v in snap.s1_values)
            else:
                val_text = f"최솟값 {snap.s2_values[0]} mm" if snap.s2_values else "--"
            self.device_table.setItem(row, 3, QTableWidgetItem(val_text))

        # ── 탭 2: 매핑 테이블 갱신 ───────────────────────────────────────────
        s1_snaps = [s for s in snapshots if s.dtype == "S1"]
        s2_snaps = [s for s in snapshots if s.dtype == "S2"]
        self._refresh_s1_table(s1_snaps)
        self._refresh_s2_table(s2_snaps)

    def _refresh_s1_table(self, snaps: list):
        cfg = self._vm.get_config()
        if self.s1_table.rowCount() != len(snaps):
            self.s1_table.setRowCount(len(snaps))
            for row, snap in enumerate(snaps):
                dev    = cfg.get_device(snap.mac)
                s1_role = dev.s1 if dev else ""

                self.s1_table.setItem(row, 0, QTableWidgetItem(snap.mac))
                cb = self._make_combo(S1_POSITION_OPTIONS, s1_role)
                self.s1_table.setCellWidget(row, 1, cb)
                self.s1_table.setItem(row, 2, QTableWidgetItem(snap.last_seen))
        else:
            for row, snap in enumerate(snaps):
                self.s1_table.setItem(row, 2, QTableWidgetItem(snap.last_seen))

    def _refresh_s2_table(self, snaps: list):
        cfg = self._vm.get_config()
        if self.s2_table.rowCount() != len(snaps):
            self.s2_table.setRowCount(len(snaps))
            for row, snap in enumerate(snaps):
                dev    = cfg.get_device(snap.mac)
                s2_lbl = dev.s2[0] if dev and dev.s2 else ""

                self.s2_table.setItem(row, 0, QTableWidgetItem(snap.mac))
                cb = self._make_combo(S2_POSITION_OPTIONS, s2_lbl)
                self.s2_table.setCellWidget(row, 1, cb)
                self.s2_table.setItem(row, 2, QTableWidgetItem(snap.last_seen))
        else:
            for row, snap in enumerate(snaps):
                self.s2_table.setItem(row, 2, QTableWidgetItem(snap.last_seen))

    @staticmethod
    def _make_combo(options: list, current: str) -> QComboBox:
        cb = QComboBox()
        cb.addItems(options)
        if current in options:
            cb.setCurrentText(current)
        return cb

    @Slot()
    def _on_apply_mapping(self):
        """S1/S2 테이블의 현재 값을 ViewModel 에 저장 (내부 헬퍼)"""
        for row in range(self.s1_table.rowCount()):
            mac    = self.s1_table.item(row, 0).text()
            cb     = self.s1_table.cellWidget(row, 1)
            s1_val = cb.currentText() if cb else ""
            self._vm.update_device_mapping(mac, "S1",
                                            s1_role="" if s1_val == "(unset)" else s1_val)

        for row in range(self.s2_table.rowCount()):
            mac  = self.s2_table.item(row, 0).text()
            cb   = self.s2_table.cellWidget(row, 1)
            lbl  = cb.currentText() if cb else ""
            self._vm.update_device_mapping(mac, "S2",
                                            s2_labels=["" if lbl == "(unset)" else lbl],
                                            active_s2=64)

    @Slot()
    def _on_apply_all(self):
        """매핑 + Calibration 파라미터를 적용하고 즉시 MQTT 전송."""
        # 1. 매핑 적용
        self._on_apply_mapping()

        # 2. Calibration 파라미터 적용
        self._vm.update_calib_params(
            sensor_gap_cm  = self.gap_spin.value() * 100,       # m → cm
            tilt_limit_deg = self.tilt_limit_spin.value(),
            threshold_mm   = self.threshold_spin.value() * 10,  # cm → mm
        )

        # 3. 즉시 전송
        self.apply_status_lbl.setText("전송 중…")
        self.apply_status_lbl.setStyleSheet("color:#FFC107;")
        self._vm.mqtt_publish_config()

    @Slot(float, int, int)
    def _on_tilt_preview(self, tilt_deg: float, left_cm: int, right_cm: int):
        self.s1l_lbl.setText(f"S1-L: {left_cm} cm")
        self.s1r_lbl.setText(f"S1-R: {right_cm} cm")
        self.tilt_lbl.setText(f"기울기: {tilt_deg:+.2f}°")
        cfg = self._vm.get_config()
        self.baseline_lbl.setText(f"현재 baseline_offset: {cfg.baseline_offset:.3f}°")

    @Slot()
    def _on_capture_baseline(self):
        self._vm.capture_baseline()

    @Slot(bool, str)
    def _on_publish_result(self, ok: bool, msg: str):
        if ok:
            self.apply_status_lbl.setText(f"✓ {msg}")
            self.apply_status_lbl.setStyleSheet("color:#4caf50;")
        else:
            self.apply_status_lbl.setText(f"✗ {msg}")
            self.apply_status_lbl.setStyleSheet("color:#f44336;")
        self._append_log(msg)

    def _append_log(self, msg: str):
        self.conn_log.append(msg)
        self.conn_log.verticalScrollBar().setValue(
            self.conn_log.verticalScrollBar().maximum())

    def closeEvent(self, event):
        self._vm.cleanup()
        event.accept()
