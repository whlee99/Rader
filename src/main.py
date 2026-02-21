# main.py
import sys
import random
import math
from enum import Enum, auto
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGridLayout, QGroupBox, QSizePolicy
)
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QLinearGradient, QGradient, QPainterPath
from PySide6.QtCore import Qt, QRectF, QTimer, Slot, QPointF

# --- 위젯 스타일시트 ---
STYLESHEET = """
QWidget {
    background-color: #2E2E2E;
    color: #FFFFFF;
    font-family: Arial;
}
QGroupBox {
    font-size: 16px;
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
QLabel#statusLabel {
    font-size: 18px;
    font-weight: bold;
    padding: 10px;
    border-radius: 5px;
}
QLabel#valueLabel {
    font-size: 18px;
    font-weight: bold;
}
QPushButton {
    background-color: #555;
    border: 1px solid #777;
    padding: 5px;
    border-radius: 3px;
}
QPushButton:hover {
    background-color: #666;
}
QPushButton:pressed {
    background-color: #777;
}
"""

# --- 상수 정의 ---
class Constants:
    # 기울기 임계값 (도)
    TILT_ANGLE_NORMAL = 5
    TILT_ANGLE_WARNING = 15

    # 장애물 거리 임계값 (mm)
    OBSTACLE_DIST_CRITICAL = 300
    OBSTACLE_DIST_WARNING = 600
    OBSTACLE_DIST_CAUTION = 1000
    OBSTACLE_DIST_NORMAL = 2000

    # 색상 정의
    COLOR_CRITICAL = QColor("#F44336")  # Red
    COLOR_WARNING = QColor("#FF9800")   # Orange
    COLOR_CAUTION = QColor("#FFC107")   # Amber
    COLOR_NORMAL = QColor("#4CAF50")    # Green
    COLOR_SAFE = QColor("#1E88E5")      # Blue
    COLOR_BACKGROUND = QColor("#444")
    COLOR_GRID_LINE = QColor("#2E2E2E")

class DisplayMode(Enum):
    """장애물 표시 모드 열거형"""
    BAR = auto()
    LINE = auto()

# -----------------------------------------------------------------------------
# 1. 기울기 표시 위젯 (디지털 수평계)
# -----------------------------------------------------------------------------
class TiltIndicatorWidget(QWidget):
    """두 TFmini 센서의 데이터를 바탕으로 기울기를 시각화하는 위젯"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0.0
        self.setMinimumSize(300, 60)

    @Slot(float)
    def setAngle(self, angle: float):
        """기울기 각도를 업데이트하고 위젯을 다시 그립니다."""
        if self._angle != angle:
            self._angle = angle
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, Constants.COLOR_BACKGROUND)

        # 눈금 그리기
        painter.setPen(QPen(Qt.white, 1, Qt.DotLine))
        center_x = rect.center().x()
        tick_positions = [-0.5, -0.25, 0, 0.25, 0.5] # -50% ~ +50% 위치
        for pos in tick_positions:
            x = center_x + pos * (rect.width() * 0.8)
            painter.drawLine(int(x), rect.height() * 0.2, int(x), rect.height() * 0.8)

        # 기울기 상태에 따른 버블 색상 결정
        if abs(self._angle) < Constants.TILT_ANGLE_NORMAL:
            bubble_color = Constants.COLOR_NORMAL
        elif abs(self._angle) < Constants.TILT_ANGLE_WARNING:
            bubble_color = Constants.COLOR_CAUTION
        else:
            bubble_color = Constants.COLOR_CRITICAL

        painter.setBrush(QBrush(bubble_color))
        painter.setPen(Qt.NoPen)

        # 각도에 따라 버블 위치 계산
        # 최대 각도를 45도로 가정
        bubble_radius = 18
        center_y = rect.center().y()
        max_offset = (rect.width() / 2) - bubble_radius - 5
        offset = (self._angle / 45.0) * max_offset
        bubble_x = rect.center().x() + offset
        
        bubble_rect = QRectF(bubble_x - bubble_radius, center_y - bubble_radius, bubble_radius * 2, bubble_radius * 2)
        painter.drawEllipse(bubble_rect)

        painter.setPen(QPen(Qt.white))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(bubble_rect, Qt.AlignCenter, f"{self._angle:.1f}°")

# -----------------------------------------------------------------------------
# 2. 장애물 감지 위젯 (히트맵)
# -----------------------------------------------------------------------------
class HeatmapWidget(QWidget):
    """VL53L5CX의 8x8 데이터를 히트맵으로 시각화하는 위젯"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.distances = [4000] * 64
        self.setFixedSize(280, 280)

    @Slot(list)
    def update_data(self, new_distances: list):
        if len(new_distances) == 64:
            self.distances = new_distances
            self.update()

    def get_color_for_distance(self, distance_mm: int):
        """거리에 따라 색상을 반환 (가까울수록 빨간색)"""
        if distance_mm < Constants.OBSTACLE_DIST_CRITICAL: return Constants.COLOR_CRITICAL
        if distance_mm < Constants.OBSTACLE_DIST_WARNING: return Constants.COLOR_WARNING
        if distance_mm < Constants.OBSTACLE_DIST_CAUTION: return Constants.COLOR_CAUTION
        if distance_mm < Constants.OBSTACLE_DIST_NORMAL: return Constants.COLOR_NORMAL
        return Constants.COLOR_SAFE

    def paintEvent(self, event):
        painter = QPainter(self)
        cell_width = self.width() / 8.0
        cell_height = self.height() / 8.0

        for i in range(64):
            row, col = divmod(i, 8)
            distance = self.distances[i]
            color = self.get_color_for_distance(distance)
            
            painter.setBrush(color)
            painter.setPen(QPen(Constants.COLOR_GRID_LINE, 1)) # Grid line
            
            rect = QRectF(col * cell_width, row * cell_height, cell_width, cell_height)
            painter.drawRect(rect)

