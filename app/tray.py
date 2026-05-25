from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from app.bundle_paths import resource_path
from app.translations import Translator, tr


class TrayManager:
    def __init__(self, app):
        self.app = app
        self.tray = QSystemTrayIcon()
        self.menu = QMenu()
        self._setup()
        Translator.instance().language_changed.connect(self._retranslate_ui)

    def _create_icon(self, color: QColor) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Segoe UI", 34)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRect(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, "D")
        painter.end()
        return QIcon(pixmap)

    def _setup(self):
        icon_path = resource_path("resources", "icon.png")
        if icon_path.exists():
            self.tray.setIcon(QIcon(str(icon_path)))
        else:
            self.tray.setIcon(self._create_icon(QColor(100, 100, 100)))

        self.toggle_action = QAction()
        self.toggle_action.triggered.connect(self.app.toggle)

        self.settings_action = QAction()
        self.settings_action.triggered.connect(self.app.show_settings)

        self.quit_action = QAction()
        self.quit_action.triggered.connect(self.app.quit)

        self.menu.addAction(self.toggle_action)
        self.menu.addAction(self.settings_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)
        self._retranslate_ui()

    def _retranslate_ui(self):
        self.settings_action.setText(tr("tray.settings"))
        self.quit_action.setText(tr("tray.quit"))
        self.update_state(getattr(self.app.engine, "running", False))

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.app.show_settings()

    def update_state(self, running: bool):
        if running:
            self.tray.setIcon(self._create_icon(QColor(80, 200, 80)))
            self.tray.setToolTip(tr("tray.tooltip_running"))
            self.toggle_action.setText(tr("tray.stop"))
        else:
            self.tray.setIcon(self._create_icon(QColor(100, 100, 100)))
            state_key = "tray.tooltip_stopped"
            if getattr(self.app.engine, "running", False):
                state_key = "tray.tooltip_paused"
            self.tray.setToolTip(tr(state_key))
            self.toggle_action.setText(tr("tray.start"))

    def show(self):
        self.tray.show()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray.showMessage(
            "DanmuAI",
            tr("tray.started_message"),
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    def hide(self):
        self.tray.hide()

    def show_minimize_hint(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray.showMessage(
            "DanmuAI",
            tr("tray.minimize_message"),
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )
