"""
src/setup/view/setup_window.py
Setup UI 메인 윈도우 — 3개 탭 구성.

탭 1: 브로커 연결 & 장치 감지
탭 2: 장치현장구성 (장치 위치 매핑 + Calibration + 즉시 전송)
탭 3: 설정 보기 (전송된 config JSON 표시)
"""

import math

from PySide6.QtWidgets import (
    QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout,
    QTabWidget, QGroupBox,
    QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QSpinBox, QDoubleSpinBox,
    QTextEdit,
    QScrollArea, QFrame,
    QDialog, QMenu,
)
from PySide6.QtGui import QFont, QPainter, QColor, QBrush, QPen, QPolygonF
from PySide6.QtCore import Qt, Slot, QRectF, QPointF

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

# S2 8×8 거리 시각화 팝업 ──────────────────────────────────────────────────────
class _S2GridWidget(QWidget):
    """8×8 (64존) 거리 히트맵 — 색상 + 수치 표시"""

    _THRESHOLDS = [
        (500,  QColor("#f44336")),   # 위험 (빨강)
        (1000, QColor("#ff9800")),   # 경고 (주황)
        (2000, QColor("#ffc107")),   # 주의 (노랑)
        (3500, QColor("#4caf50")),   # 정상 (초록)
    ]
    _COLOR_SAFE = QColor("#37474f")  # 안전 (짙은 회색)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[int] = [4000] * 64
        self.setMinimumSize(400, 340)

    def update_data(self, raw64: list[int]):
        self._data = (raw64 + [4000] * 64)[:64]
        self.update()

    @classmethod
    def _cell_color(cls, d: int) -> QColor:
        for threshold, color in cls._THRESHOLDS:
            if d < threshold:
                return color
        return cls._COLOR_SAFE

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(self.rect(), QColor("#2E2E2E"))

        margin  = 6
        cell_w  = (w - margin * 2) / 8
        cell_h  = (h - margin * 2) / 8
        pad     = 2
        font    = painter.font()
        font.setPixelSize(max(9, int(cell_h * 0.28)))
        font.setBold(True)
        painter.setFont(font)

        for row in range(8):
            for col in range(8):
                idx  = row * 8 + col
                dist = self._data[idx]
                color = self._cell_color(dist)

                x = margin + col * cell_w + pad
                y = margin + row * cell_h + pad
                cw = cell_w - pad * 2
                ch = cell_h - pad * 2

                painter.setBrush(QBrush(color))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(QRectF(x, y, cw, ch), 3, 3)

                # 텍스트 (거리 mm)
                painter.setPen(QPen(QColor("#000000") if color == QColor("#ffc107")
                                    else QColor("#ffffff")))
                label = f"{dist}" if dist < 9999 else "—"
                painter.drawText(QRectF(x, y, cw, ch), Qt.AlignCenter, label)

        # 행/열 번호 레이블
        painter.setPen(QPen(QColor("#888888")))
        small = painter.font()
        small.setPixelSize(9)
        painter.setFont(small)
        for i in range(8):
            cx = margin + i * cell_w + cell_w / 2
            cy = margin + i * cell_h + cell_h / 2
            painter.drawText(QRectF(margin - 18, cy - 7, 16, 14),
                             Qt.AlignCenter, str(i))
            painter.drawText(QRectF(cx - 7, margin - 16, 14, 14),
                             Qt.AlignCenter, str(i))


