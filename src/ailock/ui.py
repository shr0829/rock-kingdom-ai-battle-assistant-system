from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

from PySide6.QtCore import QEvent, QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from .advisor import AdvisorService
from .hotkey import GlobalHotkeyManager
from .models import AnalysisResult, AppSettings

T = TypeVar("T")


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class FunctionWorker(QRunnable):
    def __init__(self, callback: Callable[[], T]) -> None:
        super().__init__()
        self.callback = callback
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.callback()
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(str(exc))
        else:
            self.signals.finished.emit(result)


class HotkeyDialog(QDialog):
    def __init__(self, current_hotkey: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置热键")
        self.setModal(True)
        self.resize(420, 140)

        layout = QVBoxLayout(self)
        tip = QLabel("按下你想要的组合键，然后点确认保存。")
        self.editor = QLineEdit()
        self.editor.setPlaceholderText("例如：Ctrl+Shift+A")
        self.editor.setText(current_hotkey)
        self.editor.setReadOnly(True)
        self.editor.installEventFilter(self)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(tip)
        layout.addWidget(self.editor)
        layout.addWidget(buttons)
        self.editor.setFocus()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self.editor and event.type() == QEvent.Type.KeyPress:
            sequence = self._event_to_sequence_text(event)
            if sequence:
                self.editor.setText(sequence)
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        sequence = self._event_to_sequence_text(event)
        if sequence:
            self.editor.setText(sequence)
            event.accept()
            return
        super().keyPressEvent(event)

    def hotkey_text(self) -> str:
        return self.editor.text().strip()

    @staticmethod
    def _event_to_sequence_text(event) -> str:
        key = event.key()
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape}:
            return ""
        modifiers = []
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            modifiers.append("Ctrl")
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            modifiers.append("Shift")
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            modifiers.append("Alt")
        if event.modifiers() & Qt.KeyboardModifier.MetaModifier:
            modifiers.append("Win")

        if key in {
            Qt.Key.Key_Control,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Meta,
        }:
            return ""

        key_text = QKeySequence(key).toString()
        if not key_text:
            key_text = chr(key).upper() if 32 <= key <= 126 else ""
        if not key_text:
            return ""
        return "+".join([*modifiers, key_text])


