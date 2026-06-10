"""
view/dashboard.py
Srader Operation UI 메인 윈도우.
ViewModel 시그널에 바인딩하여 화면 갱신. 직접 데이터 계산 없음.
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel,
    QPushButton,
    QTextEdit,
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, Slot

from .widgets import (
    Constants, DisplayMode,
    TiltIndicatorWidget,
    ObstacleColumnWidget,
    ColorBarWidget,
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
    "OK":       "background-color:#2e7d32; font-size:18px; font-weight:bold; padding:8px; border-radius:4px;",
    "TILT":     "background-color:#e65100; font-size:18px; font-weight:bold; padding:8px; border-radius:4px;",
    "OBSTACLE": "background-color:#b71c1c; font-size:18px; font-weight:bold; padding:8px; border-radius:4px;",
}
_CONN_STYLE = {
    True:  "color:#4caf50; font-weight:bold;",
    False: "color:#aaa;    font-weight:bold;",
}

S2_COUNT = 5


class SraderDashboard(QMainWindow):
    def __init__(self, vm: MonitorViewModel):
        super().__init__()
        self._vm = vm
        self.setWindowTitle("Srader - 무대 조명 안전 모니터링 시스템")
        self.resize(700, 660)
        self._build_ui()
        self._bind()

    # ── UI 구성 ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(10, 10, 10, 10)

        # 1) 브로커 상태 표시줄 (localhost 고정, UI 입력 불필요)
        conn_box = QGroupBox("브로커 연결")
        conn_lay = QHBoxLayout(conn_box)
        conn_lay.addWidget(QLabel("Broker :"))
        broker_info = QLabel("localhost : 1883  (Mosquitto)")
        broker_info.setStyleSheet("color:#aaa;")
        conn_lay.addWidget(broker_info)
        conn_lay.addSpacing(24)
        self.conn_status_lbl = QLabel("● 연결 중...")
        self.conn_status_lbl.setStyleSheet(_CONN_STYLE[False])
        conn_lay.addWidget(self.conn_status_lbl)
        conn_lay.addStretch()
        root.addWidget(conn_box)

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
        obs_box = QGroupBox(f"하부 장애물 감지 (S2 × {S2_COUNT})")
        obs_lay = QVBoxLayout(obs_box)

        sensor_row = QHBoxLayout()
        self.obs_widgets: list[ObstacleColumnWidget] = []
        for i in range(S2_COUNT):
            w = ObstacleColumnWidget(f"S2-{i+1}")
            self.obs_widgets.append(w)
            sensor_row.addWidget(w)
        sensor_row.addWidget(ColorBarWidget())
        obs_lay.addLayout(sensor_row)

        btn_row = QHBoxLayout()
        bar_btn  = QPushButton("Bar View")
        line_btn = QPushButton("Line View")
        bar_btn.clicked.connect(lambda: self._set_mode(DisplayMode.BAR))
        line_btn.clicked.connect(lambda: self._set_mode(DisplayMode.LINE))
        btn_row.addStretch()
        btn_row.addWidget(bar_btn)
        btn_row.addWidget(line_btn)
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

        # 5) 로그
        log_box = QGroupBox("수신 로그")
        log_lay = QVBoxLayout(log_box)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFont("Consolas", 8))
        self.log_edit.setFixedHeight(100)
        log_lay.addWidget(self.log_edit)
        clr_btn = QPushButton("로그 지우기")
        clr_btn.setFixedWidth(90)
        clr_btn.clicked.connect(self.log_edit.clear)
        log_lay.addWidget(clr_btn, alignment=Qt.AlignRight)
        root.addWidget(log_box)

    # ── ViewModel 바인딩 ──────────────────────────────────────────────────────
    def _bind(self):
        self._vm.tilt_updated.connect(self.tilt_widget.setAngle)
        self._vm.s1_labels_updated.connect(self._on_s1_labels)
        self._vm.s2_updated.connect(self._on_s2)
        self._vm.status_updated.connect(self._on_status)
        self._vm.log_signal.connect(self._append_log)
        self._vm.mqtt_connected.connect(self._on_connected)
        self._vm.mqtt_disconnected.connect(self._on_disconnected)

    # ── 슬롯 ──────────────────────────────────────────────────────────────────
    @Slot(str, str)
    def _on_s1_labels(self, left: str, right: str):
        self.s1l_lbl.setText(left)
        self.s1r_lbl.setText(right)

    @Slot(int, list)
    def _on_s2(self, idx: int, cols: list):
        if idx < len(self.obs_widgets):
            self.obs_widgets[idx].update_data(cols)

    @Slot(object)
    def _on_status(self, info: StatusInfo):
        self.status_lbl.setText(info.message)
        self.status_lbl.setStyleSheet(_STATUS_STYLE.get(info.level, _STATUS_STYLE["OK"]))
        self.min_dist_lbl.setText(f"최소 감지 거리: {info.min_dist_mm} mm")

    @Slot()
    def _on_connected(self):
        self.conn_status_lbl.setText("● 수신 중")
        self.conn_status_lbl.setStyleSheet(_CONN_STYLE[True])

    @Slot()
    def _on_disconnected(self):
        self.conn_status_lbl.setText("● 미접속 (재시도 중...)")
        self.conn_status_lbl.setStyleSheet(_CONN_STYLE[False])

    def _append_log(self, msg: str):
        self.log_edit.append(msg)
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _set_mode(self, mode: DisplayMode):
        for w in self.obs_widgets:
            w.setDisplayMode(mode)

    def closeEvent(self, event):
        self._vm.cleanup()
        event.accept()
