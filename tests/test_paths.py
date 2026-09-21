"""Tests for app/paths.py: where the inbox is read from and where results go."""
import os
import unittest
from pathlib import Path
from unittest import mock

from app import paths


class InboxSourceTests(unittest.TestCase):
    def source(self, value):
        env = {} if value is None else {"INBOX_SOURCE": value}
        with mock.patch.dict(os.environ, env, clear=True):
            return paths.inbox_source()

    def test_defaults_to_the_data_folder(self):
        self.assertEqual(self.source(None), str(paths.ROOT_DIR / "data"))
        self.assertEqual(self.source(""), str(paths.ROOT_DIR / "data"))

    def test_a_relative_folder_is_taken_from_the_repo_root_not_the_cwd(self):
        with mock.patch("os.getcwd", return_value="C:/somewhere/else"):
            self.assertEqual(self.source("data"), str(paths.ROOT_DIR / "data"))

    def test_an_absolute_folder_is_kept(self):
        absolute = str(Path(paths.ROOT_DIR.anchor) / "elsewhere" / "mail")
        self.assertEqual(self.source(absolute), absolute)

    def test_a_server_url_is_passed_through_untouched(self):
        self.assertEqual(self.source("http://localhost:8080"), "http://localhost:8080")


class ResultsFileTests(unittest.TestCase):
    def test_results_go_in_the_results_folder(self):
        self.assertEqual(paths.results_file("output.json"), paths.RESULTS_DIR / "output.json")
        self.assertEqual(paths.RESULTS_DIR, paths.ROOT_DIR / "results")

    def test_the_folder_is_created_when_missing(self):
        with mock.patch.object(Path, "mkdir") as mkdir:
            paths.results_file("x.json")
        mkdir.assert_called_once_with(exist_ok=True)


if __name__ == "__main__":
    unittest.main()
