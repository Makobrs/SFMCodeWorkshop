"""Tests for the DPAPI credential store (no plaintext secrets on disk)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from sfm_workshop.services import credentials
from sfm_workshop.services.credentials import (
    CredentialError,
    CredentialStore,
    dpapi_available,
)

DPAPI_AVAILABLE = dpapi_available()
requires_dpapi = pytest.mark.skipif(
    not DPAPI_AVAILABLE, reason="Windows DPAPI is not available in this environment"
)

KEY = "sk-sfm-test-0123456789abcdef0123456789abcdef"


def _files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


def _metadata(root: Path) -> dict:
    return json.loads((root / "records.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Save / load / delete / refs
# ---------------------------------------------------------------------------


@requires_dpapi
def test_save_load_delete_roundtrip(tmp_path: Path):
    root = tmp_path / "credentials"
    store = CredentialStore(root)

    assert store.load("deepseek") is None
    assert not store.exists("deepseek")

    store.save("deepseek", KEY)

    assert store.exists("deepseek")
    assert store.load("deepseek") == KEY
    assert store.aliases() == ["deepseek"]
    ref = store.ref_for("deepseek")
    assert ref is not None
    assert re.fullmatch(r"dpapi://[0-9a-f]{32}", ref)
    assert store.alias_for_ref(ref) == "deepseek"
    assert store.load(ref) == KEY

    store.delete("deepseek")

    assert not store.exists("deepseek")
    assert store.load("deepseek") is None
    assert store.ref_for("deepseek") is None
    assert store.aliases() == []
    assert not list(root.glob("*.bin"))
    # deleting twice is safe
    store.delete("deepseek")


@requires_dpapi
def test_bound_alias_store(tmp_path: Path):
    store = CredentialStore(tmp_path / "credentials", alias="deepseek")
    store.save(secret=KEY)
    assert store.load() == KEY
    assert store.ref_for() == store.ref_for("deepseek")
    store.delete()
    assert not store.exists()


@requires_dpapi
@requires_dpapi
def test_ui_positional_alias_uses_default_root(tmp_path: Path, monkeypatch):
    """The UI calls ``CredentialStore("deepseek-default")`` and no-arg methods."""
    credential_root = tmp_path / "credentials"
    monkeypatch.setattr(credentials, "default_root", lambda: credential_root)
    store = CredentialStore("deepseek-default")
    assert store.root == credential_root
    assert store.default_alias == "deepseek-default"

    store.save(KEY)
    assert store.exists()
    assert store.load() == KEY
    assert CredentialStore("deepseek-default").load() == KEY
    store.delete()
    assert not store.exists()


@requires_dpapi
def test_string_directory_with_separator_is_still_a_root(tmp_path: Path):
    root = tmp_path / "credentials"
    store = CredentialStore(str(root))
    assert store.root == root
    assert store.default_alias is None


def test_default_alias_requires_explicit_alias(tmp_path: Path):
    store = CredentialStore(tmp_path / "credentials")
    with pytest.raises(CredentialError):
        store.save(secret=KEY)
    with pytest.raises(CredentialError):
        store.load()


# ---------------------------------------------------------------------------
# No plaintext anywhere
# ---------------------------------------------------------------------------


@requires_dpapi
def test_secret_is_never_plaintext_on_disk(tmp_path: Path):
    root = tmp_path / "credentials"
    store = CredentialStore(root)
    store.save("deepseek", KEY)

    files = _files(root)
    assert files, "credential store should write metadata and a blob"
    for path in files:
        assert KEY.encode("utf-8") not in path.read_bytes(), f"plaintext key found in {path}"

    metadata_text = (root / "records.json").read_text(encoding="utf-8")
    metadata = json.loads(metadata_text)
    assert KEY not in metadata_text
    assert "secret" not in metadata["records"]["deepseek"]

    record = metadata["records"]["deepseek"]
    assert metadata["schema"] == credentials.SCHEMA_VERSION
    assert record["alias"] == "deepseek"
    assert record["version"] == credentials.RECORD_VERSION
    assert record["scheme"] == "dpapi-v1"
    assert record["ref"].startswith("dpapi://")
    assert record["created"]
    assert record["updated"]


@requires_dpapi
def test_refs_are_opaque_and_alias_is_not_in_blob_name(tmp_path: Path):
    root = tmp_path / "credentials"
    store = CredentialStore(root)
    store.save("my-secret-alias", KEY)
    ref = store.ref_for("my-secret-alias")
    assert ref is not None
    blob = root / f"{ref.split('://', 1)[1]}.bin"
    assert blob.is_file()
    assert "my-secret-alias" not in blob.name


# ---------------------------------------------------------------------------
# Tamper / corruption
# ---------------------------------------------------------------------------


@requires_dpapi
def test_tampered_blob_fails_without_leaking_secret(tmp_path: Path):
    root = tmp_path / "credentials"
    store = CredentialStore(root)
    store.save("deepseek", KEY)

    blob = next(root.glob("*.bin"))
    data = bytearray(blob.read_bytes())
    data[len(data) // 2] ^= 0xFF
    blob.write_bytes(data)

    with pytest.raises(CredentialError) as excinfo:
        store.load("deepseek")
    assert KEY not in str(excinfo.value)
    assert "DPAPI" in str(excinfo.value)


@requires_dpapi
def test_swapped_refs_fail_alias_binding(tmp_path: Path):
    root = tmp_path / "credentials"
    store = CredentialStore(root)
    key_a = "sk-a-aaaa-bbbb-cccc-dddd"
    key_b = "sk-b-aaaa-bbbb-cccc-dddd"
    store.save("alias-a", key_a)
    store.save("alias-b", key_b)

    path = root / "records.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    ref_a = metadata["records"]["alias-a"]["ref"]
    metadata["records"]["alias-a"]["ref"] = metadata["records"]["alias-b"]["ref"]
    metadata["records"]["alias-b"]["ref"] = ref_a
    path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(CredentialError) as excinfo:
        store.load("alias-a")
    message = str(excinfo.value)
    assert key_a not in message and key_b not in message


@requires_dpapi
def test_corrupt_metadata_is_reported(tmp_path: Path):
    root = tmp_path / "credentials"
    root.mkdir(parents=True)
    (root / "records.json").write_text("{not json", encoding="utf-8")
    store = CredentialStore(root)
    with pytest.raises(CredentialError):
        store.load("deepseek")


# ---------------------------------------------------------------------------
# Overwrite / versioning
# ---------------------------------------------------------------------------


@requires_dpapi
def test_overwrite_replaces_blob_and_keeps_created(tmp_path: Path):
    root = tmp_path / "credentials"
    store = CredentialStore(root)
    store.save("deepseek", KEY)
    first = store.ref_for("deepseek")
    created = _metadata(root)["records"]["deepseek"]["created"]

    store.save("deepseek", KEY + "-rotated")

    second = store.ref_for("deepseek")
    assert second != first
    assert store.load("deepseek") == KEY + "-rotated"
    assert _metadata(root)["records"]["deepseek"]["created"] == created
    assert len(list(root.glob("*.bin"))) == 1


# ---------------------------------------------------------------------------
# Validation / unavailability
# ---------------------------------------------------------------------------


def test_alias_and_secret_validation(tmp_path: Path):
    root = tmp_path / "credentials"
    store = CredentialStore(root)

    with pytest.raises(CredentialError):
        store.save("", KEY)
    with pytest.raises(CredentialError):
        store.save("bad\nalias", KEY)
    with pytest.raises(CredentialError):
        store.save("x" * 129, KEY)
    with pytest.raises(CredentialError):
        store.save("deepseek", "")
    with pytest.raises(CredentialError):
        store.save("deepseek", "   ")
    with pytest.raises(CredentialError):
        store.save("deepseek", 123)  # type: ignore[arg-type]
    assert not root.exists()


def test_dpapi_unavailable_raises_credential_error(tmp_path: Path, monkeypatch):
    root = tmp_path / "credentials"
    store = CredentialStore(root)
    monkeypatch.setattr(credentials, "dpapi_available", lambda: False)

    with pytest.raises(CredentialError) as excinfo:
        store.save("deepseek", KEY)
    message = str(excinfo.value)
    assert "DPAPI" in message
    assert KEY not in message
    assert not (root / "records.json").exists()
    if root.exists():
        assert not list(root.glob("*.bin"))


def test_default_root_uses_appdata(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    root = credentials.default_root()
    assert root == tmp_path / "SFMCodeWorkshop" / "credentials"
    # Constructing the default store must not create or write anything.
    store = CredentialStore()
    assert store.root == root
    assert not root.exists()
