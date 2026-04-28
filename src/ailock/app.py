from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .advisor import AdvisorService
from .capture import ScreenCaptureService
from .config import ProjectPaths, SettingsStore
from .knowledge import KnowledgeStore
from .ui import MainWindow


def main() -> int:
    paths = ProjectPaths.discover()
    paths.ensure()

    app = QApplication(sys.argv)
    app.setApplicationName("AI洛克")
    app.setOrganizationName("shr")

    settings_store = SettingsStore(paths.settings_path, paths.config_path)
    settings = settings_store.load()
    advisor = AdvisorService(
        settings=settings,
        capture_service=ScreenCaptureService(paths.captures_dir),
        knowledge_store=KnowledgeStore(paths.database_path),
        log_dir=paths.logs_dir,
    )

    window = MainWindow(settings=settings, advisor=advisor, settings_saver=settings_store.save)
    window.show()
    return app.exec()
