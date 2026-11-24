import pytest

from sfm_workshop.core import storage


def test_atomic_write_permission_error_is_not_retried(tmp_path, monkeypatch):
    calls = []

    def denied(*args, **kwargs):
        calls.append(args)
        raise PermissionError("controlled folder")

    monkeypatch.setattr(storage.os, "open", denied)
    with pytest.raises(PermissionError):
        storage.atomic_write_text(tmp_path / "session.sfmproj", "{}")
    # tempfile.mkstemp would retry up to TMP_MAX names when os.access() lies
    # about a protected Windows folder; the direct O_EXCL path must not.
    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_atomic_write_round_trip(tmp_path):
    target = tmp_path / "session.sfmproj"
    storage.atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
