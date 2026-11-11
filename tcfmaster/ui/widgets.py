"""Composants d'interface réutilisables."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)


def fmt_seconds(sec: int) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


class Card(QFrame):
    def __init__(self, title: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 14, 16, 14)
        self.lay.setSpacing(8)
        if title:
            t = QLabel(title)
            t.setObjectName("H2")
            self.lay.addWidget(t)


class Kpi(Card):
    def __init__(self, label: str, value: str = "–", parent=None):
        super().__init__(parent=parent)
        self.value = QLabel(value)
        self.value.setObjectName("KpiValue")
        lbl = QLabel(label)
        lbl.setObjectName("KpiLabel")
        lbl.setWordWrap(True)
        self.lay.addWidget(self.value)
        self.lay.addWidget(lbl)

    def set(self, value) -> None:
        self.value.setText("–" if value is None else str(value))


class Page(QWidget):
    """Page standard : titre, sous-titre et zone défilante."""

    def __init__(self, ctx, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(6)
        head = QHBoxLayout()
        tbox = QVBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PageTitle")
        tbox.addWidget(self.title_label)
        if subtitle:
            st = QLabel(subtitle)
            st.setObjectName("PageSubtitle")
            st.setWordWrap(True)
            tbox.addWidget(st)
        head.addLayout(tbox, 1)
        self.header_right = QHBoxLayout()
        head.addLayout(self.header_right)
        outer.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("Content")
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(0, 12, 0, 0)
        self.body.setSpacing(14)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

    def refresh(self) -> None:  # appelé à chaque affichage
        pass

    def clear_body(self) -> None:
        while self.body.count():
            it = self.body.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            elif it.layout() is not None:
                _clear_layout(it.layout())


def _clear_layout(lay) -> None:
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _clear_layout(it.layout())


class CountdownTimer(QLabel):
    """Chronomètre décroissant ; émet `expired` à zéro."""
    expired = Signal()
    tick = Signal(int)

    def __init__(self, seconds: int, parent=None, low_threshold: int = 60):
        super().__init__(parent)
        self.total = seconds
        self.remaining = seconds
        self.low = low_threshold
        self._t = QTimer(self)
        self._t.setInterval(1000)
        self._t.timeout.connect(self._on_tick)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._render()

    def start(self) -> None:
        self._t.start()

    def stop(self) -> None:
        self._t.stop()

    def is_running(self) -> bool:
        return self._t.isActive()

    def elapsed(self) -> int:
        return self.total - self.remaining

    def reset(self, seconds: int | None = None) -> None:
        self.stop()
        if seconds is not None:
            self.total = seconds
        self.remaining = self.total
        self._render()

    def advance(self, seconds: int = 1) -> None:
        """Avance manuelle (utilisé par les tests)."""
        for _ in range(seconds):
            self._on_tick()

    def _on_tick(self) -> None:
        if self.remaining <= 0:
            return
        self.remaining -= 1
        self._render()
        self.tick.emit(self.remaining)
        if self.remaining <= 0:
            self.stop()
            self.expired.emit()

    def _render(self) -> None:
        self.setObjectName("TimerLow" if self.remaining <= self.low else "Timer")
        self.style().unpolish(self)
        self.style().polish(self)
        self.setText("⏱ " + fmt_seconds(self.remaining))


class Stopwatch(QLabel):
    """Chronomètre croissant (entraînement libre)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Timer")
        self.seconds = 0
        self._t = QTimer(self)
        self._t.setInterval(1000)
        self._t.timeout.connect(self._tick)
        self.setText("⏱ 00:00")

    def start(self):
        self._t.start()

    def stop(self):
        self._t.stop()

    def _tick(self):
        self.seconds += 1
        self.setText("⏱ " + fmt_seconds(self.seconds))


def disclaimer_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Disclaimer")
    lbl.setWordWrap(True)
    return lbl
