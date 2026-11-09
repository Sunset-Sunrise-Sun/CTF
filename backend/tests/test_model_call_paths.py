import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.model_calls import ModelCallJournal
from app.providers import ProviderError


@pytest.mark.parametrize("location", ["ledger", "ancestor", "sidecar"])
def test_journal_rejects_symlinks_before_resolution(tmp_path, monkeypatch, location):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.sqlite3"
    sentinel.write_bytes(b"synthetic untouched file")
    root = tmp_path / "data"
    root.mkdir()
    ledger = root / "model-audit.sqlite3"
    if location == "ancestor":
        link = root / "linked"
        target = outside
        ledger = link / "nested" / ledger.name
    else:
        link = (
            ledger
            if location == "ledger"
            else ledger.with_name(ledger.name + "-journal")
        )
        target = sentinel
    try:
        link.symlink_to(target, target_is_directory=location == "ancestor")
    except OSError as error:
        if os.name == "nt" and error.winerror in {5, 1314}:
            pytest.skip(
                f"Windows symbolic link privilege unavailable (WinError {error.winerror})"
            )
        raise

    if location == "sidecar":
        with pytest.raises(ProviderError, match="audit_unavailable"):
            ModelCallJournal(ledger)
    else:

        def unexpected_resolve(self, *args, **kwargs):
            pytest.fail("A linked ledger path was resolved before it was rejected")

        with monkeypatch.context() as patch:
            patch.setattr(Path, "resolve", unexpected_resolve)
            with pytest.raises(ProviderError, match="audit_unavailable"):
                ModelCallJournal(ledger)
    assert sorted(p.name for p in outside.iterdir()) == [sentinel.name]
    assert sentinel.read_bytes() == b"synthetic untouched file"


def test_windows_junction_is_rejected_on_startup_and_after_construction(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows junction test")
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "data"
    journal = ModelCallJournal(root / "model-audit.sqlite3")
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(root), str(outside)],
        capture_output=True,
        timeout=10,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(
            f"Windows junction creation unavailable (exit {created.returncode})"
        )
    with pytest.raises(ProviderError, match="audit_unavailable"):
        ModelCallJournal(root / ".." / "model-audit.sqlite3")
    with pytest.raises(ProviderError, match="audit_unavailable"):
        journal.records()
    with pytest.raises(ProviderError, match="audit_unavailable"), journal.connect():
        pytest.fail("A junction was accepted by the SQLite open path")
    with (
        pytest.raises(ProviderError, match="audit_unavailable"),
        TestClient(create_app(root)),
    ):
        pytest.fail("The app started using a redirected data root")
    assert list(outside.iterdir()) == []


def test_unlinked_relative_data_path_is_supported(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    backend.mkdir()
    monkeypatch.chdir(backend)
    journal = ModelCallJournal(Path("../data/model-audit.sqlite3"))
    assert journal.path == tmp_path / "data" / "model-audit.sqlite3"
    assert journal.records() == []
    assert not journal.path.parent.exists()