class S2GridDialog(QDialog):
    """S2 장치 8×8 거리 세부 정보 팝업 (비모달, 실시간 갱신)"""

    def __init__(self, mac: str, raw64: list[int], parent=None):
        super().__init__(parent)
        self._mac = mac
        self.setWindowTitle(f"S2 세부 거리  —  {mac}")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.resize(440, 420)
        self.setStyleSheet(STYLESHEET)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # 범례
        legend_row = QHBoxLayout()
        for label, color in [("위험 <500", "#f44336"), ("경고 <1000", "#ff9800"),
                              ("주의 <2000", "#ffc107"), ("정상 <3500", "#4caf50"),
                              ("안전", "#37474f")]:
            lbl = QLabel(f"  {label}  ")
            lbl.setStyleSheet(
                f"background:{color}; color:{'#000' if color=='#ffc107' else '#fff'};"
                "border-radius:3px; padding:2px 4px; font-size:10px;")
            legend_row.addWidget(lbl)
        legend_row.addStretch()
        lay.addLayout(legend_row)

        self._grid = _S2GridWidget()
        self._grid.update_data(raw64)
        lay.addWidget(self._grid, stretch=1)

        self._info_lbl = QLabel("단위: mm")
        self._info_lbl.setStyleSheet("color:#aaa; font-size:10px;")
        lay.addWidget(self._info_lbl)

    def refresh(self, raw64: list[int]):
        """새 패킷 수신 시 외부에서 호출"""
        if raw64:
            min_d = min(raw64)
            self._info_lbl.setText(
                f"단위: mm   |   최솟값: {min_d} mm   |   MAC: {self._mac}")
        self._grid.update_data(raw64)



# ── S2 공간구성 3D 시각화 ─────────────────────────────────────────────────────
_SPATIAL_CELL_CM  = 20    # 바닥 커버리지 그리드 셀 크기 (cm)
_SENSOR_COLORS    = ["#4fc3f7","#81c784","#ffb74d","#f06292",
                     "#ce93d8","#80cbc4","#ffcc02","#ff8a65"]


