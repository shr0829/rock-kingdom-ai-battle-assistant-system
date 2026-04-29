from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

from PySide6.QtCore import QEvent, QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
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

        self.setWindowTitle("AI洛克 · 对战辅助")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(520, 720)
        self._build_ui()
        self._apply_styles()
        self._load_settings_to_form()
        self.hotkey_manager.triggered.connect(self.start_capture_analysis)
        self._register_hotkey()
        self._update_status("就绪。按全局热键或点击按钮开始截图分析。")

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
        subheader = QLabel("点击开始后自动截图并识别双方宠物，先确认样本再优化识别")
        subheader.setWordWrap(True)
        subheader.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        layout.addWidget(header)
        layout.addWidget(subheader)

        start_row = QHBoxLayout()
        start_row.addStretch(1)
        self.capture_button = QPushButton("开始")
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

        self.detail_toggle_button = QPushButton("等待识别结果")
        self.detail_toggle_button.setObjectName("detailToggleButton")
        self.detail_toggle_button.setCheckable(True)
        self.detail_toggle_button.setDisabled(True)
        self.detail_toggle_button.toggled.connect(self._toggle_detail_panel)
        layout.addWidget(self.detail_toggle_button)

        self.detail_panel = QGroupBox("确认与样本保存")
        self.detail_panel.setObjectName("detailPanel")
        self.detail_panel.setVisible(False)
        detail_layout = QVBoxLayout(self.detail_panel)
        self.state_output = QPlainTextEdit()
        self.state_output.setReadOnly(True)
        pet_confirm_box = QGroupBox("宠物识别确认（不对就直接输入正确名字）")
        pet_confirm_layout = QFormLayout(pet_confirm_box)
        self.player_pet_combo = QComboBox()
        self.player_pet_combo.setEditable(True)
        self.opponent_pet_combo = QComboBox()
        self.opponent_pet_combo.setEditable(True)
        self.confirm_pet_button = QPushButton("确认无误并保存样本")
        self.confirm_pet_button.setDisabled(True)
        self.confirm_pet_button.clicked.connect(self.confirm_pet_samples)
        pet_confirm_layout.addRow("我方宠物", self.player_pet_combo)
        pet_confirm_layout.addRow("对方宠物", self.opponent_pet_combo)
        pet_confirm_layout.addRow("", self.confirm_pet_button)
        self.advice_output = QPlainTextEdit()
        self.advice_output.setReadOnly(True)
        self.evidence_output = QPlainTextEdit()
        self.evidence_output.setReadOnly(True)
        detail_layout.addWidget(pet_confirm_box)
        detail_layout.addWidget(QLabel("当前阶段"))
        detail_layout.addWidget(self.advice_output, 2)
        detail_layout.addWidget(QLabel("识别详情"))
        detail_layout.addWidget(self.state_output, 2)
        detail_layout.addWidget(QLabel("资料依据"))
        detail_layout.addWidget(self.evidence_output, 2)
        layout.addWidget(self.detail_panel, 1)
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
            QGroupBox {
                border: 1px solid #7C3AED;
                border-radius: 12px;
                margin-top: 12px;
                padding-top: 12px;
                font-weight: bold;
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
            QPushButton#detailToggleButton {
                background: #16162F;
                border: 1px solid #342A61;
                border-radius: 8px;
                padding: 8px 10px;
                text-align: left;
            }
            QPushButton#detailToggleButton:checked {
                border-color: #7C3AED;
                background: #1E1B3F;
            }
            QGroupBox#detailPanel {
                margin-top: 6px;
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
        self.confirm_pet_button.setDisabled(True)
        self.detail_toggle_button.setDisabled(True)
        self.detail_toggle_button.setChecked(False)
        self.detail_toggle_button.setText("正在识别，请稍候…")
        self._set_busy(True, "正在截图并识别双方宠物…")
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
        self.last_analysis_result = result
        battle_state = result.battle_state
        advice = result.advice
        knowledge_text = (
            "\n\n".join(f"{item.title}\n{item.content}" for item in result.knowledge_hits)
            or "当前阶段已跳过资料检索和建议生成；请先确认或修正宠物名并保存样本。"
        )
        key_notes = battle_state.field_notes[:3] or ["未识别到明显节奏信息"]
        unknowns = battle_state.unknowns[:3] or ["无"]
        state_quality = "信息不足，建议补截图" if not battle_state.player_pet and not battle_state.visible_moves else "已提取到关键战局信息"
        self.state_output.setPlainText(
            "\n".join(
                [
                    "[作战摘要]",
                    f"识别状态: {state_quality}",
                    f"战术总结: {battle_state.tactical_summary or '当前阶段暂不生成'}",
                    "",
                    "[我方信息]",
                    f"我方精灵: {battle_state.player_pet or '未稳定识别'}",
                    f"我方血量: {battle_state.player_hp_state or '未稳定识别'}",
                    f"可见技能: {', '.join(battle_state.visible_moves) or '未识别到'}",
                    f"状态效果: {', '.join(battle_state.status_effects) or '未识别到'}",
                    "",
                    "[对局对象]",
                    f"对方精灵: {battle_state.opponent_pet or '未稳定识别'}",
                    "",
                    "[节奏与场面]",
                    f"关键信息: {'；'.join(key_notes)}",
                    "",
                    "[待确认]",
                    f"识别疑点: {'；'.join(unknowns)}",
                    f"截图存档: {result.screenshot_path}",
                    f"耗时日志: {result.timing_log_path or '未生成'}",
                ]
            )
        )
        self.advice_output.setPlainText(
            "\n".join(
                [
                    f"推荐操作: {advice.recommended_action}",
                    f"理由: {advice.reason}",
                    f"置信度: {advice.confidence or '未提供'}",
                    f"注意事项: {', '.join(advice.caveats) or '无'}",
                ]
            )
        )
        self.evidence_output.setPlainText(knowledge_text)
        self._populate_pet_confirmation(result)
        self.detail_toggle_button.setDisabled(False)
        self.detail_toggle_button.setText("识别完成 · 展开确认/修正并保存样本")
        self.detail_toggle_button.setChecked(True)
        self._set_busy(False, "分析完成。")

    def confirm_pet_samples(self) -> None:
        if self.last_analysis_result is None:
            QMessageBox.warning(self, "AI洛克", "请先完成一次截图识别。")
            return
        player_name = self.player_pet_combo.currentText().strip()
        opponent_name = self.opponent_pet_combo.currentText().strip()
        if not player_name or not opponent_name:
            QMessageBox.warning(self, "AI洛克", "请先确认或输入我方和对方的正确宠物名。")
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
        self._update_status(f"宠物确认样本已入库：event={event_id}, samples={sample_ids}")

    def _populate_pet_confirmation(self, result: AnalysisResult) -> None:
        self.player_pet_combo.clear()
        self.opponent_pet_combo.clear()
        if result.pet_recognition is None:
            self.player_pet_combo.addItem(result.battle_state.player_pet)
            self.opponent_pet_combo.addItem(result.battle_state.opponent_pet)
            self.confirm_pet_button.setDisabled(True)
            return
        catalog_names = self.advisor.list_pet_catalog_names()
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
        self.player_pet_combo.addItems(player_candidates)
        self.opponent_pet_combo.addItems(opponent_candidates)
        self.confirm_pet_button.setDisabled(False)

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
        self._set_busy(False, "操作失败。")
        self.detail_toggle_button.setDisabled(True)
        self.detail_toggle_button.setChecked(False)
        self.detail_toggle_button.setText("识别失败，请重试")
        QMessageBox.critical(self, "AI洛克", message)

    def _set_busy(self, busy: bool, status_text: str) -> None:
        self.capture_button.setDisabled(busy)
        self.capture_button.setText("识别中" if busy else "开始")
        self._update_status(status_text)

    def _update_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _toggle_detail_panel(self, expanded: bool) -> None:
        self.detail_panel.setVisible(expanded)

    def _register_hotkey(self) -> None:
        try:
            self.hotkey_manager.register(self.settings.hotkey)
        except Exception as exc:  # noqa: BLE001
            self._update_status(f"热键注册失败：{exc}")
