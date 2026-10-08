import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema

from sources.sap.__main__ import REPOSITORY, generate, local_output
from sources.sap.config import read_json


class LocalCliTests(unittest.TestCase):
    def test_output_must_remain_in_ignored_local_sap_directory(self):
        for path in (REPOSITORY, REPOSITORY / "sources" / "sap", REPOSITORY / ".state" / "sap"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                local_output(path)

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"schema_version":1,"schema_version":2}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                read_json(path)

    def test_generation_has_no_network_and_same_rerun_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp, patch("sources.sap.__main__.REPOSITORY", Path(tmp)):
            output = Path(tmp) / ".state" / "sap" / "case"
            with patch("socket.socket.connect", side_effect=AssertionError("Network calls prohibited")):
                first = generate(output)
                paths = [p for p in output.rglob("*") if p.is_file()]
                mtimes = {p: p.stat().st_mtime_ns for p in paths}
                second = generate(output)
            self.assertEqual(first["status"], "created")
            self.assertEqual(second["status"], "unchanged")
            self.assertEqual(mtimes, {p: p.stat().st_mtime_ns for p in paths})
            self.assertEqual(list(output.parent.glob(".sap-pending-*")), [])

    def test_modified_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp, patch("sources.sap.__main__.REPOSITORY", Path(tmp)):
            output = Path(tmp) / ".local" / "sap" / "case"
            generate(output)
            summary = output / "summary.json"
            summary.write_text("user edits", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "differs"):
                generate(output)
            self.assertEqual(summary.read_text(), "user edits")
            self.assertEqual(list(output.parent.glob(".sap-pending-*")), [])

    def test_incomplete_output_and_invalid_config_fail_without_replacing_data(self):
        with tempfile.TemporaryDirectory() as tmp, patch("sources.sap.__main__.REPOSITORY", Path(tmp)):
            root = Path(tmp)
            output = root / ".state" / "sap" / "case"
            output.mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                generate(output)
            self.assertEqual(list(output.iterdir()), [])
            invalid = root / "bad.json"
            invalid.write_text("{}", encoding="utf-8")
            with self.assertRaises(jsonschema.ValidationError) as error:
                generate(root / ".state" / "sap" / "other", invalid)
            self.assertIn("required", str(error.exception))
            self.assertFalse((root / ".state" / "sap" / "other").exists())


if __name__ == "__main__":
    unittest.main()