class _Spatial3DWidget(QWidget):
    """S2 센서 배치 3D 직교투영 뷰 — VL53L5CX FOV 커버리지 시각화.
    좌드래그: 회전 | 우드래그/중간: 패닝 | 휠: 줌 | 더블클릭: 초기화
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(520, 380)
        self._sensors: list[tuple[float, str]] = []  # (z_cm, label)
        self._height_cm = 400.0
        self._length_cm = 1000.0
        self._fov_deg   = 45.0
        self._az  = -25.0
        self._el  =  38.0
        # pan & zoom
        self._zoom   = 1.5
        self._pan_x  = 0.0
        self._pan_y  = 0.0
        # drag state
        self._drag_pos    = None
        self._drag_button = None
        self._az0    = self._az
        self._el0    = self._el
        self._pan_x0 = 0.0
        self._pan_y0 = 0.0

    def set_scene(self, sensors: list, height_cm: float,
                  length_cm: float, fov_deg: float):
        self._sensors   = sensors
        self._height_cm = max(10.0, height_cm)
        self._length_cm = max(10.0, length_cm)
        self._fov_deg   = max(5.0, min(85.0, fov_deg))
        self.update()

    # ── 마우스 회전 / 패닝 / 줌 ───────────────────────────────────────────
    def mousePressEvent(self, e):
        self._drag_pos    = e.position()
        self._drag_button = e.button()
        if e.button() == Qt.LeftButton:
            self._az0, self._el0 = self._az, self._el
        else:
            self._pan_x0, self._pan_y0 = self._pan_x, self._pan_y

    def mouseMoveEvent(self, e):
        if not self._drag_pos:
            return
        dx = e.position().x() - self._drag_pos.x()
        dy = e.position().y() - self._drag_pos.y()
        if self._drag_button == Qt.LeftButton and (e.buttons() & Qt.LeftButton):
            self._az = self._az0 - dx * 0.4
            self._el = max(5.0, min(80.0, self._el0 - dy * 0.4))
        elif self._drag_button in (Qt.RightButton, Qt.MiddleButton):
            self._pan_x = self._pan_x0 + dx
            self._pan_y = self._pan_y0 + dy
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == self._drag_button:
            self._drag_pos    = None
            self._drag_button = None

    def mouseDoubleClickEvent(self, e):
        """더블클릭: 시점·패닝·줌 초기화"""
        self._az, self._el = -25.0, 38.0
        self._zoom = 1.5
        self._pan_x = self._pan_y = 0.0
        self.update()

    def wheelEvent(self, e):
        factor = 1.12 if e.angleDelta().y() > 0 else 0.893
        self._zoom = max(0.15, min(12.0, self._zoom * factor))
        self.update()

    # ── 투영 ────────────────────────────────────────────────────────────────
    def _proj(self, x: float, y: float, z: float) -> QPointF:
        """3D → 2D (스탠드 중심 원점, pan/zoom 적용)"""
        az = math.radians(self._az)
        el = math.radians(self._el)
        z_c = z - self._length_cm / 2   # 스탠드 중심을 원점으로
        xr =  x * math.cos(az) + z_c * math.sin(az)
        zr = -x * math.sin(az) + z_c * math.cos(az)
        yr =  y * math.cos(el) - zr * math.sin(el)
        w, h = self.width(), self.height()
        scale = min(w, h) / (self._length_cm * 2.1) * self._zoom
        return QPointF(w * 0.5 + xr * scale + self._pan_x,
                       h * 0.55 - yr * scale + self._pan_y)

    # ── 커버리지 계산 ─────────────────────────────────────────────────────────
    def _calc_coverage(self) -> dict:
        """(ix, iz) → count  (바닥 그리드 셀별 커버 센서 수)"""
        if not self._sensors:
            return {}
        H  = self._height_cm
        hf = math.tan(math.radians(self._fov_deg / 2))
        xs = H * hf
        cs = _SPATIAL_CELL_CM
        cov: dict = {}
        for z_s, _ in self._sensors:
            ix0 = int(-xs / cs) - 1
            ix1 = int( xs / cs) + 2
            iz0 = int((z_s - xs) / cs) - 1
            iz1 = int((z_s + xs) / cs) + 2
            for ix in range(ix0, ix1):
                for iz in range(iz0, iz1):
                    cx = (ix + 0.5) * cs
                    cz = (iz + 0.5) * cs
                    ax = math.degrees(math.atan2(abs(cx), H))
                    az = math.degrees(math.atan2(abs(cz - z_s), H))
                    if ax < self._fov_deg / 2 and az < self._fov_deg / 2:
                        cov[(ix, iz)] = cov.get((ix, iz), 0) + 1
        return cov

    # ── 그리기 ────────────────────────────────────────────────────────────────
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        W, H_w = self.width(), self.height()
        painter.fillRect(self.rect(), QColor("#16213e"))

        H  = self._height_cm
        L  = self._length_cm
        hf = math.tan(math.radians(self._fov_deg / 2))
        xs = H * hf
        cs = _SPATIAL_CELL_CM
        pp = self._proj

        def poly(*pts):
            return QPolygonF(list(pts))

        # ── 바닥 베이스 ────────────────────────────────────────────────────
        pad = max(xs * 0.3, 50)
        fp = poly(pp(-xs-pad, 0, -L*0.06), pp(xs+pad, 0, -L*0.06),
                  pp(xs+pad, 0,  L*1.06),  pp(-xs-pad, 0,  L*1.06))
        painter.setBrush(QBrush(QColor("#1b2838")))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(fp)

        # ── 바닥 격자선 ────────────────────────────────────────────────────
        step = max(50, (int(max(L, xs * 2) / 8 / 50) + 1) * 50)
        painter.setPen(QPen(QColor(80, 100, 120, 50), 0.5))
        z = 0
        while z <= int(L) + step:
            painter.drawLine(pp(-xs*1.2, 0, z), pp(xs*1.2, 0, z))
            z += step
        x = int(-xs * 1.2 / step) * step
        while x <= int(xs * 1.2) + step:
            painter.drawLine(pp(x, 0, 0), pp(x, 0, L))
            x += step

        # ── 수직 지지대 & 스탠드 바 ───────────────────────────────────────
        painter.setPen(QPen(QColor("#546e7a"), 1, Qt.DashLine))
        painter.drawLine(pp(0, 0, 0), pp(0, H, 0))
        painter.drawLine(pp(0, 0, L), pp(0, H, L))
        painter.setPen(QPen(QColor("#90a4ae"), 2))
        painter.drawLine(pp(0, H, 0), pp(0, H, L))

        # ── 센서별 FOV 피라미드 ────────────────────────────────────────────
        for si, (z_s, label) in enumerate(self._sensors):
            color = QColor(_SENSOR_COLORS[si % len(_SENSOR_COLORS)])
            s_pt = pp(0, H, z_s)
            fl   = [pp(-xs, 1, z_s-xs), pp(xs, 1, z_s-xs),
                    pp( xs, 1, z_s+xs), pp(-xs, 1, z_s+xs)]

            # 피라미드 면 — 알파 채움 (뒷면 먼저 → 앞면 순서로 대략 정렬)
            # az < 0 이면 카메라가 +x 방향에서 보므로 face 순서 조정
            face_order = [2, 3, 0, 1] if self._az < 0 else [0, 3, 2, 1]
            for fi in face_order:
                # 면마다 깊이감: 뒷면 더 어둡게, 앞면 더 밝게
                alpha = 22 + fi * 4
                fc = QColor(color); fc.setAlpha(alpha)
                painter.setBrush(QBrush(fc))
                painter.setPen(Qt.NoPen)
                painter.drawPolygon(poly(s_pt, fl[fi], fl[(fi+1) % 4]))

            # 와이어프레임 (센서→바닥 모서리)
            wc = QColor(color); wc.setAlpha(65)
            painter.setPen(QPen(wc, 0.8, Qt.DotLine))
            for fp_pt in fl:
                painter.drawLine(s_pt, fp_pt)

            # 풋프린트 테두리
            oc = QColor(color); oc.setAlpha(200)
            painter.setPen(QPen(oc, 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(poly(*fl))

            # 센서 구슬
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(s_pt, 7, 7)

            # 라벨
            painter.setPen(QPen(color))
            f = painter.font(); f.setBold(True); f.setPixelSize(11)
            painter.setFont(f)
            painter.drawText(
                QRectF(s_pt.x()+9, s_pt.y()-7, 70, 14),
                Qt.AlignLeft | Qt.AlignVCenter, label)

        # ── 높이 치수선 ───────────────────────────────────────────────────
        if self._sensors:
            z_s0 = self._sensors[0][0]
            xd   = xs * 1.55
            painter.setPen(QPen(QColor("#78909c"), 1))
            painter.drawLine(pp(xd, 0, z_s0), pp(xd, H, z_s0))
            painter.drawLine(pp(xd-4, 0, z_s0), pp(xd+4, 0, z_s0))
            painter.drawLine(pp(xd-4, H, z_s0), pp(xd+4, H, z_s0))
            mid = pp(xd+6, H/2, z_s0)
            painter.setPen(QPen(QColor("#aaa")))
            f = painter.font(); f.setBold(False); f.setPixelSize(10)
            painter.setFont(f)
            painter.drawText(QRectF(mid.x(), mid.y()-8, 90, 16),
                           Qt.AlignLeft, f"H={H/100:.2f}m")

        # ── 사각지대 통계 ──────────────────────────────────────────────────
        painter.setPen(QPen(QColor("#aaa")))
        f = painter.font(); f.setBold(False); f.setPixelSize(10)
        painter.setFont(f)
        if not self._sensors:
            painter.setPen(QPen(QColor("#f44336")))
            f.setPixelSize(14); f.setBold(True); painter.setFont(f)
            painter.drawText(W//2-80, H_w//2, "등록된 S2 센서 없음")

        # ── 조작 힌트 ─────────────────────────────────────────────────────
        painter.setPen(QPen(QColor("#444")))
        f = painter.font(); f.setPixelSize(9); painter.setFont(f)
        painter.drawText(W-210, H_w-6,
            "좌드래그:회전 | 우드래그:이동 | 휠:줌 | 더블클릭:초기화")


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
        self._s2_dialogs: dict[str, S2GridDialog] = {}   # mac → 열린 팝업
        self._s2_snaps:   dict[str, object]       = {}   # mac → DeviceSnapshot
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
        self._tabs.addTab(self._tab_spatial(),      "④ 공간구성 3D")

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
        self.s2_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.s2_table.customContextMenuRequested.connect(self._on_s2_context_menu)
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
        self.gap_spin.setValue(10.0)
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
        self.threshold_spin.setValue(100)
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

    # ── 탭 4: 공간구성 3D ─────────────────────────────────────────────────────
    def _tab_spatial(self) -> QWidget:
        w   = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(8)

        # 3D 뷰
        self._spatial_3d = _Spatial3DWidget()
        lay.addWidget(self._spatial_3d, stretch=3)

        # 컨트롤 패널
        ctrl = QWidget()
        ctrl.setFixedWidth(190)
        ctrl_lay = QVBoxLayout(ctrl)
        ctrl_lay.setSpacing(8)
        ctrl_lay.setContentsMargins(0, 0, 0, 0)

        h_box = QGroupBox("설치 높이")
        h_form = QFormLayout(h_box)
        self._sp_height = QDoubleSpinBox()
        self._sp_height.setRange(0.5, 10.0)
        self._sp_height.setSingleStep(0.1)
        self._sp_height.setDecimals(2)
        self._sp_height.setSuffix(" m")
        self._sp_height.setValue(4.0)
        h_form.addRow("높이 :", self._sp_height)
        ctrl_lay.addWidget(h_box)

        l_box = QGroupBox("스탠드 전체 길이")
        l_form = QFormLayout(l_box)
        self._sp_length = QDoubleSpinBox()
        self._sp_length.setRange(0.5, 50.0)
        self._sp_length.setSingleStep(0.5)
        self._sp_length.setDecimals(1)
        self._sp_length.setSuffix(" m")
        self._sp_length.setValue(10.0)
        l_form.addRow("길이 :", self._sp_length)
        ctrl_lay.addWidget(l_box)

        d_box = QGroupBox("슬롯 수 (등분)")
        d_form = QFormLayout(d_box)
        self._sp_divisions = QSpinBox()
        self._sp_divisions.setRange(2, 20)
        self._sp_divisions.setValue(10)
        self._sp_divisions.setToolTip("스탠드를 몇 등분하여 pos1~posN 위치를 배분할지 결정합니다")
        d_form.addRow("슬롯 수 :", self._sp_divisions)
        ctrl_lay.addWidget(d_box)

        fov_lbl = QLabel("VL53L5CX FOV: 45° × 45°\n(하드웨어 고정값)")
        fov_lbl.setStyleSheet("color:#78909c; font-size:10px; padding:4px 0px;")
        ctrl_lay.addWidget(fov_lbl)

        refresh_btn = QPushButton("▶  적용 & 새로고침")
        refresh_btn.setObjectName("pushBtn")
        refresh_btn.clicked.connect(self._update_spatial)
        ctrl_lay.addWidget(refresh_btn)

        ctrl_lay.addStretch()

        hint = QLabel("드래그: 시점 회전\n초록: 단일 커버\n파랑: 이중 커버\n주황: 3+ 커버")
        hint.setStyleSheet("color:#666; font-size:10px;")
        ctrl_lay.addWidget(hint)

        lay.addWidget(ctrl)
        return w

    def _update_spatial(self):
        """config에서 등록된 S2 센서 위치를 읽어 3D 뷰 갱신."""
        cfg    = self._vm.get_config()
        n_div  = self._sp_divisions.value()
        l_cm   = self._sp_length.value() * 100
        h_cm   = self._sp_height.value() * 100
        fov    = 45.0           # VL53L5CX 축별 FOV 고정값

        parsed = []
        for dev in cfg.devices:
            if dev.type != "S2":
                continue
            label = (dev.s2 or [""])[0]
            if label in ("", "unset"):
                continue
            try:
                pos = int(label.replace("pos", ""))
                parsed.append((pos, label))
            except ValueError:
                pass

        if parsed:
            max_pos = max(p for p, _ in parsed)
            if max_pos != n_div:
                self._sp_divisions.setValue(max_pos)
                n_div = max_pos

        sensors = []
        for pos, label in sorted(parsed):
            z_cm = (pos - 1) / max(1, n_div - 1) * l_cm
            sensors.append((z_cm, label))

        self._spatial_3d.set_scene(sensors, h_cm, l_cm, fov)

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

        # ── 열린 S2 팝업 실시간 갱신 ─────────────────────────────────────────
        for snap in s2_snaps:
            dlg = self._s2_dialogs.get(snap.mac)
            if dlg and dlg.isVisible() and snap.s2_raw64:
                dlg.refresh(snap.s2_raw64)

    def _refresh_s1_table(self, snaps: list):
        cfg = self._vm.get_config()
        if self.s1_table.rowCount() != len(snaps):
            self.s1_table.setRowCount(len(snaps))
            for row, snap in enumerate(snaps):
                dev     = cfg.get_device(snap.mac)
                s1_role = dev.s1 if dev else ""
                if s1_role == "unset":
                    s1_role = "(unset)"

                self.s1_table.setItem(row, 0, QTableWidgetItem(snap.mac))
                cb = self._make_combo(S1_POSITION_OPTIONS, s1_role)
                self.s1_table.setCellWidget(row, 1, cb)
                dist_text = f"  {snap.s1_values[0]} cm" if snap.s1_values else ""
                self.s1_table.setItem(row, 2, QTableWidgetItem(snap.last_seen + dist_text))
        else:
            for row, snap in enumerate(snaps):
                dist_text = f"  {snap.s1_values[0]} cm" if snap.s1_values else ""
                self.s1_table.setItem(row, 2, QTableWidgetItem(snap.last_seen + dist_text))

    def _refresh_s2_table(self, snaps: list):
        self._s2_snaps = {s.mac: s for s in snaps}   # context menu 에서 접근용
        cfg = self._vm.get_config()
        if self.s2_table.rowCount() != len(snaps):
            self.s2_table.setRowCount(len(snaps))
            for row, snap in enumerate(snaps):
                dev    = cfg.get_device(snap.mac)
                s2_lbl = dev.s2[0] if dev and dev.s2 else ""
                if s2_lbl == "unset":
                    s2_lbl = "(unset)"

                self.s2_table.setItem(row, 0, QTableWidgetItem(snap.mac))
                cb = self._make_combo(S2_POSITION_OPTIONS, s2_lbl)
                self.s2_table.setCellWidget(row, 1, cb)
                dist_text = f"  {snap.s2_values[0]} mm" if snap.s2_values else ""
                self.s2_table.setItem(row, 2, QTableWidgetItem(snap.last_seen + dist_text))
        else:
            for row, snap in enumerate(snaps):
                dist_text = f"  {snap.s2_values[0]} mm" if snap.s2_values else ""
                self.s2_table.setItem(row, 2, QTableWidgetItem(snap.last_seen + dist_text))

    @staticmethod
    def _make_combo(options: list, current: str) -> QComboBox:
        cb = QComboBox()
        cb.addItems(options)
        if current in options:
            cb.setCurrentText(current)
        return cb

    @Slot(object)
    def _on_s2_context_menu(self, pos):
        """S2 테이블 우클릭 → 8×8 세부 보기 팝업"""
        row = self.s2_table.rowAt(pos.y())
        if row < 0:
            return
        item = self.s2_table.item(row, 0)
        if not item:
            return
        mac  = item.text()
        snap = self._s2_snaps.get(mac)

        menu   = QMenu(self)
        action = menu.addAction(f"🔍  8×8 세부 거리 보기  [{mac}]")
        if menu.exec(self.s2_table.viewport().mapToGlobal(pos)) == action:
            raw64 = (snap.s2_raw64 if snap and snap.s2_raw64
                     else [4000] * 64)
            dlg = self._s2_dialogs.get(mac)
            if dlg and dlg.isVisible():
                dlg.raise_()
                dlg.activateWindow()
            else:
                dlg = S2GridDialog(mac, raw64, parent=self)
                dlg.finished.connect(
                    lambda _, m=mac: self._s2_dialogs.pop(m, None))
                self._s2_dialogs[mac] = dlg
                dlg.show()

    @Slot()
    def _on_apply_mapping(self):
        """S1/S2 테이블의 현재 값을 ViewModel 에 저장 (내부 헬퍼)"""
        for row in range(self.s1_table.rowCount()):
            mac    = self.s1_table.item(row, 0).text()
            cb     = self.s1_table.cellWidget(row, 1)
            s1_val = cb.currentText() if cb else ""
            self._vm.update_device_mapping(mac, "S1",
                                            s1_role="unset" if s1_val == "(unset)" else s1_val)

        for row in range(self.s2_table.rowCount()):
            mac  = self.s2_table.item(row, 0).text()
            cb   = self.s2_table.cellWidget(row, 1)
            lbl  = cb.currentText() if cb else ""
            self._vm.update_device_mapping(mac, "S2",
                                            s2_labels=["unset" if lbl == "(unset)" else lbl],
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

        # 4. 공간구성 3D 뷰 갱신
        self._update_spatial()

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
