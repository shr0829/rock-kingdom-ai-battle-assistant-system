from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

from PySide6.QtCore import QEvent, QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
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

        self.setWindowTitle("AI洛克 · 对战辅助")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(980, 720)
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
        layout.setSpacing(12)

        header = QLabel("AI洛克")
        header.setFont(QFont("Microsoft YaHei UI", 22, QFont.Weight.Bold))
        subheader = QLabel("截图直接发给大模型 API，结合本地资料库给出洛克王国 PVP 回合建议")
        subheader.setWordWrap(True)

        layout.addWidget(header)
        layout.addWidget(subheader)

        top_grid = QGridLayout()
        top_grid.setColumnStretch(0, 1)
        top_grid.setColumnStretch(1, 1)

        settings_box = QGroupBox("模型配置")
        settings_form = QFormLayout(settings_box)
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.model_input = QLineEdit()
        self.base_url_input = QLineEdit()
        self.hotkey_input = QLineEdit()
        self.hotkey_input.setReadOnly(True)
        self.hotkey_edit_button = QPushButton("修改热键")
        self.hotkey_edit_button.clicked.connect(self.edit_hotkey)
        hotkey_row = QWidget()
        hotkey_layout = QHBoxLayout(hotkey_row)
        hotkey_layout.setContentsMargins(0, 0, 0, 0)
        hotkey_layout.addWidget(self.hotkey_input, 1)
        hotkey_layout.addWidget(self.hotkey_edit_button)
        self.capture_window_title_input = QLineEdit()
        self.capture_window_title_input.setPlaceholderText("洛克王国")
        self.capture_client_area_input = QCheckBox("只截窗口内容区")
        self.max_hits_input = QSpinBox()
        self.max_hits_input.setRange(1, 20)
        settings_form.addRow("API Key", self.api_key_input)
        settings_form.addRow("Model", self.model_input)
        settings_form.addRow("Base URL", self.base_url_input)
        settings_form.addRow("窗口标题关键词", self.capture_window_title_input)
        settings_form.addRow("窗口截图范围", self.capture_client_area_input)
        settings_form.addRow("全局热键", hotkey_row)
        settings_form.addRow("资料命中数", self.max_hits_input)

        action_box = QGroupBox("操作")
        action_layout = QVBoxLayout(action_box)
        self.save_settings_button = QPushButton("保存设置")
        self.capture_button = QPushButton("截图并分析")
        self.import_button = QPushButton("导入资料文件夹")
        self.save_settings_button.clicked.connect(self.save_settings)
        self.capture_button.clicked.connect(self.start_capture_analysis)
        self.import_button.clicked.connect(self.import_knowledge_folder)
        action_layout.addWidget(self.save_settings_button)
        action_layout.addWidget(self.capture_button)
        action_layout.addWidget(self.import_button)
        action_layout.addStretch(1)

        top_grid.addWidget(settings_box, 0, 0)
        top_grid.addWidget(action_box, 0, 1)
        layout.addLayout(top_grid)

        result_box = QGroupBox("分析结果")
        result_layout = QVBoxLayout(result_box)
        self.status_label = QLabel("")
        self.state_output = QPlainTextEdit()
        self.state_output.setReadOnly(True)
        self.advice_output = QPlainTextEdit()
        self.advice_output.setReadOnly(True)
        self.evidence_output = QPlainTextEdit()
        self.evidence_output.setReadOnly(True)
        result_layout.addWidget(QLabel("状态"))
        result_layout.addWidget(self.status_label)
        result_layout.addWidget(QLabel("战局识别"))
        result_layout.addWidget(self.state_output, 2)
        result_layout.addWidget(QLabel("推荐操作"))
        result_layout.addWidget(self.advice_output, 2)
        result_layout.addWidget(QLabel("资料依据"))
        result_layout.addWidget(self.evidence_output, 2)
        layout.addWidget(result_box, 1)

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
            QLineEdit, QPlainTextEdit, QSpinBox {
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
            QLabel { background: transparent; }
            """
        )

    def _load_settings_to_form(self) -> None:
        self.api_key_input.setText(self.settings.api_key)
        self.model_input.setText(self.settings.model)
        self.base_url_input.setText(self.settings.base_url)
        self.hotkey_input.setText(self.settings.hotkey)
        self.capture_window_title_input.setText(self.settings.capture_window_title)
        self.capture_client_area_input.setChecked(self.settings.capture_window_client_area)
        self.max_hits_input.setValue(self.settings.max_knowledge_hits)

    def _collect_settings(self) -> AppSettings:
        return AppSettings(
            api_key=self.api_key_input.text().strip(),
            model_provider=self.settings.model_provider,
            model=self.model_input.text().strip() or "gpt-5.5",
            review_model=self.settings.review_model,
            model_reasoning_effort=self.settings.model_reasoning_effort,
            base_url=self.base_url_input.text().strip() or "https://api.asxs.top/v1",
            wire_api=self.settings.wire_api,
            requires_openai_auth=self.settings.requires_openai_auth,
            disable_response_storage=self.settings.disable_response_storage,
            network_access=self.settings.network_access,
            windows_wsl_setup_acknowledged=self.settings.windows_wsl_setup_acknowledged,
            model_context_window=self.settings.model_context_window,
            model_auto_compact_token_limit=self.settings.model_auto_compact_token_limit,
            hotkey=self.hotkey_input.text().strip() or "Ctrl+Shift+A",
            max_knowledge_hits=self.max_hits_input.value(),
            screenshot_detail=self.settings.screenshot_detail,
            capture_window_title=self.capture_window_title_input.text().strip(),
            capture_window_client_area=self.capture_client_area_input.isChecked(),
        )

    def save_settings(self) -> None:
        self.settings = self._collect_settings()
        self.settings_saver(self.settings)
        self.advisor.refresh_settings(self.settings)
        self._register_hotkey()
        self._update_status("设置已保存。")

    def edit_hotkey(self) -> None:
        dialog = HotkeyDialog(self.hotkey_input.text().strip() or "Ctrl+Shift+A", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        hotkey_text = dialog.hotkey_text()
        if not hotkey_text:
            QMessageBox.warning(self, "AI洛克", "请先按下一个组合键。")
            return
        self.hotkey_input.setText(hotkey_text)
        self.save_settings()
        self._update_status(f"热键已改为：{hotkey_text}")

    def start_capture_analysis(self) -> None:
        self.save_settings()
        self._set_busy(True, "正在截图并请求模型分析…")
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
        battle_state = result.battle_state
        advice = result.advice
        knowledge_text = "\n\n".join(f"{item.title}\n{item.content}" for item in result.knowledge_hits) or "未命中本地资料。"
        key_notes = battle_state.field_notes[:3] or ["未识别到明显节奏信息"]
        unknowns = battle_state.unknowns[:3] or ["无"]
        state_quality = "信息不足，建议补截图" if not battle_state.player_pet and not battle_state.visible_moves else "已提取到关键战局信息"
        self.state_output.setPlainText(
            "\n".join(
                [
                    "[作战摘要]",
                    f"识别状态: {state_quality}",
                    f"战术总结: {battle_state.tactical_summary or '暂无稳定结论'}",
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
        self._set_busy(False, "分析完成。")

    def _handle_import_result(self, imported_count: int) -> None:
        self._set_busy(False, f"资料导入完成，共处理 {imported_count} 个文件。")

    def _handle_worker_error(self, message: str) -> None:
        self._set_busy(False, "操作失败。")
        QMessageBox.critical(self, "AI洛克", message)

    def _set_busy(self, busy: bool, status_text: str) -> None:
        self.capture_button.setDisabled(busy)
        self.import_button.setDisabled(busy)
        self.save_settings_button.setDisabled(busy)
        self._update_status(status_text)

    def _update_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _register_hotkey(self) -> None:
        try:
            self.hotkey_manager.register(self.settings.hotkey)
        except Exception as exc:  # noqa: BLE001
            self._update_status(f"热键注册失败：{exc}")
