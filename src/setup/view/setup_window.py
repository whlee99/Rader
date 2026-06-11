"""
src/setup/view/setup_window.py
Setup UI 메인 윈도우 — 4개 탭 구성.

탭 1: 브로커 연결 & 장치 감지
탭 2: 장치 위치 매핑  (MAC 나열 → 위치 드롭다운 선택)
탭 3: Calibration
탭 4: Config 저장 & SSH Push
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QTabWidget, QGroupBox,
    QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QSpinBox, QDoubleSpinBox,
    QTextEdit, QSplitter, QFileDialog,
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

        self._tabs.addTab(self._tab_connection(),  "① 브로커 연결")
        self._tabs.addTab(self._tab_mapping(),     "② 장치 매핑")
        self._tabs.addTab(self._tab_calibration(), "③ Calibration")
        self._tabs.addTab(self._tab_local_save(),  "④ 로컬 저장")
        self._tabs.addTab(self._tab_ssh_push(),    "⑤ SSH Push")

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

    # ── 탭 2: 장치 위치 매핑 ──────────────────────────────────────────────────
    def _tab_mapping(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)

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

        self.s2_table = QTableWidget(0, 4)
        self.s2_table.setHorizontalHeaderLabels(["MAC 주소", "물리 위치", "활성 센서 수", "마지막 수신"])
        self.s2_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.s2_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.s2_table.setEditTriggers(QTableWidget.NoEditTriggers)
        s2_lay.addWidget(self.s2_table)
        lay.addWidget(s2_box, stretch=1)

        # 저장 버튼
        save_btn = QPushButton("매핑 적용 (메모리에 저장)")
        save_btn.clicked.connect(self._on_apply_mapping)
        lay.addWidget(save_btn, alignment=Qt.AlignRight)

        return w

    # ── 탭 3: Calibration ─────────────────────────────────────────────────────
    def _tab_calibration(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)

        # 파라미터
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
        form.addRow("sensor_gap  (S1-L/R 사이 거리, 단위: m) :", self.gap_spin)

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
        self.threshold_spin.setToolTip("S2 장애물 경보 발생 기준 거리 (쯀티미터)")
        form.addRow("threshold  (장애물 경보 거리, 단위: cm) :", self.threshold_spin)

        lay.addWidget(param_box)

        # 기울기 실시간 미리보기
        tilt_box = QGroupBox("기울기 실시간 미리보기 (탭 1에서 수신 중이어야 동작)")
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
        lay.addWidget(tilt_box)

        # 파라미터 적용 버튼
        apply_btn = QPushButton("파라미터 적용")
        apply_btn.setToolTip("목록에만 저장됩니다.  파일 저장은 탭 4 "\
                             "[로컈 저장]에서 하세요.")
        apply_btn.clicked.connect(self._on_apply_calib)
        lay.addWidget(apply_btn, alignment=Qt.AlignRight)
        lay.addStretch()

        return w

    # ── 탭 4: 저장 / Push ─────────────────────────────────────────────────────
    # ── 탭 4: 로컬 저장 ──────────────────────────────────────────────────────
    def _tab_local_save(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)

        # Config 미리보기
        preview_box = QGroupBox("Config JSON 미리보기")
        preview_lay = QVBoxLayout(preview_box)
        self.config_preview = QTextEdit()
        self.config_preview.setReadOnly(True)
        self.config_preview.setFont(QFont("Consolas", 9))
        preview_lay.addWidget(self.config_preview)

        refresh_btn = QPushButton("미리보기 갱신")
        refresh_btn.setFixedWidth(110)
        refresh_btn.clicked.connect(self._on_refresh_preview)
        preview_lay.addWidget(refresh_btn, alignment=Qt.AlignRight)
        lay.addWidget(preview_box, stretch=1)

        # 저장 경로 선택
        save_box = QGroupBox("로컬 파일 저장  (한글 경로 지원)")
        save_lay = QVBoxLayout(save_box)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("저장 경로 :"))
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setPlaceholderText("파일 선택 버튼 이용 또는 직접 입력")
        path_row.addWidget(self.save_path_edit, stretch=1)
        browse_btn = QPushButton("파일 선택...")
        browse_btn.setFixedWidth(100)
        browse_btn.clicked.connect(self._on_browse_save_path)
        path_row.addWidget(browse_btn)
        save_lay.addLayout(path_row)

        self.local_save_status_lbl = QLabel("")
        self.local_save_status_lbl.setStyleSheet("font-size:11px;")
        save_lay.addWidget(self.local_save_status_lbl)

        save_btn = QPushButton("선택한 경로에 저장")
        save_btn.setObjectName("startBtn")
        save_btn.clicked.connect(self._on_save_local_file)
        save_lay.addWidget(save_btn, alignment=Qt.AlignRight)
        lay.addWidget(save_box)

        return w

    # ── 탭 5: SSH Push ────────────────────────────────────────────────────────
    def _tab_ssh_push(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)

        info = QLabel(
            "RPi4 에 SSH(SCP)로 config.json 을 전송합니다.\n"
            "실제 장비 연결 시에만 필요합니다. 시뮬레이션 중에는 '④ 로컬 저장' 탭을 사용하세요."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa; font-size:11px;")
        lay.addWidget(info)

        ssh_box = QGroupBox("SSH 접속 정보")
        ssh_form = QFormLayout(ssh_box)
        ssh_form.setLabelAlignment(Qt.AlignRight)

        self.ssh_host_edit = QLineEdit("192.168.0.203")
        self.ssh_user_edit = QLineEdit("pi")
        self.ssh_pass_edit = QLineEdit()
        self.ssh_pass_edit.setEchoMode(QLineEdit.Password)
        self.ssh_path_edit = QLineEdit("/etc/rader/config.json")

        ssh_form.addRow("Host :",       self.ssh_host_edit)
        ssh_form.addRow("User :",       self.ssh_user_edit)
        ssh_form.addRow("Password :",   self.ssh_pass_edit)
        ssh_form.addRow("원격 경로 :",  self.ssh_path_edit)
        lay.addWidget(ssh_box)

        self.ssh_status_lbl = QLabel("")
        self.ssh_status_lbl.setWordWrap(True)
        lay.addWidget(self.ssh_status_lbl)

        push_btn = QPushButton("SSH Push 실행 → RPi4")
        push_btn.setObjectName("pushBtn")
        push_btn.clicked.connect(self._on_ssh_push)
        lay.addWidget(push_btn, alignment=Qt.AlignRight)
        lay.addStretch()

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
        self._vm.ssh_result.connect(self._on_ssh_result)
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
                s2_lbl = dev.s2[0]    if dev and dev.s2    else ""
                act    = dev.active_s2 if dev               else 1

                self.s2_table.setItem(row, 0, QTableWidgetItem(snap.mac))
                cb = self._make_combo(S2_POSITION_OPTIONS, s2_lbl)
                self.s2_table.setCellWidget(row, 1, cb)

                spin = QSpinBox()
                spin.setRange(1, 10)
                spin.setValue(act)
                self.s2_table.setCellWidget(row, 2, spin)
                self.s2_table.setItem(row, 3, QTableWidgetItem(snap.last_seen))
        else:
            for row, snap in enumerate(snaps):
                self.s2_table.setItem(row, 3, QTableWidgetItem(snap.last_seen))

    @staticmethod
    def _make_combo(options: list, current: str) -> QComboBox:
        cb = QComboBox()
        cb.addItems(options)
        if current in options:
            cb.setCurrentText(current)
        return cb

    @Slot()
    def _on_apply_mapping(self):
        """탭 2 테이블의 현재 값을 ViewModel 에 저장"""
        # S1
        for row in range(self.s1_table.rowCount()):
            mac = self.s1_table.item(row, 0).text()
            cb  = self.s1_table.cellWidget(row, 1)
            s1_val = cb.currentText() if cb else ""
            s1_role = "" if s1_val == "(unset)" else s1_val
            self._vm.update_device_mapping(mac, "S1", s1_role=s1_role)

        # S2
        for row in range(self.s2_table.rowCount()):
            mac  = self.s2_table.item(row, 0).text()
            cb   = self.s2_table.cellWidget(row, 1)
            spin = self.s2_table.cellWidget(row, 2)
            lbl  = cb.currentText() if cb else ""
            act  = spin.value()     if spin else 1
            s2_labels = ["" if lbl == "(unset)" else lbl]
            self._vm.update_device_mapping(mac, "S2",
                                            s2_labels=s2_labels,
                                            active_s2=act)

        self._append_log("매핑 적용 완료")
        self._on_refresh_preview()

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

    @Slot()
    def _on_apply_calib(self):
        self._vm.update_calib_params(
            sensor_gap_cm  = self.gap_spin.value() * 100,      # m → cm 변환
            tilt_limit_deg = self.tilt_limit_spin.value(),
            threshold_mm   = self.threshold_spin.value() * 10, # cm → mm 변환
        )
        self._append_log("Calibration 파라미터 적용 완료")

    @Slot()
    def _on_refresh_preview(self):
        self.config_preview.setPlainText(self._vm.get_config().to_json())

    @Slot()
    def _on_browse_save_path(self):
        """QFileDialog — 한글 경로 포함 원시 문자열 반환 (nativeDialog 사용)"""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "저장 파일 선택",
            self.save_path_edit.text() or "rader_config.json",
            "JSON 파일 (*.json);;All Files (*)",
        )
        if path:
            self.save_path_edit.setText(path)

    @Slot()
    def _on_save_local_file(self):
        path = self.save_path_edit.text().strip()
        if not path:
            self.local_save_status_lbl.setText("⚠ 저장 경로를 지정하세요.")
            self.local_save_status_lbl.setStyleSheet("color:#FFC107;")
            return
        ok, msg = self._vm.save_config_to_path(path)
        if ok:
            self.local_save_status_lbl.setText(f"✓ {msg}")
            self.local_save_status_lbl.setStyleSheet("color:#4caf50;")
        else:
            self.local_save_status_lbl.setText(f"✗ {msg}")
            self.local_save_status_lbl.setStyleSheet("color:#f44336;")
        self._append_log(msg)

    @Slot()
    def _on_ssh_push(self):
        self.ssh_status_lbl.setText("전송 중...")
        self.ssh_status_lbl.setStyleSheet("color:#FFC107;")
        self._vm.ssh_push(
            host        = self.ssh_host_edit.text().strip(),
            user        = self.ssh_user_edit.text().strip(),
            password    = self.ssh_pass_edit.text(),
            remote_path = self.ssh_path_edit.text().strip(),
        )

    @Slot(bool, str)
    def _on_ssh_result(self, ok: bool, msg: str):
        if ok:
            self.ssh_status_lbl.setText(f"✓ {msg}")
            self.ssh_status_lbl.setStyleSheet("color:#4caf50;")
        else:
            self.ssh_status_lbl.setText(f"✗ {msg}")
            self.ssh_status_lbl.setStyleSheet("color:#f44336;")
        self._append_log(msg)

    def _append_log(self, msg: str):
        self.conn_log.append(msg)
        self.conn_log.verticalScrollBar().setValue(
            self.conn_log.verticalScrollBar().maximum())

    def closeEvent(self, event):
        self._vm.cleanup()
        event.accept()