class PetRecognitionDialog(QDialog):
    def __init__(
        self,
        result: AnalysisResult,
        *,
        player_candidates: list[str],
        opponent_candidates: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("确认本次精灵识别")
        self.setModal(True)
        self.resize(560, 520)

        layout = QVBoxLayout(self)
        prompt = QLabel("模型识别结果如下；如果不对，直接改成正确的我方/敌方精灵名后确认入库。")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        form = QFormLayout()
        self.player_pet_combo = QComboBox()
        self.player_pet_combo.setEditable(True)
        self.player_pet_combo.addItems(player_candidates)
        self.opponent_pet_combo = QComboBox()
        self.opponent_pet_combo.setEditable(True)
        self.opponent_pet_combo.addItems(opponent_candidates)
        form.addRow("我方精灵", self.player_pet_combo)
        form.addRow("敌方精灵", self.opponent_pet_combo)
        layout.addLayout(form)

        self.detail_output = QPlainTextEdit()
        self.detail_output.setReadOnly(True)
        self.detail_output.setPlainText(self._detail_text(result))
        layout.addWidget(QLabel("其他识别信息"))
        layout.addWidget(self.detail_output, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("确认并存入数据库")
            ok_button.setDisabled(result.pet_recognition is None)
        cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def player_pet_name(self) -> str:
        return self.player_pet_combo.currentText().strip()

    def opponent_pet_name(self) -> str:
        return self.opponent_pet_combo.currentText().strip()

    def accept(self) -> None:  # type: ignore[override]
        if not self.player_pet_name() or not self.opponent_pet_name():
            QMessageBox.warning(self, "AI洛克", "请先确认或输入我方和敌方的正确精灵名。")
            return
        super().accept()

    @staticmethod
    def _detail_text(result: AnalysisResult) -> str:
        battle_state = result.battle_state
        lines = [
            "[模型识别结果]",
            f"我方精灵: {battle_state.player_pet or '未稳定识别'}",
            f"敌方精灵: {battle_state.opponent_pet or '未稳定识别'}",
            f"我方血量: {battle_state.player_hp_state or '未稳定识别'}",
            f"可见技能: {', '.join(battle_state.visible_moves) or '未识别到'}",
            f"状态效果: {', '.join(battle_state.status_effects) or '未识别到'}",
            "",
            "[候选与置信度]",
            *PetRecognitionDialog._pet_channel_summary(result),
            "",
            "[其他]",
            f"识别疑点: {'；'.join(battle_state.unknowns) or '无'}",
            f"截图存档: {result.screenshot_path}",
            f"耗时日志: {result.timing_log_path or '未生成'}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _pet_channel_summary(result: AnalysisResult) -> list[str]:
        recognition = result.pet_recognition
        if recognition is None:
            return ["未启用本地宠物识别，当前结果无法保存为样本。"]

        def summarize_candidates(label: str, candidates) -> str:
            if not candidates:
                return f"{label}: 无"
            return f"{label}: " + "，".join(
                f"{candidate.name}({candidate.confidence:.2f})" for candidate in candidates[:3]
            )

        return [
            f"我方融合: {recognition.player.name or '未识别'}({recognition.player.confidence:.2f})",
            summarize_candidates("我方候选", recognition.player.top_candidates),
            f"敌方融合: {recognition.opponent.name or '未识别'}({recognition.opponent.confidence:.2f})",
            summarize_candidates("敌方候选", recognition.opponent.top_candidates),
        ]


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: AppSettings,
        advisor: AdvisorService,
        settings_saver: Callable[[AppSettings], None],
    ) -> None:
        super().__init__()
        self.settings = settings
        self.advisor = advisor
        self.settings_saver = settings_saver
        self.hotkey_manager = GlobalHotkeyManager(self)
        self.thread_pool = QThreadPool.globalInstance()
        self.last_analysis_result: AnalysisResult | None = None
        self._was_visible_before_capture = False

        self.setWindowTitle("AI洛克 · 对战辅助")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(420, 300)
        self._build_ui()
        self._apply_styles()
        self._load_settings_to_form()
        self.hotkey_manager.triggered.connect(self.start_capture_analysis)
        self._register_hotkey()
        self._update_status("就绪。点击“截图”或按全局热键开始识别。")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.hotkey_manager.unregister()
        return super().closeEvent(event)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QLabel("AI洛克")
        header.setFont(QFont("Microsoft YaHei UI", 22, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        subheader = QLabel("点击截图后自动识别双方精灵，弹窗确认后存入本地数据库")
        subheader.setWordWrap(True)
        subheader.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        layout.addWidget(header)
        layout.addWidget(subheader)

        start_row = QHBoxLayout()
        start_row.addStretch(1)
        self.capture_button = QPushButton("截图")
        self.capture_button.setObjectName("startCaptureButton")
        self.capture_button.setFixedSize(128, 128)
        self.capture_button.clicked.connect(self.start_capture_analysis)
        start_row.addWidget(self.capture_button)
        start_row.addStretch(1)
        layout.addLayout(start_row)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addStretch(1)

        self.setCentralWidget(root)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #0F0F23;
                color: #E2E8F0;
                font-family: "Microsoft YaHei UI";
                font-size: 13px;
            }
            QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {
                background: #16162F;
                border: 1px solid #342A61;
                border-radius: 8px;
                padding: 8px;
                selection-background-color: #7C3AED;
            }
            QPushButton {
                background: #7C3AED;
                border-radius: 10px;
                padding: 10px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #9155FF;
            }
            QPushButton:disabled {
                background: #342A61;
                color: #A0AEC0;
            }
            QPushButton#startCaptureButton {
                border-radius: 64px;
                font-size: 24px;
                font-weight: 800;
            }
            QLabel { background: transparent; }
            """
        )

    def _load_settings_to_form(self) -> None:
        return

    def _collect_settings(self) -> AppSettings:
        return self.settings

    def save_settings(self) -> None:
        self.settings = self._collect_settings()
        self.settings_saver(self.settings)
        self.advisor.refresh_settings(self.settings)
        self._register_hotkey()
        self._update_status("设置已保存。")

    def edit_hotkey(self) -> None:
        dialog = HotkeyDialog(self.settings.hotkey or "Ctrl+Shift+A", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        hotkey_text = dialog.hotkey_text()
        if not hotkey_text:
            QMessageBox.warning(self, "AI洛克", "请先按下一个组合键。")
            return
        self.settings = AppSettings(**{**self.settings.to_dict(), "hotkey": hotkey_text})
        self.settings_saver(self.settings)
        self.advisor.refresh_settings(self.settings)
        self._register_hotkey()
        self._update_status(f"热键已改为：{hotkey_text}")

    def start_capture_analysis(self) -> None:
        self.save_settings()
        self.last_analysis_result = None
        self._set_busy(True, "正在截图并识别双方精灵…")
        self._hide_for_capture()
        worker = FunctionWorker(self.advisor.capture_and_advise)
        worker.signals.finished.connect(self._handle_analysis_result)
        worker.signals.failed.connect(self._handle_worker_error)
        self.thread_pool.start(worker)

    def import_knowledge_folder(self) -> None:
        self.save_settings()
        folder = QFileDialog.getExistingDirectory(self, "选择资料文件夹")
        if not folder:
            return
        self._set_busy(True, f"正在导入资料：{folder}")
        worker = FunctionWorker(lambda: self.advisor.import_knowledge_folder(Path(folder)))
        worker.signals.finished.connect(self._handle_import_result)
        worker.signals.failed.connect(self._handle_worker_error)
        self.thread_pool.start(worker)

    def _handle_analysis_result(self, result: AnalysisResult) -> None:
        self._restore_after_capture()
        self.last_analysis_result = result
        self._set_busy(False, "识别完成，请在弹窗中确认后入库。")
        self._show_confirmation_dialog(result)

    def _save_pet_confirmation(self, *, player_name: str, opponent_name: str) -> None:
        if self.last_analysis_result is None:
            QMessageBox.warning(self, "AI洛克", "请先完成一次截图识别。")
            return
        if not player_name or not opponent_name:
            QMessageBox.warning(self, "AI洛克", "请先确认或输入我方和敌方的正确精灵名。")
            return
        try:
            event_id, sample_ids = self.advisor.save_pet_confirmation(
                self.last_analysis_result,
                player_name=player_name,
                opponent_name=opponent_name,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "AI洛克", str(exc))
            return
        message = f"精灵确认结果已入库：event={event_id}, samples={sample_ids}"
        self._update_status(message)
        QMessageBox.information(self, "AI洛克", message)

    def _show_confirmation_dialog(self, result: AnalysisResult) -> None:
        catalog_names = self.advisor.list_pet_catalog_names()
        if result.pet_recognition is None:
            player_candidates = self._candidate_names([], result.battle_state.player_pet, catalog_names)
            opponent_candidates = self._candidate_names([], result.battle_state.opponent_pet, catalog_names)
        else:
            player_candidates = self._candidate_names(
                result.pet_recognition.player.top_candidates,
                result.battle_state.player_pet,
                catalog_names,
            )
            opponent_candidates = self._candidate_names(
                result.pet_recognition.opponent.top_candidates,
                result.battle_state.opponent_pet,
                catalog_names,
            )
        dialog = PetRecognitionDialog(
            result,
            player_candidates=player_candidates,
            opponent_candidates=opponent_candidates,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._update_status("识别完成，用户未保存本次确认。")
            return
        self._save_pet_confirmation(
            player_name=dialog.player_pet_name(),
            opponent_name=dialog.opponent_pet_name(),
        )

    @staticmethod
    def _candidate_names(candidates, preferred_name: str, catalog_names: list[str]) -> list[str]:
        names: list[str] = []
        for name in [preferred_name, *(candidate.name for candidate in candidates), *catalog_names]:
            name = str(name).strip()
            if name and name not in names:
                names.append(name)
        return names

    def _handle_import_result(self, imported_count: int) -> None:
        self._set_busy(False, f"资料导入完成，共处理 {imported_count} 个文件。")

    def _handle_worker_error(self, message: str) -> None:
        self._restore_after_capture()
        self._set_busy(False, "操作失败。")
        QMessageBox.critical(self, "AI洛克", message)

    def _set_busy(self, busy: bool, status_text: str) -> None:
        self.capture_button.setDisabled(busy)
        self.capture_button.setText("识别中" if busy else "截图")
        self._update_status(status_text)

    def _update_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _hide_for_capture(self) -> None:
        self._was_visible_before_capture = self.isVisible()
        if self._was_visible_before_capture:
            self.hide()
            QApplication.processEvents()

    def _restore_after_capture(self) -> None:
        if self._was_visible_before_capture:
            self.show()
            self.raise_()
            self.activateWindow()
            QApplication.processEvents()
        self._was_visible_before_capture = False

    def _register_hotkey(self) -> None:
        try:
            self.hotkey_manager.register(self.settings.hotkey)
        except Exception as exc:  # noqa: BLE001
            self._update_status(f"热键注册失败：{exc}")
