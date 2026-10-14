import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import (
    clean_temp_directory,
    clear_chromium_history,
    clear_firefox_history,
    discover_browser_history_files,
)


class CleanerTests(unittest.TestCase):
    def test_clean_temp_directory_removes_files_and_subdirectories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "temporary.txt").write_text("temp")
            nested = root / "folder" / "nested"
            nested.mkdir(parents=True)
            (nested / "file.bin").write_bytes(b"temp")

            result = clean_temp_directory(root)

            self.assertEqual(result.files_removed, 2)
            self.assertEqual(result.directories_removed, 2)
            self.assertEqual(result.errors, [])
            self.assertEqual(list(root.iterdir()), [])

    def test_clear_chromium_history_keeps_urls_but_resets_visit_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "History"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER)"
                )
                connection.execute(
                    "CREATE TABLE urls "
                    "(id INTEGER PRIMARY KEY, visit_count INTEGER, "
                    "last_visit_time INTEGER)"
                )
                connection.execute("INSERT INTO visits VALUES (1, 1)")
                connection.execute("INSERT INTO urls VALUES (1, 1, 123)")
            connection.close()

            clear_chromium_history(database)

            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM visits").fetchone()[0], 0)
                self.assertEqual(
                    connection.execute(
                        "SELECT visit_count, last_visit_time FROM urls"
                    ).fetchone(),
                    (0, 0),
                )
            connection.close()

    def test_clear_firefox_history_preserves_bookmarks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "places.sqlite"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE moz_historyvisits "
                    "(id INTEGER PRIMARY KEY, place_id INTEGER)"
                )
                connection.execute(
                    "CREATE TABLE moz_places "
                    "(id INTEGER PRIMARY KEY, visit_count INTEGER, "
                    "last_visit_date INTEGER)"
                )
                connection.execute(
                    "CREATE TABLE moz_bookmarks "
                    "(id INTEGER PRIMARY KEY, fk INTEGER)"
                )
                connection.executemany(
                    "INSERT INTO moz_places VALUES (?, 1, 123)",
                    [(1,), (2,)],
                )
                connection.execute("INSERT INTO moz_historyvisits VALUES (1, 1)")
                connection.execute("INSERT INTO moz_bookmarks VALUES (1, 2)")
            connection.close()

            clear_firefox_history(database)

            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT id, visit_count, last_visit_date FROM moz_places"
                    ).fetchall(),
                    [(2, 0, None)],
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM moz_historyvisits"
                    ).fetchone()[0],
                    0,
                )
            connection.close()

    def test_discover_browser_history_files_finds_supported_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            local = base / "local"
            roaming = base / "roaming"
            chrome_history = local / "Google" / "Chrome" / "User Data" / "Default" / "History"
            firefox_history = roaming / "Mozilla" / "Firefox" / "Profiles" / "test.default" / "places.sqlite"
            chrome_history.parent.mkdir(parents=True)
            firefox_history.parent.mkdir(parents=True)
            chrome_history.touch()
            firefox_history.touch()

            found = discover_browser_history_files(str(roaming), str(local))

            self.assertEqual(
                {(name, path.name, kind) for name, path, kind in found},
                {
                    ("Google Chrome", "History", "chromium"),
                    ("Firefox", "places.sqlite", "firefox"),
                },
            )

    def test_clear_chromium_history_complete_mode_deletes_all_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "History"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER)"
                )
                connection.execute(
                    "CREATE TABLE urls "
                    "(id INTEGER PRIMARY KEY, url TEXT, title TEXT, visit_count INTEGER, last_visit_time INTEGER)"
                )
                connection.execute("INSERT INTO visits VALUES (1, 1)")
                connection.execute("INSERT INTO urls VALUES (1, 'https://example.com', 'Example', 5, 9999)")
            connection.close()

            clear_chromium_history(database, complete=True)

            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM visits").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM urls").fetchone()[0], 0)
            connection.close()

    def test_clean_temp_directory_tracks_bytes_freed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sample = root / "sample.bin"
            sample.write_bytes(b"A" * 2048)

            result = clean_temp_directory(root)
            self.assertEqual(result.files_removed, 1)
            self.assertEqual(result.bytes_freed, 2048)

    def test_format_bytes(self) -> None:
        from app import format_bytes
        self.assertEqual(format_bytes(500), "500 B")
        self.assertEqual(format_bytes(1024), "1.00 KB")
        self.assertEqual(format_bytes(1048576), "1.00 MB")
        self.assertEqual(format_bytes(1073741824), "1.00 GB")

    def test_scan_directory_stats_does_not_delete(self) -> None:
        from app import scan_directory_stats
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "test1.txt").write_bytes(b"12345")
            (root / "test2.txt").write_bytes(b"67890")
            bytes_found, files_found = scan_directory_stats(root)
            self.assertEqual(files_found, 2)
            self.assertEqual(bytes_found, 10)
            self.assertTrue((root / "test1.txt").exists())

    def test_discover_browser_cache_directories(self) -> None:
        from app import discover_browser_cache_directories
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            local = base / "local"
            chrome_cache = local / "Google" / "Chrome" / "User Data" / "Default" / "Cache"
            chrome_cache.mkdir(parents=True)
            ff_cache = local / "Mozilla" / "Firefox" / "Profiles" / "test.profile" / "cache2"
            ff_cache.mkdir(parents=True)

            found = discover_browser_cache_directories(None, str(local))
            found_paths = [p for _, p in found]
            self.assertIn(chrome_cache, found_paths)
            self.assertIn(ff_cache, found_paths)


if __name__ == "__main__":
    unittest.main()