# -----------------------------------------------------------------------------
# 2.1. 새로운 장애물 감지 위젯 (정면 뷰 - 수직 막대)
# -----------------------------------------------------------------------------
class ObstacleColumnWidget(QWidget):
    """하나의 S2 센서에서 받은 8개 거리 데이터를 수직 막대로 시각화"""
    def __init__(self, sensor_name: str, parent=None):
        super().__init__(parent)
        self.sensor_name = sensor_name
        self.distances = [4000] * 8  # 8개 픽셀 데이터
        self.display_mode = DisplayMode.BAR # 기본 표시 모드
        self.setMinimumSize(60, 200)

    @Slot(list)
    def update_data(self, new_distances: list):
        if len(new_distances) == 8:
            self.distances = new_distances
            self.update()

    @Slot(DisplayMode)
    def setDisplayMode(self, mode: DisplayMode):
        if self.display_mode != mode:
            self.display_mode = mode
            self.update()

    def get_color_for_distance(self, distance_mm: int):
        if distance_mm < Constants.OBSTACLE_DIST_CRITICAL: return Constants.COLOR_CRITICAL
        if distance_mm < Constants.OBSTACLE_DIST_WARNING: return Constants.COLOR_WARNING
        if distance_mm < Constants.OBSTACLE_DIST_CAUTION: return Constants.COLOR_CAUTION
        if distance_mm < Constants.OBSTACLE_DIST_NORMAL: return Constants.COLOR_NORMAL
        return Constants.COLOR_SAFE

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 센서 이름 표시
        painter.setPen(Qt.white)
        painter.drawText(self.rect(), Qt.AlignHCenter | Qt.AlignTop, self.sensor_name)

        # 8개의 막대 그리기
        bar_area_height = self.height() - 20  # 상단 텍스트 영역 제외
        bar_width = self.width() / 8.0
        max_dist = 4000.0  # 최대 거리 4m

        if self.display_mode == DisplayMode.BAR:
            for i, dist in enumerate(self.distances):
                color = self.get_color_for_distance(dist)
                painter.setBrush(color)
                painter.setPen(Qt.NoPen)

                # 거리에 따라 막대 높이 계산 (거리가 짧을수록 막대가 길어짐)
                bar_height_ratio = 1.0 - (min(dist, max_dist) / max_dist)
                bar_height = bar_area_height * bar_height_ratio
                
                rect = QRectF(i * bar_width, self.height() - bar_height, bar_width - 2, bar_height)
                painter.drawRect(rect)
        
        elif self.display_mode == DisplayMode.LINE:
            points = []
            for i, dist in enumerate(self.distances):
                bar_height_ratio = 1.0 - (min(dist, max_dist) / max_dist)
                bar_height = bar_area_height * bar_height_ratio
                x = (i + 0.5) * bar_width
                y = self.height() - bar_height
                points.append(QPointF(x, y))

            path = QPainterPath()
            path.moveTo(points[0])
            for i in range(len(points) - 1):
                path.lineTo(points[i+1])
            
            painter.setPen(QPen(Constants.COLOR_CAUTION, 2))
            painter.drawPath(path)

