import tempfile
import unittest
from pathlib import Path

from scripts.download_rocom_wiki_artworks import normalize_mediawiki_original_url, safe_filename, unique_path


class DownloadRocomWikiArtworksTests(unittest.TestCase):
    def test_normalize_mediawiki_original_url_strips_thumbnail_segment(self) -> None:
        thumb = (
            "https://patchwiki.biligame.com/images/rocom/thumb/2/25/"
            "o64cvcxq1l6tlur77xjqbwx2s4imabd.png/180px-name.png"
        )

        self.assertEqual(
            normalize_mediawiki_original_url(thumb),
            "https://patchwiki.biligame.com/images/rocom/2/25/o64cvcxq1l6tlur77xjqbwx2s4imabd.png",
        )

    def test_safe_filename_keeps_pet_name_but_removes_windows_forbidden_chars(self) -> None:
        self.assertEqual(safe_filename("迪莫<>:/"), "迪莫")

    def test_unique_path_keeps_plain_name_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "迪莫.png"
            self.assertEqual(unique_path(candidate, set()), candidate)
            candidate.write_bytes(b"x")
            self.assertEqual(unique_path(candidate, set()).name, "迪莫_2.png")


if __name__ == "__main__":
    unittest.main()
