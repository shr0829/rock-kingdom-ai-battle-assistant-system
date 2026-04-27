from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path


class CaptureError(RuntimeError):
    pass


class ScreenCaptureService:
    def __init__(self, captures_dir: Path) -> None:
        self.captures_dir = captures_dir

    def capture_primary_screen(self) -> tuple[bytes, Path]:
        screenshot_path = self._next_capture_path()
        self._capture_with_gdi(screenshot_path)
        image_bytes = screenshot_path.read_bytes()
        return image_bytes, screenshot_path

    def _next_capture_path(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return self.captures_dir / f"capture-{timestamp}.png"

    @staticmethod
    def _capture_with_gdi(output_path: Path) -> None:
        # Keep the runtime dependency-free: use Windows' built-in .NET drawing APIs
        # through a no-profile PowerShell helper to write a PNG screenshot.
        script = rf"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {{
  $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
  $bitmap.Save('{str(output_path).replace("'", "''")}', [System.Drawing.Imaging.ImageFormat]::Png)
}} finally {{
  $graphics.Dispose()
  $bitmap.Dispose()
}}
"""
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0 or not output_path.exists():
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise CaptureError(f"截图失败：{detail}")
