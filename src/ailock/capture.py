from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from .models import AppSettings


class CaptureError(RuntimeError):
    pass


class ScreenCaptureService:
    def __init__(self, captures_dir: Path, settings: AppSettings | None = None) -> None:
        self.captures_dir = captures_dir
        self.window_title_keyword = ""
        self.capture_client_area = True
        if settings is not None:
            self.refresh_settings(settings)

    def refresh_settings(self, settings: AppSettings) -> None:
        self.window_title_keyword = settings.capture_window_title.strip()
        self.capture_client_area = settings.capture_window_client_area

    def capture_primary_screen(self) -> tuple[bytes, Path]:
        screenshot_path = self._next_capture_path()
        if not self.window_title_keyword:
            raise CaptureError("未配置窗口标题关键词；为避免误截其他画面，本工具不会退回到全屏截图。")
        self._capture_window_with_gdi(
            screenshot_path,
            title_keyword=self.window_title_keyword,
            client_area=self.capture_client_area,
        )
        image_bytes = screenshot_path.read_bytes()
        return image_bytes, screenshot_path

    def _next_capture_path(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return self.captures_dir / f"capture-{timestamp}.png"

    @staticmethod
    def _capture_primary_screen_with_gdi(output_path: Path) -> None:
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

    @staticmethod
    def _capture_window_with_gdi(output_path: Path, title_keyword: str, client_area: bool) -> None:
        escaped_output = str(output_path).replace("'", "''")
        escaped_keyword = title_keyword.replace("'", "''")
        client_area_literal = "$true" if client_area else "$false"
        script = rf"""
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;

public static class Win32Capture {{
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

    [DllImport("user32.dll")]
    public static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);

    [DllImport("user32.dll")]
    public static extern bool ClientToScreen(IntPtr hWnd, ref POINT lpPoint);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool SetProcessDPIAware();

    public struct RECT {{
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }}

    public struct POINT {{
        public int X;
        public int Y;
    }}
}}
"@

$ErrorActionPreference = "Stop"
[Win32Capture]::SetProcessDPIAware() | Out-Null
$keyword = '{escaped_keyword}'
$captureClientArea = {client_area_literal}
$matches = New-Object 'System.Collections.Generic.List[System.IntPtr]'
[Win32Capture]::EnumWindows({{
  param([IntPtr]$hwnd, [IntPtr]$lparam)
  if (-not [Win32Capture]::IsWindowVisible($hwnd)) {{
    return $true
  }}
  $titleBuilder = New-Object System.Text.StringBuilder 512
  [Win32Capture]::GetWindowText($hwnd, $titleBuilder, $titleBuilder.Capacity) | Out-Null
  $title = $titleBuilder.ToString()
  if ($title -and $title.IndexOf($keyword, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {{
    $matches.Add($hwnd)
  }}
  return $true
}}, [IntPtr]::Zero) | Out-Null

if ($matches.Count -eq 0) {{
  throw "未找到标题包含 '$keyword' 的可见窗口。请先打开洛克王国窗口，或在设置里修改窗口标题关键词。"
}}

$hwnd = $matches[0]
[Win32Capture]::ShowWindow($hwnd, 9) | Out-Null
[Win32Capture]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Milliseconds 180

$left = 0
$top = 0
$width = 0
$height = 0
if ($captureClientArea) {{
  $clientRect = New-Object Win32Capture+RECT
  if (-not [Win32Capture]::GetClientRect($hwnd, [ref]$clientRect)) {{
    throw "读取窗口客户区失败。"
  }}
  $origin = New-Object Win32Capture+POINT
  $origin.X = 0
  $origin.Y = 0
  if (-not [Win32Capture]::ClientToScreen($hwnd, [ref]$origin)) {{
    throw "换算窗口客户区坐标失败。"
  }}
  $left = $origin.X
  $top = $origin.Y
  $width = $clientRect.Right - $clientRect.Left
  $height = $clientRect.Bottom - $clientRect.Top
}} else {{
  $windowRect = New-Object Win32Capture+RECT
  if (-not [Win32Capture]::GetWindowRect($hwnd, [ref]$windowRect)) {{
    throw "读取窗口位置失败。"
  }}
  $left = $windowRect.Left
  $top = $windowRect.Top
  $width = $windowRect.Right - $windowRect.Left
  $height = $windowRect.Bottom - $windowRect.Top
}}

if ($width -le 0 -or $height -le 0) {{
  throw "窗口尺寸无效，可能已最小化或不可截图。"
}}

$bitmap = New-Object System.Drawing.Bitmap $width, $height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {{
  $graphics.CopyFromScreen($left, $top, 0, 0, (New-Object System.Drawing.Size $width, $height))
  $bitmap.Save('{escaped_output}', [System.Drawing.Imaging.ImageFormat]::Png)
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
            raise CaptureError(f"窗口截图失败：{detail}")
