"""
view/dashboard.py
Srader Operation UI 메인 윈도우.
ViewModel 시그널에 바인딩하여 화면 갱신. 직접 데이터 계산 없음.
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel,
    QPushButton, QFrame,
)
from PySide6.QtCore import Qt, Slot

from .widgets import (
    Constants, DisplayMode,
    TiltIndicatorWidget,
    ObstacleColumnWidget,
    ColorBarWidget,
    BlinkDot,
)
from ..viewmodel.monitor_viewmodel import MonitorViewModel, StatusInfo

STYLESHEET = """
QWidget {
    background-color: #2E2E2E;
    color: #FFFFFF;
    font-family: Arial;
}
QGroupBox {
    font-size: 14px;
    font-weight: bold;
    border: 1px solid #555;
    border-radius: 5px;
    margin-top: 1ex;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top center;
    padding: 0 3px;
}
QLineEdit {
    background-color: #3a3a3a;
    border: 1px solid #666;
    border-radius: 3px;
    padding: 3px 6px;
    color: white;
}
QPushButton {
    background-color: #555;
    border: 1px solid #777;
    padding: 4px 10px;
    border-radius: 3px;
}
QPushButton:hover   { background-color: #666; }
QPushButton:pressed { background-color: #777; }
"""

_STATUS_STYLE = {
    "OK":   "background-color:#1a3d1a; color:#66bb6a; font-size:18px; font-weight:bold; padding:8px; border-radius:4px;",
    "FAIL": "background-color:#3d0e0e; color:#ef5350; font-size:18px; font-weight:bold; padding:8px; border-radius:4px;",
}

S2_MAX = 10


class SraderDashboard(QMainWindow):
    def __init__(self, vm: MonitorViewModel):
        super().__init__()
        self._vm = vm
        self.setWindowTitle("Srader - 무대 조명 안전 모니터링 시스템")
        self.resize(700, 580)
        self._build_ui()
        self._bind()

    # ── UI 구성 ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(10, 10, 10, 10)

        # 1) 센서 상태바 (브로커 GroupBox 대체)
        bar = QWidget()
        bar.setStyleSheet("background-color:#2a2a2a; border-radius:4px;")
        bar.setFixedHeight(48)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(10, 4, 10, 4)
        bar_lay.setSpacing(4)

        self.dot_mqtt = BlinkDot("MQTT")
        self.dot_rx   = BlinkDot("RX")
        bar_lay.addWidget(self.dot_mqtt)
        bar_lay.addWidget(self.dot_rx)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("background-color:#555;")
        sep.setFixedWidth(1)
        bar_lay.addSpacing(6)
        bar_lay.addWidget(sep)
        bar_lay.addSpacing(6)

        # S1-L ― S2-1..N ― S1-R
        self.dot_s1l = BlinkDot("S1-L")
        bar_lay.addWidget(self.dot_s1l)

        self.dots_s2: list[BlinkDot] = []
        for i in range(S2_MAX):
            d = BlinkDot(f"S2-{i + 1}")
            d.hide()
            self.dots_s2.append(d)
            bar_lay.addWidget(d)

        self.dot_s1r = BlinkDot("S1-R")
        bar_lay.addWidget(self.dot_s1r)
        bar_lay.addStretch()
        root.addWidget(bar)

        # 2) 기울기
        tilt_box = QGroupBox("기울기 상태 (S1: TFmini Plus)")
        tilt_lay = QVBoxLayout(tilt_box)
        self.tilt_widget = TiltIndicatorWidget()
        s1_row = QHBoxLayout()
        self.s1l_lbl = QLabel("S1-L: --")
        self.s1r_lbl = QLabel("S1-R: --")
        s1_row.addWidget(self.s1l_lbl)
        s1_row.addStretch()
        s1_row.addWidget(self.s1r_lbl)
        tilt_lay.addWidget(self.tilt_widget)
        tilt_lay.addLayout(s1_row)
        root.addWidget(tilt_box)

        # 3) 장애물 감지
        obs_box = QGroupBox(f"하부 장애물 감지 (S2 × {S2_MAX})")  # 실제 표시는 _on_s2_count에서 갱신
        obs_lay = QVBoxLayout(obs_box)

        sensor_row = QHBoxLayout()
        self.obs_widgets: list[ObstacleColumnWidget] = []
        for i in range(S2_MAX):
            w = ObstacleColumnWidget(f"S2-{i+1}")
            w.hide()   # config 로드 전엔 숨김
            self.obs_widgets.append(w)
            sensor_row.addWidget(w)
        sensor_row.addWidget(ColorBarWidget())
        obs_lay.addLayout(sensor_row)

        btn_row = QHBoxLayout()
        bar_btn  = QPushButton("Bar View")
        line_btn = QPushButton("Line View")
        cell_btn = QPushButton("Cell View")
        iso_btn  = QPushButton("3D View")
        bar_btn.clicked.connect(lambda: self._set_mode(DisplayMode.BAR))
        line_btn.clicked.connect(lambda: self._set_mode(DisplayMode.LINE))
        cell_btn.clicked.connect(lambda: self._set_mode(DisplayMode.CELL))
        iso_btn.clicked.connect(lambda: self._set_mode(DisplayMode.ISO))
        btn_row.addStretch()
        btn_row.addWidget(bar_btn)
        btn_row.addWidget(line_btn)
        btn_row.addWidget(cell_btn)
        btn_row.addWidget(iso_btn)
        btn_row.addStretch()
        obs_lay.addLayout(btn_row)

        self.min_dist_lbl = QLabel("최소 감지 거리: --")
        self.min_dist_lbl.setAlignment(Qt.AlignCenter)
        obs_lay.addWidget(self.min_dist_lbl)
        root.addWidget(obs_box)

        # 4) 상태 표시줄
        self.status_lbl = QLabel("SYSTEM INITIALIZING...")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setStyleSheet(_STATUS_STYLE["OK"])
        root.addWidget(self.status_lbl)



    # ── ViewModel 바인딩 ──────────────────────────────────────────────────────
    def _bind(self):
        self._vm.tilt_updated.connect(self.tilt_widget.setAngle)
        self._vm.s1_labels_updated.connect(self._on_s1_labels)
        self._vm.s2_updated.connect(self._on_s2)
        self._vm.status_updated.connect(self._on_status)
        self._vm.mqtt_connected.connect(self._on_connected)
        self._vm.mqtt_disconnected.connect(self._on_disconnected)
        self._vm.config_loaded.connect(self._on_config_loaded)
        self._vm.rx_blinked.connect(self.dot_rx.blink)
        self._vm.s1_blinked.connect(self._on_s1_blink)
        self._vm.s2_blinked.connect(self._on_s2_blink)
        self._vm.s2_count_changed.connect(self._on_s2_count)
        self._vm.s1_mapped_changed.connect(self._on_s1_mapped)
    # ── 슬롯 ──────────────────────────────────────────────────────────────────
    @Slot(str, str)
    def _on_s1_labels(self, left: str, right: str):
        self.s1l_lbl.setText(left)
        self.s1r_lbl.setText(right)

    @Slot(int, list)
    def _on_s2(self, idx: int, d64: list):
        if idx < len(self.obs_widgets):
            self.obs_widgets[idx].update_data(d64)

    @Slot(object)
    def _on_status(self, info: StatusInfo):
        self.status_lbl.setText(info.message)
        self.status_lbl.setStyleSheet(_STATUS_STYLE.get(info.level, _STATUS_STYLE["OK"]))
        self.min_dist_lbl.setText(f"최소 감지 거리: {info.min_dist_mm} mm")

    @Slot(bool, str)
    def _on_config_loaded(self, ok: bool, msg: str):
        if ok:
            self.status_lbl.setText("SYSTEM OK")
            self.status_lbl.setStyleSheet(_STATUS_STYLE["OK"])
        else:
            self.status_lbl.setText("⏳ config 대기 중 — Setup PC에서 RDR/config 전송하세요")
            self.status_lbl.setStyleSheet(
                "background-color:#e65100; font-size:16px; "
                "font-weight:bold; padding:8px; border-radius:4px;"
            )

    @Slot()
    def _on_connected(self):
        self.dot_mqtt.set_connected(True)

    @Slot()
    def _on_disconnected(self):
        self.dot_mqtt.set_connected(False)

    @Slot(str)
    def _on_s1_blink(self, role: str):
        if role == "L":
            self.dot_s1l.blink()
        elif role == "R":
            self.dot_s1r.blink()

    @Slot(int)
    def _on_s2_blink(self, slot: int):
        if 0 <= slot < len(self.dots_s2):
            self.dots_s2[slot].blink()

    @Slot(int)
    def _on_s2_count(self, count: int):
        for i, d in enumerate(self.dots_s2):
            visible = i < count
            d.setVisible(visible)
            d.set_mapped(visible)
        # obs_widgets 동기화
        for i, w in enumerate(self.obs_widgets):
            w.setVisible(i < count)

    @Slot(bool, bool)
    def _on_s1_mapped(self, has_l: bool, has_r: bool):
        self.dot_s1l.set_mapped(has_l)
        self.dot_s1r.set_mapped(has_r)

    def _set_mode(self, mode: DisplayMode):
        for w in self.obs_widgets:
            w.setDisplayMode(mode)

    def closeEvent(self, event):
        self._vm.cleanup()
        event.accept()
