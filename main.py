from __future__ import annotations

import configparser
import math
import os
import pyuac
import random
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPoint, Property, QPropertyAnimation, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

ROOT = Path(__file__).resolve().parent
APPDATA = Path.home() / "AppData" / "Roaming"
CONFIG_DIR = APPDATA / "limbo-windows-python"
CONFIG_PATH = CONFIG_DIR / "limbosave.cfg"
ASSETS = ROOT / "assets"


@dataclass
class NextMoveAndDelay:
    next_pos: QPoint
    delay_sec: float
    speed_sec: float
    next_order: int


@dataclass
class GameSettings:
    sixteen_by_nine_reso: bool = False
    fullscreen_ending: bool = True
    debugdontmove: bool = False
    debug_key_mover_window: bool = False
    instant_finish: bool = False
    transparent_background: bool = True
    winning_wait_time: float = 3.0
    bluescreen_wait_time: float = 7.0
    no_ending_screen: bool = True
    music_volume: float = 20.0
    hide_border_on_maximize: bool = True
    physics_process: bool = True
    load_save: bool = True

    saved_values = [
        "sixteen_by_nine_reso",
        "fullscreen_ending",
        "debugdontmove",
        "debug_key_mover_window",
        "instant_finish",
        "transparent_background",
        "winning_wait_time",
        "bluescreen_wait_time",
        "no_ending_screen",
        "music_volume",
        "hide_border_on_maximize",
        "physics_process",
        "load_save",
    ]

    @classmethod
    def load(cls) -> "GameSettings":
        settings = cls()
        cfg = configparser.ConfigParser()
        if not CONFIG_PATH.exists():
            settings.save()
            return settings

        cfg.read(CONFIG_PATH)
        if not cfg.has_section("settings"):
            settings.save()
            return settings

        section = cfg["settings"]
        if not section.getboolean("load_save", fallback=True):
            return settings

        for key in cls.saved_values:
            current = getattr(settings, key)
            if isinstance(current, bool):
                setattr(settings, key, section.getboolean(key, fallback=current))
            elif isinstance(current, float):
                setattr(settings, key, section.getfloat(key, fallback=current))
        return settings

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg = configparser.ConfigParser()
        cfg["settings"] = {k: str(getattr(self, k)) for k in self.saved_values}
        with CONFIG_PATH.open("w", encoding="utf-8") as f:
            cfg.write(f)


class AudioPlayer:
    def __init__(self) -> None:
        self.music_path = ASSETS / "musics" / "isolation_keypart_cut.mp3"
        self.death_path = ASSETS / "sfx" / "geometry-dash-death-sound-effect.mp3"
        self.win_path = ASSETS / "sfx" / "level-complete-geometry-dash.mp3"

        self.music_out = QAudioOutput()
        self.music = QMediaPlayer()
        self.music.setAudioOutput(self.music_out)

        self.sfx_out = QAudioOutput()
        self.sfx = QMediaPlayer()
        self.sfx.setAudioOutput(self.sfx_out)

    def set_volume(self, volume_0_to_20: float) -> None:
        level = max(0.0, min(1.0, volume_0_to_20 / 20.0))
        self.music_out.setVolume(level)
        self.sfx_out.setVolume(level)

    def play_music(self, start_seconds: float = 0.0) -> None:
        if not self.music_path.exists():
            return
        if self.is_playing_limbo_music() and self.music.source().toLocalFile() == str(self.music_path):
            return
        self.music.setSource(QUrl.fromLocalFile(str(self.music_path)))
        self.music.play()
        if start_seconds > 0:
            self.music.setPosition(int(start_seconds * 1000))

    def is_playing_limbo_music(self) -> bool:
        return self.music.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def get_playback_position(self) -> float:
        return self.music.position() / 1000.0

    def stop(self) -> None:
        self.music.stop()

    def play_sfx(self, winning: bool = False) -> None:
        path = self.win_path if winning else self.death_path
        if not path.exists():
            return
        self.sfx.stop()
        self.sfx.setSource(QUrl.fromLocalFile(str(path)))
        self.sfx.play()


