import math
import unittest

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from novelreader.qt_corners import corner_cutout


class QtCornerTests(unittest.TestCase):
    def test_current_size_is_clipped_with_antialiasing_at_all_three_dpis(self):
        for dpr in (1, 1.25, 1.5):
            for width, height in ((400, 300), (631, 417), (320, 210)):
                for radius, inset in ((22, 0), (30, 2)):
                    with self.subTest(dpr=dpr, size=(width, height), radius=radius):
                        image = QImage(math.ceil(width * dpr), math.ceil(height * dpr),
                                       QImage.Format.Format_ARGB32_Premultiplied)
                        image.setDevicePixelRatio(dpr)
                        # Model a stale rectangular web frame, including floating opacity.
                        image.fill(QColor(200, 100, 50, 180))
                        painter = QPainter(image)
                        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                        painter.fillPath(corner_cutout(QRectF(0, 0, width, height), radius, inset),
                                         Qt.GlobalColor.transparent)
                        painter.end()
                        corners = ((0, 0), (image.width() - 1, 0),
                                   (0, image.height() - 1), (image.width() - 1, image.height() - 1))
                        self.assertEqual([image.pixelColor(x, y).alpha() for x, y in corners], [0] * 4)
                        self.assertEqual(image.pixelColor(image.width() // 2, image.height() // 2).alpha(), 180)
                        edge = math.ceil((radius + inset) * dpr)
                        self.assertTrue(any(0 < image.pixelColor(x, y).alpha() < 180
                                            for x in range(edge) for y in range(edge)))


if __name__ == "__main__":
    unittest.main()
