"""Native-size antialiased alpha clipping for software-composited web views."""

from PySide6.QtCore import QRect, QRectF, QTimer, Qt
from PySide6.QtGui import QPainter, QPainterPath, QRegion
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget


def corner_cutout(rect: QRectF, radius: float, inset: float = 0) -> QPainterPath:
    outer = QPainterPath()
    # Extend beyond the logical edge so fractional DPI does not leave a
    # half-painted last row/column when the physical backing size rounds up.
    outer.addRect(rect.adjusted(-1, -1, 1, 1))
    inner = QPainterPath()
    inner.addRoundedRect(rect.adjusted(inset, inset, -inset, -inset), radius, radius)
    return outer.subtracted(inner)


class CornerClip(QWidget):
    """Erase corner alpha after the web view paints into Qt's backing store.

    Qt's current client size is authoritative even when Chromium still paints
    its previous viewport during live resize. No binary native region is used.
    """

    def __init__(self, view: QWebEngineView, surface: str):
        super().__init__(view)
        self._surface = surface
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def refresh(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        # Paint damage only; QRegion is never installed as a window mask.
        edge = 34 if self._surface == "floating" else 24
        width, height = self.width(), self.height()
        damage = QRegion(QRect(0, 0, edge, edge))
        for x, y in ((width - edge, 0), (0, height - edge), (width - edge, height - edge)):
            damage |= QRegion(QRect(x, y, edge, edge))
        if self._surface == "floating":
            for rim in (QRect(0, 0, width, 2), QRect(0, height - 2, width, 2),
                        QRect(0, 0, 2, height), QRect(width - 2, 0, 2, height)):
                damage |= QRegion(rim)
        self.update(damage)

    def paintEvent(self, event) -> None:
        window = self.window()
        if self._surface == "main" and (window.isMaximized() or window.isFullScreen()):
            return
        radius, inset = (30, 2) if self._surface == "floating" else (22, 0)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillPath(corner_cutout(QRectF(self.rect()), radius, inset), Qt.GlobalColor.transparent)
        painter.end()


class RoundedWebEngineView(QWebEngineView):
    def __init__(self, parent: QWidget, surface: str):
        super().__init__(parent)
        self._corner_clip = CornerClip(self, surface)
        self.loadFinished.connect(lambda _ok: self._corner_clip.refresh())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_corner_clip"):
            self._corner_clip.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._corner_clip.show()
        self._corner_clip.refresh()

    def childEvent(self, event) -> None:
        super().childEvent(event)
        if event.added() and hasattr(self, "_corner_clip") and event.child() is not self._corner_clip:
            # Navigation may recreate WebEngine's internal render child.
            QTimer.singleShot(0, self._corner_clip.refresh)