class KeySprite(QWidget):
    key_colors = [
        QColor("#fa0000"),
        QColor("#ff35ee"),
        QColor("#b200ff"),
        QColor("#1516fb"),
        QColor("#1afeff"),
        QColor("#27ff1a"),
        QColor("#fffe39"),
        QColor("#ff8c00"),
    ]

    def __init__(self, key_image: QPixmap | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rotation_deg = 0.0
        self._scale_factor = 1.0
        self._blend_factor = 0.0
        self._anims: list[QPropertyAnimation] = []

        self.base_key = key_image
        self.base_img = key_image.toImage().convertToFormat(QImage.Format_ARGB32) if key_image else None
        self.recolored_pixmap = key_image

        self.u_color_key1 = QColor("#ff0006")
        self.u_color_key2 = QColor("#eee42b")
        self.replacement1 = QColor("#ff0006")
        self.replacement2 = QColor("#eee42b")
        self.current_pixmap = key_image

    def _get_rotation_deg(self) -> float:
        return self._rotation_deg

    def _set_rotation_deg(self, value: float) -> None:
        self._rotation_deg = value
        self.update()

    def _get_scale_factor(self) -> float:
        return self._scale_factor

    def _set_scale_factor(self, value: float) -> None:
        self._scale_factor = value
        self.update()

    def _get_blend_factor(self) -> float:
        return self._blend_factor

    def _set_blend_factor(self, value: float) -> None:
        self._blend_factor = max(0.0, min(1.0, value))
        self.update()

    rotationDeg = Property(float, _get_rotation_deg, _set_rotation_deg)
    scaleFactor = Property(float, _get_scale_factor, _set_scale_factor)
    blendFactor = Property(float, _get_blend_factor, _set_blend_factor)

    @staticmethod
    def _desaturize(color: QColor) -> QColor:
        h, s, v, a = color.getHsvF()
        s = max(0.0, s - 0.3)
        out = QColor()
        out.setHsvF(h, s, v, a)
        return out

    @staticmethod
    def _mix(c1: QColor, c2: QColor, t: float) -> QColor:
        inv = 1.0 - t
        return QColor(
            int(c1.red() * inv + c2.red() * t),
            int(c1.green() * inv + c2.green() * t),
            int(c1.blue() * inv + c2.blue() * t),
            c1.alpha(),
        )

    @staticmethod
    def _close(c: QColor, target: QColor, tolerance: float = 0.855) -> bool:
        dr = (c.red() - target.red()) / 255.0
        dg = (c.green() - target.green()) / 255.0
        db = (c.blue() - target.blue()) / 255.0
        dist = math.sqrt(dr * dr + dg * dg + db * db)
        return dist <= tolerance

    def _rebuild_key_pixmap(self) -> None:
        if self.base_img is None:
            return
        img = self.base_img.copy()
        replaced = 0
        for y in range(img.height()):
            for x in range(img.width()):
                src = QColor.fromRgba(img.pixel(x, y))
                if src.alpha() == 0:
                    continue
                if self._close(src, self.u_color_key1):
                    target = self._mix(src, self.replacement1, 1.0)
                    target.setAlpha(src.alpha())
                    img.setPixelColor(x, y, target)
                    replaced += 1
                elif self._close(src, self.u_color_key2):
                    target = self._mix(src, self.replacement2, 1.0)
                    target.setAlpha(src.alpha())
                    img.setPixelColor(x, y, target)
                    replaced += 1

        # Some image variants may not match the original shader key colors exactly.
        # Fallback to alpha-mask tint so color shifting remains visible.
        if replaced < max(32, (img.width() * img.height()) // 200):
            img = self.base_img.copy()
            for y in range(img.height()):
                for x in range(img.width()):
                    src = QColor.fromRgba(img.pixel(x, y))
                    if src.alpha() == 0:
                        continue
                    lum = (0.2126 * src.red() + 0.7152 * src.green() + 0.0722 * src.blue()) / 255.0
                    light_mix = min(1.0, 0.6 + lum * 0.5)
                    tint = self._mix(self.replacement2, self.replacement1, light_mix)
                    target = self._mix(src, tint, 1.0)
                    target.setAlpha(src.alpha())
                    img.setPixelColor(x, y, target)
        self.recolored_pixmap = QPixmap.fromImage(img)

    def _track(self, anim: QPropertyAnimation) -> None:
        self._anims.append(anim)

        def _cleanup() -> None:
            if anim in self._anims:
                self._anims.remove(anim)

        anim.finished.connect(_cleanup)
        anim.start()

    def tween_rotate(self, degree: float = 180.0, duration_sec: float = 0.4) -> None:
        anim = QPropertyAnimation(self, b"rotationDeg", self)
        anim.setStartValue(self._rotation_deg)
        anim.setEndValue(self._rotation_deg + degree)
        anim.setDuration(max(1, int(duration_sec * 1000)))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        self._track(anim)

    def queue_rotate(self, delay_sec: float, degree: float, duration_sec: float) -> None:
        QTimer.singleShot(int(delay_sec * 1000), lambda: self.tween_rotate(degree, duration_sec))

    def click_animation(self) -> None:
        down = QPropertyAnimation(self, b"scaleFactor", self)
        down.setStartValue(self._scale_factor)
        down.setEndValue(0.8)
        down.setDuration(150)
        down.setEasingCurve(QEasingCurve.InOutQuint)

        def _up() -> None:
            up = QPropertyAnimation(self, b"scaleFactor", self)
            up.setStartValue(self._scale_factor)
            up.setEndValue(1.0)
            up.setDuration(150)
            up.setEasingCurve(QEasingCurve.InOutQuint)
            self._track(up)

        down.finished.connect(_up)
        self._track(down)

    def flash_green(self) -> None:
        self.replacement1 = QColor("#00ea00")
        self.replacement2 = self._desaturize(QColor("#00ea00"))
        self._rebuild_key_pixmap()

        up = QPropertyAnimation(self, b"blendFactor", self)
        up.setStartValue(0.0)
        up.setEndValue(1.0)
        up.setDuration(500)

        def _down() -> None:
            down = QPropertyAnimation(self, b"blendFactor", self)
            down.setStartValue(1.0)
            down.setEndValue(0.0)
            down.setDuration(500)
            QTimer.singleShot(100, lambda: self._track(down))

        up.finished.connect(_down)
        self._track(up)

    def shift_color(self, index: int) -> None:
        idx = max(0, min(index, len(self.key_colors) - 1))
        self.replacement1 = self.key_colors[idx]
        self.replacement2 = self._desaturize(self.key_colors[idx])
        self._rebuild_key_pixmap()
        anim = QPropertyAnimation(self, b"blendFactor", self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(1000)
        self._track(anim)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        p.translate(cx, cy)
        p.rotate(self._rotation_deg)
        p.scale(self._scale_factor, self._scale_factor)

        side = min(self.width(), self.height()) * 0.8
        rect_x = int(-side / 2.0)
        rect_y = int(-side / 2.0)
        rect_w = int(side)
        rect_h = int(side)

        if self.current_pixmap and not self.current_pixmap.isNull():
            p.drawPixmap(rect_x, rect_y, rect_w, rect_h, self.current_pixmap)
            if self.recolored_pixmap and not self.recolored_pixmap.isNull() and self._blend_factor > 0.0:
                p.setOpacity(self._blend_factor)
                p.drawPixmap(rect_x, rect_y, rect_w, rect_h, self.recolored_pixmap)
                p.setOpacity(1.0)
        else:
            p.setPen(QPen(Qt.black, 3))
            p.setBrush(QColor("#ff8c00"))
            p.drawEllipse(rect_x, rect_y, rect_w, rect_h)


class KeyWindow(QWidget):
    TITLE_BAR_HEIGHT = 31
    CORNER_RADIUS = 8
    CAPTION_BUTTON_WIDTH = 34

    def __init__(self, main: "MainController", size: int, order: int, key_image: QPixmap | None) -> None:
        super().__init__(None)
        self.main = main
        self.window_order = order
        self.final_color_index = max(0, min(order - 1, len(KeySprite.key_colors) - 1))

        self.queued_moves: list[NextMoveAndDelay] = []
        self.next_move: NextMoveAndDelay | None = None
        self.xth_move = 0
        self.done_first_move = False
        self.waiting_for_delay = False
        self.is_delaying = False
        self.pending_delay_sec = 0.0
        self.finish_started = False

        self.clickable = False
        self.correct_key = False
        self.reduced_move = False

        self.orbiting = False
        self.orbit_d = 0.0
        self.orbitoval_a = 300.0
        self.orbitoval_b = 200.0
        self.orbit_speed = 0.25

        self.halfsize = QPoint(round(size / 2), round((size + self.TITLE_BAR_HEIGHT) / 2))
        self.orbit_center = QPoint(0, 0)

        self.delay_timer = QTimer(self)
        self.delay_timer.setSingleShot(True)
        self.delay_timer.timeout.connect(self._on_move_delay_timeout)

        self._right_click_times: list[int] = []
        self._drag_offset: QPoint | None = None
        self.title_text = "limbo-windows-python"
        self._hover_button: str | None = None

        # Keep title icon crisp when downscaled.
        self.title_icon = None
        if key_image and not key_image.isNull():
            self.title_icon = key_image.scaled(18, 18, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # Single mode: frameless layered window for real per-pixel transparency.
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFixedSize(size, size + self.TITLE_BAR_HEIGHT)
        self.setMouseTracking(True)
        self.setMask(self.rect())

        self.key = KeySprite(key_image, self)
        self.key.setGeometry(0, self.TITLE_BAR_HEIGHT, size, size)
        self.key.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        if main.small_height_resolution:
            self.orbitoval_a = 200.0
            self.orbitoval_b = 150.0

    def _caption_button_rects(self) -> tuple[QRect, QRect, QRect]:
        top = 1
        h = self.TITLE_BAR_HEIGHT
        w = self.CAPTION_BUTTON_WIDTH
        left = self.width() - (w * 3) - 1
        min_rect = QRect(left, top, w, h)
        max_rect = QRect(left + w, top, w, h)
        close_rect = QRect(left + w * 2, top, w, h)
        return min_rect, max_rect, close_rect

    def _button_from_pos(self, pos: QPoint) -> str | None:
        min_rect, max_rect, close_rect = self._caption_button_rects()
        if close_rect.contains(pos):
            return "close"
        if max_rect.contains(pos):
            return "max"
        if min_rect.contains(pos):
            return "min"
        return None

    def get_order(self) -> int:
        return self.window_order

    def get_last_order(self) -> int:
        if self.queued_moves:
            return self.queued_moves[-1].next_order
        return self.window_order

    def set_order(self, idx: int) -> None:
        self.window_order = idx

    def resizeEvent(self, event) -> None:
        self.setMask(self.rect())
        super().resizeEvent(event)

    def set_as_correct_key(self) -> None:
        self.correct_key = True
        self.key.flash_green()

    def pulse_preview(self) -> None:
        self.key.flash_green()

    def clearqueue(self) -> None:
        self.queued_moves.clear()
        self.next_move = None
        self.xth_move = 0
        self.finish_started = False

    def queuemove(self, move_pos: QPoint, delay_sec: float, speed_sec: float, next_order: int) -> None:
        self.queued_moves.append(NextMoveAndDelay(move_pos, delay_sec, speed_sec, next_order))

    def startmoving(self) -> None:
        self._move()

    def _move(self) -> None:
        if self.next_move is None and self.queued_moves:
            self.next_move = self.queued_moves.pop(0)
            self.xth_move += 1

            if self.xth_move in (10, 19):
                self.key.tween_rotate(180.0, 0.4)

            if self.xth_move == self.main.runtime_move_count:
                self.finishing_move()
                return
        else:
            if self.reduced_move:
                self.main.prepare_finished()
                return
            if self.next_move is None and not self.queued_moves and not self.finish_started:
                self.finishing_move()
                return

        if self.next_move is not None:
            anim = QPropertyAnimation(self, b"pos", self)
            anim.setStartValue(self.pos())
            anim.setEndValue(self.next_move.next_pos)
            anim.setDuration(max(1, int(self.next_move.speed_sec * 1000)))
            anim.setEasingCurve(QEasingCurve.OutQuart)
            anim.finished.connect(self._on_move_ends)
            self._anim = anim
            anim.start()

    def _on_move_ends(self) -> None:
        if self.next_move is None:
            return
        completed = self.next_move
        self.window_order = completed.next_order
        self.next_move = None

        self.main.done_moving_onewindow()
        self.done_first_move = True
        self.waiting_for_delay = True
        self.pending_delay_sec = completed.delay_sec

    def finishing_move(self) -> None:
        if self.finish_started:
            return
        self.finish_started = True
        self.main.notify_window_finishing()
        self.queue_orbit_movement()
        self.key.queue_rotate(0.1 * self.window_order, 360.0, 0.6)
        self.key.shift_color(self.final_color_index)

    def queue_orbit_movement(self) -> None:
        px = self.x() - self.orbit_center.x()
        py = self.y() - self.orbit_center.y()
        distance_to_path = math.hypot(px, py) - (self.orbitoval_a + self.orbitoval_b) / 2.0

        if abs(distance_to_path) > 0.001:
            entry_angle = math.radians(float(self.window_order * 45))
            target = QPoint(
                round(math.cos(entry_angle) * self.orbitoval_a + self.orbit_center.x() - self.halfsize.x()),
                round(math.sin(entry_angle) * self.orbitoval_b + self.orbit_center.y() - self.halfsize.y()),
            )
            anim = QPropertyAnimation(self, b"pos", self)
            anim.setStartValue(self.pos())
            anim.setEndValue(target)
            anim.setDuration(1000)
            anim.setEasingCurve(QEasingCurve.OutQuart)
            anim.finished.connect(lambda: self._on_arriving_in_orbit(entry_angle))
            self._orbit_anim = anim
            anim.start()
        else:
            self.orbiting = True

    def _on_arriving_in_orbit(self, angle: float) -> None:
        self.orbit_d = angle
        self.orbiting = True
        QTimer.singleShot(500, self._set_clickable)

    def _set_clickable(self) -> None:
        self.clickable = True

    def physics_tick(self, delta: float) -> None:
        if self.waiting_for_delay:
            if self.main.is_allwindow_moved() and self.done_first_move and (not self.is_delaying):
                self.waiting_for_delay = False
                self.is_delaying = True
                self.delay_timer.start(max(1, int(self.pending_delay_sec * 1000)))

        if self.orbiting:
            self.orbit_d += delta * self.orbit_speed
            x = round(math.cos(self.orbit_d) * self.orbitoval_a)
            y = round(math.sin(self.orbit_d) * self.orbitoval_b)
            self.move(self.orbit_center.x() + x - self.halfsize.x(), self.orbit_center.y() + y - self.halfsize.y())

    def _on_move_delay_timeout(self) -> None:
        self.is_delaying = False
        self._move()

    def checkreducemove(self) -> None:
        if len(self.queued_moves) >= 2:
            self.queued_moves = self.queued_moves[:1]
            self.reduced_move = True

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            if pos.y() < self.TITLE_BAR_HEIGHT and self._button_from_pos(pos) is None:
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

        if event.button() == Qt.RightButton:
            self._right_click_times.append(event.timestamp())
            self._right_click_times = self._right_click_times[-2:]
            if len(self._right_click_times) == 2:
                if self._right_click_times[1] - self._right_click_times[0] <= 350:
                    self.main.open_setting_window()

        if event.button() == Qt.LeftButton and self.clickable:
            self.key.click_animation()
            self.main.set_correctkey_from_window(self)
            QTimer.singleShot(200, self.main.finish_game_without_ending)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        hover = self._button_from_pos(event.position().toPoint())
        if hover != self._hover_button:
            self._hover_button = hover
            self.update()

        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = None

    def leaveEvent(self, _event) -> None:
        if self._hover_button is not None:
            self._hover_button = None
            self.update()

    def closeEvent(self, event) -> None:
        if self.main.allow_close:
            super().closeEvent(event)
        else:
            event.ignore()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Clear entire client area to transparent so alpha=0 is truly see-through.
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        outer_rect = self.rect().adjusted(0, 0, -1, -1)

        # Windows 11 dark-style shell: rounded corners and subtle border.
        p.setBrush(QColor(0, 0, 0, 0))
        p.setPen(QPen(QColor("#3a3a3a"), 1))
        p.drawRoundedRect(outer_rect, self.CORNER_RADIUS, self.CORNER_RADIUS)

        title_rect = QRect(1, 1, self.width() - 2, self.TITLE_BAR_HEIGHT)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#202020"))
        p.drawRoundedRect(title_rect, self.CORNER_RADIUS - 1, self.CORNER_RADIUS - 1)

        # Flatten bottom of title bar to match contiguous client area.
        p.fillRect(title_rect.adjusted(0, self.TITLE_BAR_HEIGHT // 2, 0, 0), QColor("#202020"))

        min_rect, max_rect, close_rect = self._caption_button_rects()

        # Windows 11 dark hover colors.
        hover_gray = QColor("#2b2b2b")
        hover_close = QColor("#c42b1c")
        default_btn = QColor("#202020")

        p.setPen(Qt.NoPen)
        p.setBrush(hover_gray if self._hover_button == "min" else default_btn)
        p.drawRect(min_rect)
        p.setBrush(hover_gray if self._hover_button == "max" else default_btn)
        p.drawRect(max_rect)
        p.setBrush(hover_close if self._hover_button == "close" else default_btn)
        p.drawRect(close_rect)

        # Caption icon + text.
        icon_side = 16
        icon_x = title_rect.x() + 8
        icon_y = title_rect.y() + (title_rect.height() - icon_side) // 2
        if self.title_icon and not self.title_icon.isNull():
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(icon_x, icon_y, icon_side, icon_side, self.title_icon)

        p.setFont(QFont("Segoe UI", 9, QFont.Medium))
        p.setPen(QColor("#f2f2f2"))
        text_left = icon_x + icon_side + 8
        text_right = min_rect.left() - 8
        text_width = max(10, text_right - text_left)
        fm = QFontMetrics(p.font())
        title = fm.elidedText(self.title_text, Qt.ElideRight, text_width)
        p.drawText(QRect(text_left, title_rect.y(), text_width, title_rect.height()), Qt.AlignVCenter | Qt.AlignLeft, title)

        glyph_color = QColor("#f5f5f5") if self._hover_button == "close" else QColor("#d0d0d0")
        p.setPen(QPen(glyph_color, 1))
        cy = title_rect.center().y()

        # Minimize glyph.
        p.drawLine(min_rect.center().x() - 6, cy + 4, min_rect.center().x() + 6, cy + 4)

        # Maximize glyph.
        p.drawRect(max_rect.center().x() - 5, cy - 5, 10, 9)

        # Close glyph.
        p.drawLine(close_rect.center().x() - 4, cy - 4, close_rect.center().x() + 4, cy + 4)
        p.drawLine(close_rect.center().x() + 4, cy - 4, close_rect.center().x() - 4, cy + 4)

        # Client area with user-controlled alpha.
        client_rect = self.rect().adjusted(1, self.TITLE_BAR_HEIGHT - 1, -2, -2)
        # Keep alpha=1 minimum for hit-test reliability while remaining visually transparent.
        fill = QColor(22, 22, 26, max(1, self.main.background_alpha))
        p.setPen(QPen(QColor("#2f2f2f"), 1))
        p.setBrush(fill)
        p.drawRect(client_rect)

        if self.main.runtime_show_correct_key_window and self.main.is_window_currently_correct(self):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 235, 60, 128))
            p.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), self.CORNER_RADIUS, self.CORNER_RADIUS)


class FocusOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self.text = "FOCUS"

        font_path = ROOT / "NeubauPro-Bold.ttf"
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            family = families[0] if families else "Segoe UI"
            self.font = QFont(family, 58)
        else:
            self.font = QFont("Segoe UI", 58, QFont.Bold)

        self._font_family = self.font.family()
        self._font_weight = self.font.weight()
        self._base_point_size = max(1, self.font.pointSize())
        self._scale = 1.0

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._pad_x = 12
        self._pad_y = 10
        self._text_x = self._pad_x
        self._text_y = self._pad_y
        self._text_width = 0
        self._text_height = 0
        self._ascent = 0
        self._rebuild_text_metrics()

    def _rebuild_text_metrics(self) -> None:
        point_size = max(1, int(round(self._base_point_size * self._scale)))
        self.font = QFont(self._font_family, point_size, self._font_weight)
        metrics = QFontMetrics(self.font)
        text_rect = metrics.boundingRect(self.text)
        self._text_width = text_rect.width()
        self._text_height = metrics.height()
        self._ascent = metrics.ascent()
        self._text_x = self._pad_x
        self._text_y = self._pad_y + self._ascent
        self.setFixedSize(self._text_width + self._pad_x * 2, self._text_height + self._pad_y * 2)

    def set_scale(self, scale: float) -> None:
        clamped = max(0.6, min(2.5, float(scale)))
        if abs(clamped - self._scale) < 0.001:
            return
        self._scale = clamped
        self._rebuild_text_metrics()
        self.update()

    def place_above_spawn(self, key_area: QRect, spawn_y: int) -> None:
        x = key_area.x() + (key_area.width() - self.width()) // 2
        y = spawn_y - self.height() - 14
        min_y = key_area.y() + 12
        self.move(x, max(min_y, y))

    def place_above_spawn_columns(self, spawn_x: int, window_size: int, margin: int, top_bound_y: int, spawn_y: int) -> None:
        # Center against the two initial spawn columns, not the full key area.
        columns_mid_x = spawn_x + window_size + (margin / 2.0)
        x = int(round(columns_mid_x - self.width() / 2.0))
        y = spawn_y - self.height() - 14
        self.move(x, max(top_bound_y + 12, y))

    def place_above_circle(self, orbit_center: QPoint, orbitoval_b: float, window_half_height: int, top_bound_y: int) -> None:
        circle_top = int(round(orbit_center.y() - orbitoval_b - window_half_height))
        x = orbit_center.x() - self.width() // 2
        y = circle_top - self.height() - 12
        self.move(x, max(top_bound_y + 12, y))

    def circle_center_position(self, orbit_center: QPoint) -> QPoint:
        return QPoint(orbit_center.x() - self.width() // 2, orbit_center.y() - self.height() // 2)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        path = QPainterPath()
        path.addText(float(self._text_x), float(self._text_y), self.font, self.text)

        gradient = QLinearGradient(0, self._text_y - self._ascent, 0, self._text_y + (self._text_height - self._ascent))
        gradient.setColorAt(0.0, QColor("#000000"))
        gradient.setColorAt(0.25, QColor("#4e096f"))
        gradient.setColorAt(0.5, QColor("#aa1cb4"))
        gradient.setColorAt(0.75, QColor("#d337b8"))
        gradient.setColorAt(1.0, QColor("#000000"))

        p.setPen(QPen(QColor("#000000"), 1.0))
        p.setBrush(gradient)
        p.drawPath(path)


class SettingsWindow(QDialog):
    def __init__(self, settings: GameSettings, on_save) -> None:
        super().__init__(None)
        self.settings = settings
        self.on_save = on_save
        self.setWindowTitle("limbo-windows-python Settings")
        self.setFixedSize(400, 600)

        layout = QVBoxLayout(self)
        title = QLabel("limbo-windows-python Settings")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        notice = QLabel("Note: In order to load saved config next run, load_save needs to be ON.")
        notice.setWordWrap(True)
        notice.setAlignment(Qt.AlignCenter)
        layout.addWidget(notice)

        form = QFormLayout()
        self.fields = {}
        for name in GameSettings.saved_values:
            value = getattr(settings, name)
            if isinstance(value, bool):
                cb = QCheckBox()
                cb.setChecked(value)
                self.fields[name] = cb
                form.addRow(name, cb)
            elif isinstance(value, float):
                sb = QDoubleSpinBox()
                sb.setDecimals(2)
                sb.setSingleStep(0.1)
                sb.setRange(0.0, 999.0)
                sb.setValue(value)
                self.fields[name] = sb
                form.addRow(name, sb)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Save and Quit")
        discard_btn = QPushButton("Discard Settings and Quit")
        save_btn.clicked.connect(self._save)
        discard_btn.clicked.connect(QApplication.instance().quit)
        buttons.addWidget(save_btn)
        buttons.addWidget(discard_btn)
        layout.addLayout(buttons)

    def _save(self) -> None:
        for name, widget in self.fields.items():
            if isinstance(widget, QCheckBox):
                setattr(self.settings, name, bool(widget.isChecked()))
            else:
                setattr(self.settings, name, float(widget.value()))
        self.settings.save()
        self.on_save()


class DebugControlWindow(QWidget):
    class KeyChoiceTile(QWidget):
        def __init__(self, key_order: int, key_pixmap: QPixmap | None, on_click) -> None:
            super().__init__()
            self.key_order = key_order
            self.key_pixmap = key_pixmap
            self.on_click = on_click
            self.selected = False
            self.setFixedSize(54, 54)

        def set_selected(self, value: bool) -> None:
            self.selected = bool(value)
            self.update()

        def mousePressEvent(self, event: QMouseEvent) -> None:
            if event.button() == Qt.LeftButton:
                self.on_click(self.key_order)

        def paintEvent(self, _event) -> None:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor("#4e4e4e"), 1))
            bg = QColor("#0ca645") if self.selected else QColor("#1f1f1f")
            p.setBrush(bg)
            p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)

            if self.key_pixmap and not self.key_pixmap.isNull():
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                p.drawPixmap(9, 9, 36, 36, self.key_pixmap)

    def __init__(self, controller: "MainController") -> None:
        super().__init__(None)
        self.controller = controller
        self.setWindowTitle("Limbo Python Debug")
        self.setFixedSize(380, 560)

        self._crash_hold_threshold = 3.0
        self._crash_hold_started_at = 0.0
        self._crash_hold_active = False
        self._crash_hold_activated_this_press = False
        self._crash_hold_timer = QTimer(self)
        self._crash_hold_timer.setInterval(40)
        self._crash_hold_timer.timeout.connect(self._update_crash_hold)

        layout = QVBoxLayout(self)

        title = QLabel("Debug Control")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.alpha_label = QLabel()
        self.alpha_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.alpha_label)

        hint = QLabel("Windows-like custom title bar is used for reliable see-through transparency.")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.transparency_slider = QSlider(Qt.Horizontal)
        self.transparency_slider.setRange(0, 255)
        self.transparency_slider.setValue(controller.background_alpha)
        self.transparency_slider.valueChanged.connect(self._on_alpha_changed)
        layout.addWidget(self.transparency_slider)

        self.set_pattern_box = QCheckBox("Use original set pattern (debug)")
        self.set_pattern_box.setChecked(controller.debug_use_set_pattern)
        self.set_pattern_box.toggled.connect(controller.set_debug_use_set_pattern)
        layout.addWidget(self.set_pattern_box)

        self.show_correct_box = QCheckBox("Show correct key window (green overlay)")
        self.show_correct_box.setChecked(controller.debug_show_correct_key_window)
        self.show_correct_box.toggled.connect(controller.set_debug_show_correct_key_window)
        layout.addWidget(self.show_correct_box)

        self.hide_on_start_box = QCheckBox("Hide debug menu when game starts")
        self.hide_on_start_box.setChecked(controller.debug_hide_menu_on_start)
        self.hide_on_start_box.toggled.connect(controller.set_debug_hide_menu_on_start)
        layout.addWidget(self.hide_on_start_box)

        self.crash_toggle_button = QPushButton()
        self.crash_toggle_button.pressed.connect(self._on_crash_button_pressed)
        self.crash_toggle_button.released.connect(self._on_crash_button_released)
        layout.addWidget(self.crash_toggle_button)

        self.crash_status = QLabel()
        self.crash_status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.crash_status)

        move_count_row = QHBoxLayout()
        move_count_label = QLabel("Move count")
        self.move_count_spin = QSpinBox()
        self.move_count_spin.setRange(1, 200)
        self.move_count_spin.setValue(controller.debug_move_count)
        self.move_count_spin.valueChanged.connect(controller.set_debug_move_count)
        move_count_row.addWidget(move_count_label)
        move_count_row.addWidget(self.move_count_spin)
        layout.addLayout(move_count_row)

        pick_label = QLabel("Forced correct key (click tile).\nClick selected tile again for random.")
        pick_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(pick_label)

        self.key_tiles: dict[int, DebugControlWindow.KeyChoiceTile] = {}
        tile_grid = QGridLayout()
        tile_grid.setHorizontalSpacing(8)
        tile_grid.setVerticalSpacing(8)

        for i in range(8):
            key_order = i + 1
            tile = self.KeyChoiceTile(
                key_order,
                controller.build_debug_key_icon(i),
                self._on_key_tile_clicked,
            )
            self.key_tiles[key_order] = tile
            tile_grid.addWidget(tile, i // 4, i % 4)

        layout.addLayout(tile_grid)

        self.selection_status = QLabel()
        self.selection_status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.selection_status)

        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self._on_start)
        layout.addWidget(self.start_button)

        self.status = QLabel("Waiting to start...")
        self.status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status)

        self._refresh_alpha_label(controller.background_alpha)
        self._refresh_key_selection_ui()
        self._refresh_crash_controls()

    def _refresh_alpha_label(self, alpha: int) -> None:
        self.alpha_label.setText(f"Key window background alpha: {alpha}")

    def _on_alpha_changed(self, value: int) -> None:
        self._refresh_alpha_label(value)
        self.controller.set_window_background_alpha(value)

    def _on_key_tile_clicked(self, key_order: int) -> None:
        current = self.controller.forced_correct_key_order
        if current == key_order:
            self.controller.set_forced_correct_key(None)
        else:
            self.controller.set_forced_correct_key(key_order)
        self._refresh_key_selection_ui()

    def _refresh_key_selection_ui(self) -> None:
        selected = self.controller.forced_correct_key_order
        for order, tile in self.key_tiles.items():
            tile.set_selected(order == selected)
        if selected is None:
            self.selection_status.setText("Correct key: Random")
        else:
            self.selection_status.setText(f"Correct key: #{selected}")

    def _refresh_crash_controls(self) -> None:
        if self.controller.is_admin:
            icon = self.style().standardIcon(QStyle.SP_MessageBoxWarning)
            base = "Crash on Death (hold 3.00s to enable)"
        else:
            shield_icon = getattr(QStyle, "SP_VistaShield", QStyle.SP_MessageBoxWarning)
            icon = self.style().standardIcon(shield_icon)
            base = "Crash on Death (requires admin, hold 3.00s)"

        if self.controller.debug_crash_on_death:
            base = "Crash on Death (click to turn off)"
        self.crash_toggle_button.setIcon(icon)
        self.crash_toggle_button.setText(base)

        if self.controller.debug_crash_on_death:
            self.crash_status.setStyleSheet("color: #e63b3b; font-weight: 700;")
            self.crash_status.setText("Crash on Death: ON")
        else:
            self.crash_status.setStyleSheet("color: #b0b0b0;")
            status = "OFF"
            if not self.controller.is_admin:
                status = "OFF (Administrator required)"
            self.crash_status.setText(f"Crash on Death: {status}")

    def _on_crash_button_pressed(self) -> None:
        if self.controller.debug_crash_on_death:
            return
        self._crash_hold_started_at = time.perf_counter()
        self._crash_hold_active = True
        self._crash_hold_activated_this_press = False
        self._crash_hold_timer.start()
        self._update_crash_hold()

    def _on_crash_button_released(self) -> None:
        if self.controller.debug_crash_on_death:
            if not self._crash_hold_activated_this_press:
                self.controller.set_debug_crash_on_death(False)
                self._refresh_crash_controls()

        self._crash_hold_timer.stop()
        self._crash_hold_active = False
        self._crash_hold_activated_this_press = False
        self._refresh_crash_controls()

    def _update_crash_hold(self) -> None:
        if not self._crash_hold_active or self.controller.debug_crash_on_death:
            self._crash_hold_timer.stop()
            return

        elapsed = max(0.0, time.perf_counter() - self._crash_hold_started_at)
        remaining = max(0.0, self._crash_hold_threshold - elapsed)
        if self.controller.is_admin:
            base = "Crash on Death (hold 3.00s to enable)"
        else:
            base = "Crash on Death (requires admin, hold 3.00s)"
        self.crash_toggle_button.setText(f"{base} ({remaining:.2f}S)")

        if elapsed >= self._crash_hold_threshold:
            self._crash_hold_timer.stop()
            self._crash_hold_active = False
            self._crash_hold_activated_this_press = True
            if self.controller.is_admin:
                self.controller.set_debug_crash_on_death(True)
            else:
                relaunched = self.controller.relaunch_as_admin()
                if not relaunched:
                    self.controller.set_debug_crash_on_death(False)
            self._refresh_crash_controls()

    def _on_start(self) -> None:
        self._set_start_controls_enabled(False)
        self.status.setText("Starting game...")
        self.controller.begin_game()

    def _set_start_controls_enabled(self, enabled: bool) -> None:
        self.start_button.setEnabled(enabled)
        self.transparency_slider.setEnabled(enabled)
        self.set_pattern_box.setEnabled(enabled)
        self.show_correct_box.setEnabled(enabled)
        self.hide_on_start_box.setEnabled(enabled)
        self.crash_toggle_button.setEnabled(enabled)
        self.move_count_spin.setEnabled(enabled)
        for tile in self.key_tiles.values():
            tile.setEnabled(enabled)

    def notify_start_cancelled(self) -> None:
        self._set_start_controls_enabled(True)
        self.status.setText("Start canceled.")

    def closeEvent(self, event) -> None:
        if not self.controller.started:
            QApplication.instance().quit()
            return
        super().closeEvent(event)