# -----------------------------------------------------------------------------
# 2.1. 히트맵 범례 위젯
# -----------------------------------------------------------------------------
class ColorBarWidget(QWidget):
    """히트맵의 색상 범례를 표시하는 위젯"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 280)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        gradient = QLinearGradient(0, rect.height(), 0, 0)
        
        # get_color_for_distance 로직과 일치하는 그라데이션 설정
        gradient.setColorAt(0, Constants.COLOR_SAFE) # 2000mm+
        gradient.setColorAt(1.0 - (Constants.OBSTACLE_DIST_NORMAL / 4000.0), Constants.COLOR_SAFE)
        gradient.setColorAt(1.0 - (Constants.OBSTACLE_DIST_CAUTION / 4000.0), Constants.COLOR_NORMAL)
        gradient.setColorAt(1.0 - (Constants.OBSTACLE_DIST_WARNING / 4000.0), Constants.COLOR_CAUTION)
        gradient.setColorAt(1.0 - (Constants.OBSTACLE_DIST_CRITICAL / 4000.0), Constants.COLOR_WARNING)
        gradient.setColorAt(1.0, Constants.COLOR_CRITICAL) # 0mm

        painter.fillRect(QRectF(0, 0, 20, rect.height()), gradient)

        # 텍스트 레이블 추가
        painter.setPen(Qt.white)
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        
        labels = {"0m": 1.0, "0.3m": 1.0 - (300/4000.0), "1m": 1.0 - (1000/4000.0), "2m": 1.0 - (2000/4000.0), "4m+": 0.0}
        for text, pos in labels.items():
            painter.drawText(22, int(rect.height() * pos) + 5, text)

# -----------------------------------------------------------------------------
# 3. 메인 대시보드 윈도우
# -----------------------------------------------------------------------------
class SraderDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Srader - 무대 조명 안전 모니터링 시스템")
        self.setGeometry(100, 100, 600, 550) # 수직으로 긴 형태로 변경

        # --- 중앙 위젯 및 레이아웃 설정 ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 1. 기울기 정보 그룹
        tilt_group = QGroupBox("기울기 상태 (S1: TFmini Plus)")
        tilt_layout = QVBoxLayout()
        self.tilt_indicator = TiltIndicatorWidget()
        self.s1_l_label = QLabel("S1-L: 0 mm")
        self.s1_r_label = QLabel("S1-R: 0 mm")
        tilt_layout.addWidget(self.tilt_indicator)
        tilt_layout.addWidget(self.s1_l_label)
        tilt_layout.addWidget(self.s1_r_label)
        tilt_group.setLayout(tilt_layout)

        # 2. 장애물 감지 그룹
        obstacle_group = QGroupBox("하부 장애물 감지 (S2 x 5)")
        obstacle_layout = QVBoxLayout()
        
        # 5개의 센서 뷰를 담을 수평 레이아웃
        sensor_view_layout = QHBoxLayout()
        self.obstacle_widgets = []
        for i in range(5):
            widget = ObstacleColumnWidget(f"S2-{i+1}")
            self.obstacle_widgets.append(widget)
            sensor_view_layout.addWidget(widget)

        # 뷰 모드 전환 버튼
        button_layout = QHBoxLayout()
        self.bar_view_button = QPushButton("Bar View")
        self.line_view_button = QPushButton("Line View")
        button_layout.addStretch()
        button_layout.addWidget(self.bar_view_button)
        button_layout.addWidget(self.line_view_button)
        button_layout.addStretch()

        self.min_dist_label = QLabel("최소 감지 거리: N/A")
        self.min_dist_label.setObjectName("valueLabel")

        obstacle_layout.addLayout(sensor_view_layout)
        obstacle_layout.addLayout(button_layout)
        obstacle_layout.addWidget(self.min_dist_label, alignment=Qt.AlignCenter)
        obstacle_group.setLayout(obstacle_layout)

        # --- 메인 레이아웃에 위젯 추가 (수직 구성) ---
        main_layout.addWidget(tilt_group)
        main_layout.addWidget(obstacle_group)

        self.status_label = QLabel("SYSTEM INITIALIZING...")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignCenter)
        
        main_layout.addWidget(self.status_label)

        # --- 상태별 스타일시트 미리 정의 ---
        self.status_styles = {
            "OK": f"background-color: {Constants.COLOR_NORMAL.name()};",
            "TILT": f"background-color: {Constants.COLOR_WARNING.name()};",
            "OBSTACLE": f"background-color: {Constants.COLOR_CRITICAL.name()};"
        }

        # --- 시그널/슬롯 연결 ---
        self.bar_view_button.clicked.connect(self.set_bar_view)
        self.line_view_button.clicked.connect(self.set_line_view)

        # --- 데이터 시뮬레이션을 위한 상태 변수 ---
        self._last_sim_angle = 0.0
        # 5개의 센서, 각 8개 픽셀의 초기 거리 값
        self._last_sim_distances = [[4000] * 8 for _ in range(5)]

        # --- 데이터 시뮬레이션 타이머 ---
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.simulate_data)
        self.timer.start(200) # 0.2초마다 데이터 업데이트

    @Slot()
    def set_bar_view(self):
        """장애물 뷰를 'Bar' 모드로 설정합니다."""
        for widget in self.obstacle_widgets:
            widget.setDisplayMode(DisplayMode.BAR)

    @Slot()
    def set_line_view(self):
        """장애물 뷰를 'Line' 모드로 설정합니다."""
        for widget in self.obstacle_widgets:
            widget.setDisplayMode(DisplayMode.LINE)

    def simulate_person_obstacle(self, sensor_index: int, distance_to_person: int, shoulder_width_pixels: float):
        """
        특정 센서 아래에 가우시안 분포를 이용한 사람 형태의 장애물을 시뮬레이션합니다.
        :param sensor_index: 사람이 위치할 센서의 인덱스 (0-4)
        :param distance_to_person: 사람까지의 최소 거리 (mm)
        :param shoulder_width_pixels: 사람 어깨 너비에 해당하는 픽셀 수 (표준편차 역할)
        """
        sensor_data = [4000] * 8
        center_pixel = 3.5  # 8개 픽셀의 중앙

        for j in range(8):
            # 가우시안 함수: exp(-((x-mu)^2) / (2*sigma^2))
            exponent = -((j - center_pixel) ** 2) / (2 * shoulder_width_pixels ** 2)
            dist = distance_to_person + (4000 - distance_to_person) * (1 - math.exp(exponent))
            self._last_sim_distances[sensor_index][j] = int(dist)

    @Slot()
    def simulate_data(self):
        """센서 데이터를 시뮬레이션하고 GUI를 업데이트합니다."""
        # 1. 기울기 데이터 시뮬레이션 (점진적 변화)
        # 이전 각도에서 -2 ~ +2도 사이로 변화
        angle_change = (random.random() - 0.5) * 4
        self._last_sim_angle += angle_change
        # 각도가 너무 커지지 않도록 범위 제한
        if not -30 < self._last_sim_angle < 30:
            self._last_sim_angle -= angle_change * 2 # 방향 반전

        sim_angle = self._last_sim_angle

        base_dist = 2000 # 기준 높이 2m
        sensor_gap = 500 # 두 센서 간 거리 50cm 가정
        dist_diff = math.tan(math.radians(sim_angle)) * sensor_gap
        s1_l_dist = int(base_dist - dist_diff / 2)
        s1_r_dist = int(base_dist + dist_diff / 2)

        self.tilt_indicator.setAngle(self._last_sim_angle)
        self.s1_l_label.setText(f"S1-L: {s1_l_dist} mm")
        self.s1_r_label.setText(f"S1-R: {s1_r_dist} mm")

        # 2. 장애물 데이터 시뮬레이션 (점진적 변화)
        all_distances = []
        for i in range(5):
            sensor_data = self._last_sim_distances[i]
            for j in range(8):
                # 이전 값에서 -50 ~ +50mm 사이로 변화
                dist_change = (random.random() - 0.5) * 100
                sensor_data[j] += dist_change
                # 최소/최대 거리 제한
                sensor_data[j] = max(50, min(4000, sensor_data[j]))

            # 5% 확률로 갑작스러운 장애물 등장/사라짐
            if random.random() < 0.02: # 확률을 조금 낮춤
                pixel_idx = random.randint(0, 7)
                # 현재 값이 멀면 가깝게, 가까우면 멀게 변경
                if sensor_data[pixel_idx] > 1000:
                    sensor_data[pixel_idx] = random.randint(50, 299)
                else:
                    sensor_data[pixel_idx] = random.randint(1500, 4000)

        # 10% 확률로 '사람' 장애물 시뮬레이션 실행
        if random.random() < 0.1:
            target_sensor = random.randint(0, 4) # 5개 센서 중 하나를 랜덤 선택
            person_dist = random.randint(400, 1200) # 사람까지의 거리
            shoulder_width = random.uniform(1.5, 2.5) # 사람 어깨 너비
            self.simulate_person_obstacle(target_sensor, person_dist, shoulder_width)

        for i in range(5):
            self.obstacle_widgets[i].update_data(self._last_sim_distances[i])
            all_distances.extend(self._last_sim_distances[i])

        min_dist = min(all_distances)
        self.min_dist_label.setText(f"최소 감지 거리: {min_dist} mm")

        # 3. 전체 시스템 상태 업데이트
        if min_dist < Constants.OBSTACLE_DIST_CRITICAL:
            self.status_label.setText("!!! OBSTACLE DETECTED !!!")
            self.status_label.setStyleSheet(self.status_styles["OBSTACLE"])
        elif abs(sim_angle) > Constants.TILT_ANGLE_WARNING:
            self.status_label.setText("TILT WARNING")
            self.status_label.setStyleSheet(self.status_styles["TILT"])
        else:
            self.status_label.setText("SYSTEM OK")
            self.status_label.setStyleSheet(self.status_styles["OK"])


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    window = SraderDashboard()
    window.show()
    sys.exit(app.exec())
