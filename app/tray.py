"""System tray icon and menu for the DanmuApp desktop shell.

QSystemTrayIcon 持有"显示控制台 / 检查更新 / 卸载应用 / 退出"等菜单；
所有 handler 都运行在主线程，不需要额外的 invoke_on_main 桥接。
"""

import threading

from PyQt6.QtCore import QObject, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QMessageBox, QProgressDialog, QSystemTrayIcon

from app.bundle_paths import resource_path
from app.translations import Translator, tr


class _UpdateCheckBridge(QObject):
    """跨线程信号桥：后台线程 emit → 主线程 slot（QueuedConnection）。"""

    done = pyqtSignal(object, str, bool, bool)


class TrayManager:
    def __init__(self, app):
        self.app = app
        self.tray = QSystemTrayIcon()
        self.menu = QMenu()
        self._update_progress = None
        self._update_poll_timer = None
        self._update_check_in_flight = False
        self._startup_update_check_scheduled = False
        self._startup_update_prompt_suppressed = False
        self._update_check_bridge = _UpdateCheckBridge()
        self._update_check_bridge.done.connect(self._on_check_update_done)
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

        self.check_update_action = QAction()
        self.check_update_action.triggered.connect(self._on_check_update)

        self.uninstall_action = QAction()
        self.uninstall_action.triggered.connect(self._on_uninstall)

        self.quit_action = QAction()
        self.quit_action.triggered.connect(self.app.quit)

        self.menu.addAction(self.toggle_action)
        self.menu.addAction(self.settings_action)
        self.menu.addSeparator()
        self.menu.addAction(self.check_update_action)
        self.menu.addAction(self.uninstall_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)
        self._retranslate_ui()

    def _retranslate_ui(self):
        self.settings_action.setText(tr("tray.settings"))
        self.check_update_action.setText(tr("tray.check_update", "检查更新"))
        self.uninstall_action.setText(tr("tray.uninstall", "卸载应用"))
        self.quit_action.setText(tr("tray.quit"))
        self.update_state(getattr(self.app.engine, "running", False))

    def schedule_startup_update_check(self, delay_ms: int = 2000) -> None:
        """启动后后台检查更新；失败静默，有更新时弹窗（本次运行可「稍后提醒」抑制）。"""
        if self._startup_update_check_scheduled:
            return
        self._startup_update_check_scheduled = True
        QTimer.singleShot(delay_ms, self._run_startup_update_check)

    def _run_startup_update_check(self) -> None:
        if self._update_check_in_flight or self._startup_update_prompt_suppressed:
            return
        self._start_update_check(
            title=tr("tray.check_update", "检查更新"),
            force=False,
            silent=True,
            is_startup=True,
        )

    def _on_check_update(self):
        if self._update_check_in_flight:
            return
        title = tr("tray.check_update", "检查更新")
        # 即时反馈：气泡提示正在检查（非阻塞）
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.showMessage(
                "DanmuAI",
                tr("tray.update_checking", "正在检查更新…"),
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )
        self._start_update_check(title=title, force=True, silent=False, is_startup=False)

    def _start_update_check(self, *, title: str, force: bool, silent: bool, is_startup: bool) -> None:
        if self._update_check_in_flight:
            return
        self._update_check_in_flight = True

        def _worker():
            from app import update_service
            try:
                result = update_service.check_for_updates(force=force)
            except Exception as exc:  # boundary: tray update check worker
                # 兜底：update_service 内部已有 try/except，此处防止未预期异常静默丢失
                result = update_service.UpdateStatus(
                    ok=False,
                    frozen=False,
                    error=str(exc),
                    message=tr("tray.update_check_failed", "检查失败"),
                )
            # 经 Qt 信号投递到主线程（QueuedConnection），不阻塞后台线程
            self._update_check_bridge.done.emit(
                result,
                title,
                silent,
                is_startup,
            )

        threading.Thread(target=_worker, daemon=True, name="tray-update-check").start()

    def _on_check_update_done(self, result, title, silent=False, is_startup=False):
        from app import update_service

        self._update_check_in_flight = False
        if silent and not result.ok:
            return
        if silent and not result.update_available:
            return
        if is_startup and self._startup_update_prompt_suppressed:
            return
        if not result.ok:
            detail = result.message or result.error or tr("tray.update_check_failed", "检查失败")
            QMessageBox.warning(None, title, detail)
            return
        if result.update_available:
            if is_startup:
                self._show_startup_update_prompt(result, title)
                return
            reply = QMessageBox.question(
                None,
                title,
                tr("tray.update_download_prompt").format(version=result.latest_version),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                dl = update_service.download_updates(wait=False)
                if not dl.ok or not dl.downloading:
                    # 非冻结环境或已下载完毕，走原有流程
                    if dl.ok and dl.download_ready:
                        restart = QMessageBox.question(
                            None,
                            title,
                            tr("tray.update_restart_prompt", "更新已下载，是否立即重启安装？"),
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        )
                        if restart == QMessageBox.StandardButton.Yes:
                            update_service.apply_updates_and_restart()
                    elif not dl.ok:
                        QMessageBox.warning(
                            None,
                            title,
                            dl.message or dl.error or tr("tray.update_download_failed", "下载失败"),
                        )
                    return

                self._begin_update_download_progress(title)
            else:
                pass  # 用户选择不下载
        elif not silent:
            QMessageBox.information(
                None,
                title,
                result.message or tr("tray.update_up_to_date", "已是最新版本"),
            )

    def _show_startup_update_prompt(self, result, title: str) -> None:
        """启动自动检查发现新版本：展示版本信息与更新说明，不阻塞启动主链路。"""
        from app import update_service
        from app.supabase_app_updates import fetch_app_update_result

        release_notes = ""
        try:
            remote = fetch_app_update_result()
            if remote.update is not None:
                release_notes = str(remote.update.message or "").strip()
        except Exception:  # boundary: startup update notes fetch
            release_notes = ""

        current = result.current_version or "-"
        latest = result.latest_version or "-"
        body = tr("tray.startup_update_body", "当前版本：{current}\n最新版本：{latest}").format(
            current=current,
            latest=latest,
        )
        if release_notes:
            body += "\n\n" + tr("tray.startup_update_notes_heading", "更新内容：") + "\n" + release_notes

        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(tr("tray.startup_update_title", "发现新版本"))
        box.setInformativeText(body)
        btn_update = box.addButton(
            tr("tray.startup_update_now", "更新"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        btn_later = box.addButton(
            tr("tray.startup_update_remind_later", "稍后提醒"),
            QMessageBox.ButtonRole.RejectRole,
        )
        box.setDefaultButton(btn_update)
        box.exec()

        if box.clickedButton() == btn_later:
            self._startup_update_prompt_suppressed = True
            return

        if box.clickedButton() != btn_update:
            return

        dl = update_service.download_updates(wait=False)
        if not dl.ok or not dl.downloading:
            if dl.ok and dl.download_ready:
                restart = QMessageBox.question(
                    None,
                    title,
                    tr("tray.update_restart_prompt", "更新已下载，是否立即重启安装？"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if restart == QMessageBox.StandardButton.Yes:
                    update_service.apply_updates_and_restart()
            elif not dl.ok:
                QMessageBox.warning(
                    None,
                    title,
                    dl.message or dl.error or tr("tray.update_download_failed", "下载失败"),
                )
            return

        self._begin_update_download_progress(title)

    def _begin_update_download_progress(self, title: str) -> None:
        from app import update_service

        # 清理上一次更新进度对话框（防止用户重复触发"检查更新"残留旧对话框）
        if self._update_progress is not None or self._update_poll_timer is not None:
            if self._update_poll_timer is not None:
                self._update_poll_timer.stop()
            self._update_progress = None
            self._update_poll_timer = None

        self._update_progress = QProgressDialog(
            tr("tray.update_downloading", "正在下载更新…"),
            tr("common.cancel", "取消"),
            0, 100, None,
        )
        self._update_progress.setWindowTitle(title)
        self._update_progress.setModal(True)
        self._update_progress.setAutoClose(False)
        self._update_progress.setAutoReset(False)
        self._update_progress.show()

        self._update_poll_timer = QTimer()
        self._update_poll_timer.setInterval(200)

        def _poll_progress():
            try:
                st = update_service.get_status()
                pct = getattr(st, "download_progress", 0) or 0
                self._update_progress.setValue(int(pct))
                if st.download_ready:
                    self._update_poll_timer.stop()
                    self._update_progress.close()
                    self._update_progress = None
                    self._update_poll_timer = None
                    restart = QMessageBox.question(
                        None,
                        title,
                        tr("tray.update_restart_prompt", "更新已下载，是否立即重启安装？"),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if restart == QMessageBox.StandardButton.Yes:
                        update_service.apply_updates_and_restart()
                elif not st.downloading and not st.download_ready:
                    self._update_poll_timer.stop()
                    self._update_progress.close()
                    self._update_progress = None
                    self._update_poll_timer = None
                    if not st.ok:
                        QMessageBox.warning(
                            None,
                            title,
                            st.message or st.error or tr("tray.update_download_failed", "下载失败"),
                        )
            except RuntimeError:  # boundary: Qt timer cleanup after download poll
                self._update_poll_timer.stop()
                self._update_progress.close()
                self._update_progress = None
                self._update_poll_timer = None

        self._update_poll_timer.timeout.connect(_poll_progress)
        self._update_poll_timer.start()

        def _on_canceled():
            if self._update_poll_timer is not None:
                self._update_poll_timer.stop()
            self._update_progress = None
            self._update_poll_timer = None

        self._update_progress.canceled.connect(_on_canceled)

    def _on_uninstall(self):
        from app import uninstall_service

        title = tr("tray.uninstall", "卸载应用")
        status = uninstall_service.get_status()
        if not status.supported:
            detail = status.message or status.error or tr("tray.uninstall_unavailable", "当前环境不支持卸载。")
            QMessageBox.warning(None, title, detail)
            return

        # 合并为单对话框：三个选项按钮
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(title)
        box.setText(
            tr("tray.uninstall_prompt", "是否启动卸载？默认会保留用户数据。")
            + "\n\n"
            + tr(
                "tray.uninstall_delete_data_prompt",
                "选择「卸载并删除数据」将同时删除 %APPDATA%\\DanmuAI\\ 下的配置与密钥。",
            )
        )
        _btn_keep = box.addButton(
            tr("tray.uninstall_keep_data", "卸载（保留数据）"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        btn_delete = box.addButton(
            tr("tray.uninstall_delete_data", "卸载并删除数据"),
            QMessageBox.ButtonRole.DestructiveRole,
        )
        btn_cancel = box.addButton(
            tr("common.cancel", "取消"),
            QMessageBox.ButtonRole.RejectRole,
        )
        box.setDefaultButton(btn_cancel)
        box.exec()

        clicked = box.clickedButton()
        if clicked == btn_cancel or clicked is None:
            return

        delete_user_data = (clicked == btn_delete)

        if delete_user_data:
            confirm = QMessageBox.question(
                None,
                title,
                tr(
                    "tray.uninstall_delete_data_confirm",
                    "请再次确认：卸载时将删除 %APPDATA%\\DanmuAI\\ 下的配置与密钥，此操作不可恢复。",
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        launched = uninstall_service.request_uninstall(delete_user_data=delete_user_data)
        if not launched.ok:
            QMessageBox.warning(
                None,
                title,
                launched.message or launched.error or tr("tray.uninstall_failed", "启动卸载失败。"),
            )
            return

        # Velopack uninstall needs DanmuAI.exe to exit before files can be removed.
        self.tray.showMessage(
            title,
            launched.message or tr("tray.uninstall_started", "已启动卸载程序。"),
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )
        QTimer.singleShot(0, self.app.quit)

    def _on_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.app.show_settings()

    def _tooltip_with_action_hint(self, state_key: str) -> str:
        """S-005: surface tray click recovery on hover (tray has no window chrome)."""
        hint = tr("tray.tooltip_action_hint", "单击打开设置")
        return f"{tr(state_key)} - {hint}"

    def update_state(self, running: bool):
        if running:
            self.tray.setIcon(self._create_icon(QColor(80, 200, 80)))
            self.tray.setToolTip(self._tooltip_with_action_hint("tray.tooltip_running"))
            self.toggle_action.setText(tr("tray.stop"))
        else:
            self.tray.setIcon(self._create_icon(QColor(100, 100, 100)))
            state_key = "tray.tooltip_stopped"
            if getattr(self.app.engine, "running", False):
                state_key = "tray.tooltip_paused"
            self.tray.setToolTip(self._tooltip_with_action_hint(state_key))
            self.toggle_action.setText(tr("tray.start"))

    def show(self):
        self.tray.show()

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

    def show_api_key_missing_hint(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray.showMessage(
            "DanmuAI",
            tr("app.api_key_missing_warning"),
            QSystemTrayIcon.MessageIcon.Warning,
            3000,
        )