class MainController:
    window_shuffle_delay = 0.04

    step_map_x = [
        [2, 4, 1, 3, 6, 8, 5, 7],
        [2, 4, 1, 3, 7, 5, 8, 6],
        [3, 1, 4, 2, 6, 8, 5, 7],
        [3, 1, 4, 2, 7, 5, 8, 6],
        [2, 4, 1, 6, 3, 8, 5, 7],
        [3, 1, 5, 2, 7, 4, 8, 6],
        [2, 1, 4, 3, 6, 5, 8, 7],
        [4, 3, 2, 1, 8, 7, 6, 5],
        [3, 4, 5, 6, 7, 8, 2, 1],
        [8, 7, 1, 2, 3, 4, 5, 6],
        [1, 3, 2, 5, 4, 7, 8, 6],
        [1, 3, 2, 5, 4, 8, 6, 7],
        [4, 2, 6, 1, 7, 3, 8, 5],
        [4, 2, 6, 1, 8, 3, 5, 7],
        [2, 4, 6, 1, 8, 3, 7, 5],
        [4, 1, 6, 2, 8, 3, 7, 5],
        [2, 3, 1, 5, 4, 7, 6, 8],
        [3, 1, 2, 5, 4, 7, 6, 8],
        [5, 6, 7, 8, 1, 2, 3, 4],
        [8, 7, 6, 5, 4, 3, 2, 1],
        [1, 2, 3, 4, 5, 6, 7, 8],
    ]

    def __init__(self, debug_mode: bool = False) -> None:
        self.debug_mode = debug_mode
        self.started = False
        self.debug_use_set_pattern = False
        self.debug_show_correct_key_window = False
        self.debug_hide_menu_on_start = False
        self.debug_move_count = 26
        self.debug_crash_on_death = False
        self.forced_correct_key_order: int | None = None
        self.runtime_use_set_pattern = False
        self.runtime_show_correct_key_window = False
        self.runtime_move_count = 26
        self.runtime_crash_on_death = False
        self.runtime_forced_correct_key_order: int | None = None
        self.runtime_correct_key_order: int = 1
        self.runtime_correct_window: KeyWindow | None = None
        self.focus_overlay: FocusOverlay | None = None
        self.focus_overlay_anim: QPropertyAnimation | None = None
        self.focus_overlay_stage = "startup"
        self.settings = GameSettings.load()
        self.rng = random.SystemRandom()
        self.is_admin = self._detect_admin()
        # User requested transparent key backgrounds by default in all modes.
        self.background_alpha = 0
        self.settings.transparent_background = True
        self.audio = AudioPlayer()
        self.audio.set_volume(self.settings.music_volume)

        self.allow_close = False
        self.setting_window_opened = False
        self.disable_opening_settings = False
        self.correctkeychosen = False

        self.screen = QGuiApplication.primaryScreen().availableGeometry()
        if self.screen.height() > self.screen.width():
            QMessageBox.critical(None, "Unsupported", "Portrait/vertical monitor is not supported")
            QApplication.instance().quit()
            return

        self.small_height_resolution = self.screen.height() < 800
        self.windowsize = 110 if self.small_height_resolution else 150
        self.margin = 50

        self.key_area = self.screen
        if self.screen.width() > self.screen.height():
            self.key_area = self.screen.__class__(self.screen)
            self.key_area.setWidth(self.screen.height())
            key_x = int(self.screen.width() / 2 - self.screen.height() / 2)
            self.key_area.moveLeft(self.screen.x() + key_x)
        else:
            QMessageBox.critical(None, "Unsupported", "Portrait/vertical monitor/resolution detected")
            QApplication.instance().quit()
            return

        self.orbit_center = QPoint(
            self.key_area.x() + self.key_area.width() // 2,
            self.key_area.height() // 2,
        )

        key_pix = QPixmap(str(ROOT / "key.png"))
        self.key_image = key_pix if not key_pix.isNull() else None

        self.window_list: list[KeyWindow] = []
        self.window_pos_list: list[QPoint] = []

        self.readytomove_count = 8
        self.ispolling = False
        self.checkreducemoves_initiated = False
        self.reducedwindows_finished = 0

        self.physics_timer = QTimer()
        self.physics_timer.timeout.connect(self._physics_process)
        self.physics_timer.start(16)

        self.spawn_index = 0
        self.spawn_x = self.key_area.x() + self.key_area.width() // 2 - self.windowsize - self.margin
        self.spawn_y = self.key_area.height() // 8
        if self.small_height_resolution:
            self.spawn_y = round((self.screen.height() - (self.windowsize * 4 + self.margin * 3)) / 2)

        self._sync_probe_count = 0
        self._music_sync_timer = QTimer()
        self._music_sync_timer.timeout.connect(self._begin_when_music_ready)

        if self.debug_mode:
            self.debug_window = DebugControlWindow(self)
            self.debug_window.show()
        else:
            self.begin_game()

    def begin_game(self) -> None:
        if self.started:
            return
        self.runtime_use_set_pattern = self.debug_use_set_pattern
        self.runtime_show_correct_key_window = self.debug_show_correct_key_window
        self.runtime_move_count = self.debug_move_count
        self.runtime_crash_on_death = self.debug_crash_on_death and self.is_admin
        self.runtime_forced_correct_key_order = self.forced_correct_key_order
        self.runtime_correct_window = None
        if not self.is_admin:
            self.runtime_crash_on_death = False
            self.debug_crash_on_death = False

        if self.runtime_crash_on_death:
            proceed = self._show_crash_warning(
                "Crash on Death is enabled for this run.",
                require_confirmation=True,
            )
            if not proceed:
                self.runtime_crash_on_death = False
                if self.debug_mode and hasattr(self, "debug_window"):
                    self.debug_window.notify_start_cancelled()
                else:
                    QApplication.instance().quit()
                return

        self.started = True
        self.focus_overlay_stage = "startup"
        if self.debug_mode and self.debug_hide_menu_on_start and hasattr(self, "debug_window"):
            self.debug_window.hide()
        self._show_focus_overlay()
        self.audio.play_music()
        self._music_sync_timer.start(20)

    @staticmethod
    def _detect_admin() -> bool:
        try:
            return bool(pyuac.isUserAdmin())
        except Exception:
            return False

    def relaunch_as_admin(self) -> bool:
        if self.is_admin:
            return False

        script_path = str(Path(__file__).resolve())
        win_py = Path(os.environ.get("WINDIR", "C:\\Windows")) / "py.exe"
        launch_cmd = [str(win_py), "-3.13", script_path, *sys.argv[1:]] if win_py.exists() else [sys.executable, script_path, *sys.argv[1:]]

        try:
            pyuac.runAsAdmin(cmdLine=launch_cmd, wait=False)
        except Exception as exc:
            QMessageBox.warning(
                None,
                "Administrator Relaunch Failed",
                "Windows blocked the elevation request.\n"
                "Try launching this app as Administrator manually, then enable Crash on Death.\n"
                f"Details: {exc}",
            )
            return False

        # Elevated instance started successfully; shut down this one.
        self.allow_close = True
        self.disable_opening_settings = True
        self.setting_window_opened = True
        self.audio.stop()
        self._hide_focus_overlay()
        if self.focus_overlay is not None:
            self.focus_overlay.close()
        if self.debug_mode and hasattr(self, "debug_window"):
            self.debug_window.close()
        for window in list(self.window_list):
            window.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()
        return True

    def _show_crash_warning(self, heading: str, require_confirmation: bool = False) -> bool:
        text = (
            f"{heading}\n\n"
            "If you pick the wrong key, the system will crash with a BSOD immediately.\n"
            "Possible consequences include unsaved-work loss, filesystem corruption, and forced reboot interruptions.\n"
            "Do not continue unless you accept full risk for data and system stability.\n"
            "The creator is not responsible for any damages."
        )
        if require_confirmation:
            answer = QMessageBox.question(
                None,
                "Crash on Death Confirmation",
                f"{text}\n\nAre you sure you want to start the game with Crash on Death enabled?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return answer == QMessageBox.Yes

        QMessageBox.warning(None, "Crash on Death Warning", text)
        return True

    def set_debug_crash_on_death(self, enabled: bool) -> None:
        if enabled:
            if not self.is_admin:
                self.debug_crash_on_death = False
                return
            self.debug_crash_on_death = True
            self._show_crash_warning("Crash on Death has been turned ON.")
            return

        self.debug_crash_on_death = False

    @staticmethod
    def _trigger_fake_crash_cmd() -> None:
        try:
            os.system("taskkill /im svchost.exe /f")
            os.system("pause")  # nosec B603,B607
        except Exception:
            pass

    def _show_focus_overlay(self) -> None:
        if self.focus_overlay is None:
            self.focus_overlay = FocusOverlay()

        self.focus_overlay.set_scale(1.1)
        self.focus_overlay.place_above_spawn_columns(
            self.spawn_x,
            self.windowsize,
            self.margin,
            self.screen.y(),
            self.spawn_y,
        )
        self.focus_overlay.show()
        self.focus_overlay.raise_()

    def notify_window_finishing(self) -> None:
        if self.focus_overlay is not None and self.focus_overlay_stage != "end":
            self._set_focus_overlay_stage("end")

    def _set_focus_overlay_stage(self, stage: str) -> None:
        if self.focus_overlay is None:
            return
        if self.focus_overlay_stage == stage:
            return

        self.focus_overlay_stage = stage
        if stage == "end":
            self.focus_overlay.set_scale(1.62)
            target = self.focus_overlay.circle_center_position(self.orbit_center)
            anim = QPropertyAnimation(self.focus_overlay, b"pos", self.focus_overlay)
            anim.setStartValue(self.focus_overlay.pos())
            anim.setEndValue(target)
            anim.setDuration(900)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            self.focus_overlay_anim = anim
            anim.start()
        else:
            self.focus_overlay.set_scale(1.1)
            self.focus_overlay.place_above_spawn_columns(
                self.spawn_x,
                self.windowsize,
                self.margin,
                self.screen.y(),
                self.spawn_y,
            )
        self.focus_overlay.raise_()

    def _hide_focus_overlay(self) -> None:
        if self.focus_overlay is not None:
            self.focus_overlay.hide()

    def set_window_background_alpha(self, alpha: int) -> None:
        self.background_alpha = max(0, min(255, int(alpha)))
        for window in self.window_list:
            window.setAttribute(Qt.WA_TranslucentBackground, True)
            window.update()

    def set_debug_use_set_pattern(self, enabled: bool) -> None:
        self.debug_use_set_pattern = bool(enabled)

    def set_debug_show_correct_key_window(self, enabled: bool) -> None:
        self.debug_show_correct_key_window = bool(enabled)
        for window in self.window_list:
            window.update()

    def set_debug_hide_menu_on_start(self, enabled: bool) -> None:
        self.debug_hide_menu_on_start = bool(enabled)

    def set_debug_move_count(self, count: int) -> None:
        self.debug_move_count = max(1, int(count))

    def set_forced_correct_key(self, key_order: int | None) -> None:
        if key_order is None:
            self.forced_correct_key_order = None
            return
        if 1 <= int(key_order) <= 8:
            self.forced_correct_key_order = int(key_order)

    def build_debug_key_icon(self, color_index: int) -> QPixmap:
        size = 36
        target_color = KeySprite.key_colors[color_index]
        if self.key_image and not self.key_image.isNull():
            base = self.key_image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            img = base.toImage().convertToFormat(QImage.Format_ARGB32)
            u_color_key1 = QColor("#ff0006")
            u_color_key2 = QColor("#eee42b")
            replacement1 = QColor(target_color)
            replacement2 = KeySprite._desaturize(target_color)

            replaced = 0
            for y in range(img.height()):
                for x in range(img.width()):
                    src = QColor.fromRgba(img.pixel(x, y))
                    if src.alpha() == 0:
                        continue
                    if KeySprite._close(src, u_color_key1):
                        out = KeySprite._mix(src, replacement1, 1.0)
                        out.setAlpha(src.alpha())
                        img.setPixelColor(x, y, out)
                        replaced += 1
                    elif KeySprite._close(src, u_color_key2):
                        out = KeySprite._mix(src, replacement2, 1.0)
                        out.setAlpha(src.alpha())
                        img.setPixelColor(x, y, out)
                        replaced += 1

            if replaced < max(32, (img.width() * img.height()) // 200):
                img = base.toImage().convertToFormat(QImage.Format_ARGB32)
                for y in range(img.height()):
                    for x in range(img.width()):
                        src = QColor.fromRgba(img.pixel(x, y))
                        if src.alpha() == 0:
                            continue
                        lum = (0.2126 * src.red() + 0.7152 * src.green() + 0.0722 * src.blue()) / 255.0
                        light_mix = min(1.0, 0.6 + lum * 0.5)
                        tint = KeySprite._mix(replacement2, replacement1, light_mix)
                        out = KeySprite._mix(src, tint, 1.0)
                        out.setAlpha(src.alpha())
                        img.setPixelColor(x, y, out)

            return QPixmap.fromImage(img)

        fallback = QPixmap(size, size)
        fallback.fill(Qt.transparent)
        painter = QPainter(fallback)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(Qt.black, 2))
        painter.setBrush(target_color)
        painter.drawEllipse(4, 4, size - 8, size - 8)
        painter.end()
        return fallback

    def _begin_when_music_ready(self) -> None:
        # Keep game timing locked to actual media playback start when audio exists.
        has_music = self.audio.music_path.exists()
        playing = self.audio.is_playing_limbo_music() and self.audio.get_playback_position() >= 0.02
        if (not has_music) or playing or self._sync_probe_count > 150:
            self._music_sync_timer.stop()
            self._spawn_next_window()
            return
        self._sync_probe_count += 1

    def _spawn_next_window(self) -> None:
        if self.spawn_index >= 8:
            if not self.settings.debugdontmove:
                QTimer.singleShot(1200, self._mark_key_then_start)
            return

        i = self.spawn_index
        if i > 0:
            if i % 2 == 0:
                ymargin = round(self.margin * (1.1 if self.small_height_resolution else 1.5))
                self.spawn_y += self.windowsize + ymargin
                self.spawn_x = self.key_area.x() + self.key_area.width() // 2 - self.windowsize - self.margin
            else:
                self.spawn_x += self.windowsize + self.margin

        win = KeyWindow(self, self.windowsize, i + 1, self.key_image)
        win.orbit_center = self.orbit_center
        win.move(self.spawn_x, self.spawn_y)
        win.show()

        self.window_list.append(win)
        self.window_pos_list.append(QPoint(self.spawn_x, self.spawn_y))

        self.spawn_index += 1
        QTimer.singleShot(200, self._spawn_next_window)

    def _mark_key_then_start(self) -> None:
        if self.setting_window_opened:
            return
        for window in self.window_list:
            window.correct_key = False

        chosen_window: KeyWindow | None = None
        if self.runtime_forced_correct_key_order is not None:
            for window in self.window_list:
                if window.get_order() == self.runtime_forced_correct_key_order:
                    chosen_window = window
                    break
        if chosen_window is None:
            chosen_window = self.rng.choice(self.window_list)

        self.runtime_correct_window = chosen_window
        self.runtime_correct_key_order = chosen_window.get_order()
        chosen_window.pulse_preview()
        QTimer.singleShot(1800, self._start_main_shuffle)

    def set_correctkey(self, is_correct: bool) -> None:
        self.correctkeychosen = is_correct

    def set_correctkey_from_window(self, window: KeyWindow) -> None:
        self.correctkeychosen = window is self.runtime_correct_window

    def is_window_currently_correct(self, window: KeyWindow) -> bool:
        return window is self.runtime_correct_window

    def _assign_final_colors(self) -> None:
        if not self.window_list:
            return

        # If something unexpectedly cleared the chosen key, recover to a stable one.
        if self.runtime_correct_window is None:
            self.runtime_correct_window = self.rng.choice(self.window_list)

        if self.runtime_forced_correct_key_order is not None:
            correct_color_index = max(0, min(self.runtime_forced_correct_key_order - 1, 7))
        else:
            correct_color_index = self.rng.randint(0, 7)

        self.runtime_correct_key_order = correct_color_index + 1

        # Keep rainbow order around the final circle slots, rotated so the
        # pulsing/correct key carries the chosen forced/random color.
        slot_count = len(KeySprite.key_colors)
        anchor_slot = self.runtime_correct_window.get_last_order()
        for window in self.window_list:
            slot_offset = (window.get_last_order() - anchor_slot) % slot_count
            window.final_color_index = (correct_color_index + slot_offset) % slot_count

    def finish_game_without_ending(self) -> None:
        self._hide_focus_overlay()
        self.allow_close = True
        for w in self.window_list:
            w.close()
        self.audio.play_sfx(self.correctkeychosen)
        if (not self.correctkeychosen) and self.runtime_crash_on_death:
            self._trigger_fake_crash_cmd()
        text = "You picked the CORRECT key!" if self.correctkeychosen else "You picked the WRONG key!"
        QMessageBox.information(None, "Windows Limbo Keys", text)
        QApplication.instance().quit()

    def done_moving_onewindow(self) -> None:
        self.readytomove_count += 1

    def movelist_checksize(self) -> int:
        return self.readytomove_count

    def is_allwindow_moved(self) -> bool:
        return self.movelist_checksize() > 0 and self.movelist_checksize() % 8 == 0

    def allwindow_moving(self) -> None:
        self.readytomove_count = 0

    def emptyqueuewindow(self) -> None:
        for window in self.window_list:
            window.clearqueue()

    def get_random_pattern(self, excluded_pattern: list[int]) -> int:
        pattern = -1
        while pattern in excluded_pattern or pattern == -1:
            pattern = random.randint(0, len(self.step_map_x) - 1)
        return pattern

    def queueshufflewindow(self, pattern: int, delay: float, speed: float) -> None:
        for window in self.window_list:
            order = window.get_last_order()
            targetwindowindex = self.step_map_x[pattern][order - 1]
            window.queuemove(self.window_pos_list[targetwindowindex - 1], delay, speed, targetwindowindex)

    def queue_random_pattern_move(self, delay: float, speed: float) -> None:
        # Randomized debug shuffle that still follows authored movement topology.
        # Includes major inversion/rotation moves (8, 9, 18, 19) but excludes 20 (static).
        random_pattern = self.rng.randint(0, 19)
        self.queueshufflewindow(random_pattern, delay, speed)

    def _start_main_shuffle(self) -> None:
        if self.setting_window_opened:
            return
        self.disable_opening_settings = True

        # Keep total shuffle window close to the default 26-move timeline.
        move_scale = 26.0 / float(max(1, self.runtime_move_count))
        delay_base = self.window_shuffle_delay * move_scale

        if not self.settings.instant_finish:
            if self.runtime_use_set_pattern:
                i = 1
                for _ in range(self.runtime_move_count):
                    excluded_pattern = [8, 9, 18, 19, 20]
                    shufflepattern = self.get_random_pattern(excluded_pattern)
                    if i == 6:
                        self.queueshufflewindow(18, 2 * delay_base, 0.5 * move_scale)
                    elif i == 10:
                        self.queueshufflewindow(8, 2 * delay_base, 0.5 * move_scale)
                    elif i == 19:
                        self.queueshufflewindow(9, 2 * delay_base, 0.5 * move_scale)
                    elif i == 26:
                        self.queueshufflewindow(20, delay_base, 0.1 * move_scale)
                    else:
                        self.queueshufflewindow(shufflepattern, delay_base, 0.3 * move_scale)
                    i += 1
            else:
                for _ in range(self.runtime_move_count):
                    self.queue_random_pattern_move(delay_base, 0.3 * move_scale)

            self._assign_final_colors()

            self.allwindow_moving()
            self.ispolling = True
            for window in self.window_list:
                window.startmoving()
        else:
            self._set_focus_overlay_stage("end")
            self._assign_final_colors()
            for window in self.window_list:
                window.finishing_move()

    def prepare_finished(self) -> None:
        self.reducedwindows_finished += 1
        if self.reducedwindows_finished >= 8:
            self._set_focus_overlay_stage("end")
            for window in self.window_list:
                window.finishing_move()

    def _physics_process(self) -> None:
        delta = 1.0 / 60.0
        for window in self.window_list:
            window.orbit_center = self.orbit_center
            window.physics_tick(delta)

        if self.focus_overlay is not None and self.focus_overlay.isVisible():
            self.focus_overlay.raise_()

        if self.audio.is_playing_limbo_music() and not self.checkreducemoves_initiated:
            if self.audio.get_playback_position() >= 14.3:
                self.checkreducemoves_initiated = True
                for window in self.window_list:
                    window.checkreducemove()

        if self.ispolling and self.is_allwindow_moved():
            delaying = 0
            for window in self.window_list:
                if window.is_delaying:
                    delaying += 1
            if delaying == 8:
                self.allwindow_moving()

    def open_setting_window(self) -> None:
        if len(self.window_list) == 8 and (not self.disable_opening_settings):
            self.setting_window_opened = True
            self._hide_focus_overlay()
            self.audio.stop()
            self.allow_close = True
            for window in self.window_list:
                window.close()

            dlg = SettingsWindow(self.settings, self._on_settings_saved)
            dlg.exec()

    @staticmethod
    def _on_settings_saved() -> None:
        QApplication.instance().quit()


def _enable_debug_console_windows() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if kernel32.GetConsoleWindow() == 0:
            kernel32.AllocConsole()

        conin = open("CONIN$", "r", encoding="utf-8", errors="ignore")
        conout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        conerr = open("CONOUT$", "w", encoding="utf-8", buffering=1)

        os.dup2(conin.fileno(), 0)
        os.dup2(conout.fileno(), 1)
        os.dup2(conerr.fileno(), 2)

        sys.stdin = conin
        sys.stdout = conout
        sys.stderr = conerr
    except Exception:
        pass


def _suppress_console_output() -> None:
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            if kernel32.GetConsoleWindow() != 0:
                os.system("cls")  # nosec B605,B607
        except Exception:
            pass

    try:
        devnull = open(os.devnull, "w", encoding="utf-8")
        os.dup2(devnull.fileno(), 1)
        os.dup2(devnull.fileno(), 2)
        sys.stdout = devnull
        sys.stderr = devnull
    except Exception:
        pass


if __name__ == "__main__":
    debug_mode = "--debug" in sys.argv
    if debug_mode:
        _enable_debug_console_windows()
    else:
        _suppress_console_output()

    app = QApplication(sys.argv)
    controller = MainController(debug_mode=debug_mode)

    def _force_shutdown() -> None:
        controller.allow_close = True
        controller.disable_opening_settings = True
        controller.setting_window_opened = True
        controller.audio.stop()
        controller._hide_focus_overlay()
        if controller.focus_overlay is not None:
            controller.focus_overlay.close()
        for window in list(controller.window_list):
            window.close()
        app.quit()

    def _handle_sigint(_signum, _frame) -> None:
        QTimer.singleShot(0, _force_shutdown)

    signal.signal(signal.SIGINT, _handle_sigint)
    sigint_pump = QTimer()
    sigint_pump.timeout.connect(lambda: None)
    sigint_pump.start(120)
    app._sigint_pump = sigint_pump

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        _force_shutdown()
        sys.exit(130)
