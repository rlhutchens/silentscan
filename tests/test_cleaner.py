"""
test_cleaner.py

Tests for silentscan/cleaner.py covering:
  - dry-run never touches files
  - clean handles empty report gracefully
  - clean correctly reports succeeded and failed files
  - clean handles missing files gracefully
  - --yes flag skips confirmation prompt
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from silentscan.cleaner import run_clean


# ─── Helpers ──────────────────────────────────────────────────────────────────

def write_report(path: Path, silent_files: list[dict]) -> Path:
    """Write a minimal .silentscan.json report file for testing."""
    report = {
        "scanned_at": "2026-01-01T00:00:00+00:00",
        "root_path": "/fake/root",
        "threshold_db": -60.0,
        "scan_duration_seconds": 1.0,
        "total_files_scanned": len(silent_files),
        "total_silent_files": len(silent_files),
        "total_silent_size_bytes": sum(f["size_bytes"] for f in silent_files),
        "sessions": [
            {
                "session_path": "/fake/root/session",
                "silent_file_count": len(silent_files),
                "silent_files": silent_files,
            }
        ],
    }
    report_path = path / "test.silentscan.json"
    report_path.write_text(json.dumps(report))
    return report_path


def make_silent_file_entry(path: Path) -> dict:
    """Create a silent file dict entry pointing to a real file."""
    path.write_bytes(b"\x00" * 1024)
    return {
        "path": str(path),
        "size_bytes": 1024,
        "duration_seconds": 1.0,
    }


# ─── Dry run ──────────────────────────────────────────────────────────────────

class TestDryRun:

    def test_dry_run_does_not_delete_files(self, tmp_path):
        """Files should still exist after a dry run."""
        audio_file = tmp_path / "silent.wav"
        entry = make_silent_file_entry(audio_file)
        report_path = write_report(tmp_path, [entry])

        run_clean(report_path, dry_run=True, yes=True)

        assert audio_file.exists()

    def test_dry_run_does_not_call_trash(self, tmp_path):
        """The _trash_file function should never be called during a dry run."""
        audio_file = tmp_path / "silent.wav"
        entry = make_silent_file_entry(audio_file)
        report_path = write_report(tmp_path, [entry])

        with patch("silentscan.cleaner._trash_file") as mock_trash:
            run_clean(report_path, dry_run=True, yes=True)
            mock_trash.assert_not_called()


# ─── Empty report ─────────────────────────────────────────────────────────────

class TestEmptyReport:

    def test_empty_report_does_not_crash(self, tmp_path):
        """A report with no silent files should complete without error."""
        report_path = write_report(tmp_path, [])
        run_clean(report_path, dry_run=False, yes=True)

    def test_empty_report_does_not_call_trash(self, tmp_path):
        """No trash calls should be made for an empty report."""
        report_path = write_report(tmp_path, [])

        with patch("silentscan.cleaner._trash_file") as mock_trash:
            run_clean(report_path, dry_run=False, yes=True)
            mock_trash.assert_not_called()


# ─── Successful recycling ─────────────────────────────────────────────────────

class TestSuccessfulRecycle:

    def test_trash_is_called_for_each_file(self, tmp_path):
        """_trash_file should be called once per file in the report."""
        files = [
            make_silent_file_entry(tmp_path / f"silent_{i}.wav")
            for i in range(3)
        ]
        report_path = write_report(tmp_path, files)

        with patch("silentscan.cleaner._trash_file", return_value=True) as mock_trash:
            run_clean(report_path, dry_run=False, yes=True)
            assert mock_trash.call_count == 3

    def test_trash_is_called_with_correct_path(self, tmp_path):
        """_trash_file should be called with the correct Path object."""
        audio_file = tmp_path / "silent.wav"
        entry = make_silent_file_entry(audio_file)
        report_path = write_report(tmp_path, [entry])

        with patch("silentscan.cleaner._trash_file", return_value=True) as mock_trash:
            run_clean(report_path, dry_run=False, yes=True)
            called_path = mock_trash.call_args[0][0]
            assert called_path == audio_file


# ─── Failed recycling ─────────────────────────────────────────────────────────

class TestFailedRecycle:

    def test_missing_file_is_not_passed_to_trash(self, tmp_path):
        """Files that no longer exist should be skipped, not passed to _trash_file."""
        entry = {
            "path": str(tmp_path / "ghost.wav"),
            "size_bytes": 1024,
            "duration_seconds": 1.0,
        }
        report_path = write_report(tmp_path, [entry])

        with patch("silentscan.cleaner._trash_file") as mock_trash:
            run_clean(report_path, dry_run=False, yes=True)
            mock_trash.assert_not_called()

    def test_failed_trash_does_not_crash(self, tmp_path):
        """If _trash_file returns False, run_clean should continue without raising."""
        audio_file = tmp_path / "silent.wav"
        entry = make_silent_file_entry(audio_file)
        report_path = write_report(tmp_path, [entry])

        with patch("silentscan.cleaner._trash_file", return_value=False):
            run_clean(report_path, dry_run=False, yes=True)

    def test_partial_failure_continues(self, tmp_path):
        """If one file fails, remaining files should still be processed."""
        files = [
            make_silent_file_entry(tmp_path / f"silent_{i}.wav")
            for i in range(3)
        ]
        report_path = write_report(tmp_path, files)

        # First call fails, subsequent calls succeed
        side_effects = [False, True, True]
        with patch("silentscan.cleaner._trash_file", side_effect=side_effects) as mock_trash:
            run_clean(report_path, dry_run=False, yes=True)
            assert mock_trash.call_count == 3


# ─── Yes flag ─────────────────────────────────────────────────────────────────

class TestYesFlag:

    def test_yes_flag_skips_confirmation(self, tmp_path):
        """With --yes, run_clean should not prompt for input."""
        audio_file = tmp_path / "silent.wav"
        entry = make_silent_file_entry(audio_file)
        report_path = write_report(tmp_path, [entry])

        with patch("silentscan.cleaner._trash_file", return_value=True):
            with patch("builtins.input") as mock_input:
                run_clean(report_path, dry_run=False, yes=True)
                mock_input.assert_not_called()