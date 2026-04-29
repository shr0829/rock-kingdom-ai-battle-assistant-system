import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from ailock.capture import CaptureError, ScreenCaptureService
from ailock.models import AppSettings


class CaptureServiceTests(unittest.TestCase):
    def test_default_settings_capture_config_targets_rock_kingdom_window(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service = ScreenCaptureService(Path(temp_dir), AppSettings())

            with mock.patch.object(
                ScreenCaptureService,
                "_capture_window_with_gdi",
                side_effect=lambda output_path, **_: output_path.write_bytes(b"window"),
            ) as capture_window:
                image_bytes, screenshot_path = service.capture_primary_screen()

        self.assertEqual(image_bytes, b"window")
        self.assertEqual(screenshot_path.suffix, ".png")
        capture_window.assert_called_once()
        self.assertEqual(capture_window.call_args.kwargs["title_keyword"], "洛克王国")
        self.assertTrue(capture_window.call_args.kwargs["client_area"])

    def test_blank_window_title_is_rejected_to_avoid_full_screen_capture(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service = ScreenCaptureService(
                Path(temp_dir),
                AppSettings(capture_window_title=""),
            )

            with mock.patch.object(
                ScreenCaptureService,
                "_capture_primary_screen_with_gdi",
                side_effect=lambda output_path: output_path.write_bytes(b"screen"),
            ) as capture_screen:
                with self.assertRaisesRegex(CaptureError, "不会退回到全屏截图"):
                    service.capture_primary_screen()

        capture_screen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
