"""本机凭据存储（Windows DPAPI）。

设计目标
--------
- **secret 绝不明文落盘**：密钥用 Windows DPAPI（``CryptProtectData``）
  以当前 Windows 用户身份加密，只有同一用户在同一台机器上才能解密。
- **版本化 records + 不透明 refs**：``records.json`` 只保存记录元数据
  （alias / ref / created / updated / version / scheme），工程或其他文件
  只需保存 ref（例如 ``dpapi://<32位十六进制>``），不保存 secret。
- **无第三方依赖**：通过 ``ctypes`` 调用 crypt32.dll / kernel32.dll。

目录结构::

    <root>/
        records.json          # 版本化元数据（无 secret）
        <record-id>.bin       # CryptProtectData 输出的二进制密文

用法::

    store = CredentialStore()                 # 默认 %APPDATA%\\SFMCodeWorkshop\\credentials
    store.save("deepseek", user_key)          # 显式 alias
    ref = store.ref_for("deepseek")           # 需要持久化时只保存 ref
    secret = store.load(ref)                  # load 同时接受 alias 或 ref

    # 也可以绑定默认 alias（UI 兼容写法）：
    store = CredentialStore("deepseek-default")
    store.save(user_key)
    store.load()

如果 DPAPI 不可用（非 Windows 或 crypt32 加载失败），需要加密的操作
会抛出 :class:`CredentialError`；调用方（UI）应退回“仅本次会话”模式。
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "CredentialError",
    "CredentialStore",
    "DEFAULT_ALIAS",
    "REF_PREFIX",
    "RECORD_VERSION",
    "SCHEMA_VERSION",
    "default_root",
    "dpapi_available",
]


# Same application directory as core/storage.py; duplicated here so this
# module never has to import the core package (avoids import cycles and keeps
# credential handling independent from project files).
APP_DIR_NAME = "SFMCodeWorkshop"

SCHEMA_VERSION = 1
RECORD_VERSION = 1
REF_PREFIX = "dpapi://"
DEFAULT_ALIAS = "deepseek"
SCHEME = "dpapi-v1"

_ENTROPY_PREFIX = b"SFMCodeWorkshop/ai-credential/v1\x00"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_DESCRIPTION = "SFM Code Workshop AI credential"
_ALIAS_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,128}$")
_REF_RE = re.compile(r"^dpapi://([0-9a-f]{32})$")


class CredentialError(RuntimeError):
    """凭据读写失败。

    错误信息只包含操作/alias/错误码，绝不包含 secret 本身。
    """


# ---------------------------------------------------------------------------
# Windows DPAPI through ctypes
# ---------------------------------------------------------------------------


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _load_dll(name: str) -> Any:
    """Load a Windows DLL; raise CredentialError when unavailable."""
    if sys.platform != "win32":
        raise CredentialError("Windows DPAPI 不可用：当前系统不是 Windows，无法加密保存密钥")
    win_dll = getattr(ctypes, "WinDLL", None)
    if win_dll is None:
        raise CredentialError("Windows DPAPI 不可用：Python ctypes 缺少 WinDLL")
    try:
        return win_dll(name, use_last_error=True)
    except OSError:
        raise CredentialError(f"Windows DPAPI 不可用：无法加载 {name}.dll") from None


def dpapi_available() -> bool:
    """Return True when CryptProtectData/CryptUnprotectData can be used."""
    if sys.platform != "win32":
        return False
    try:
        crypt32 = _load_dll("crypt32")
        kernel32 = _load_dll("kernel32")
        for name in ("CryptProtectData", "CryptUnprotectData"):
            if not hasattr(crypt32, name):
                return False
        return hasattr(kernel32, "LocalFree")
    except CredentialError:
        return False


def _require_dpapi() -> None:
    if not dpapi_available():
        raise CredentialError(
            "Windows DPAPI 不可用，无法加密保存密钥；请使用“仅本次会话”模式或检查系统组件"
        )


def _blob(data: bytes) -> tuple[_DataBlob, Any]:
    # ``create_string_buffer`` with an explicit size avoids an extra NUL byte
    # being included in cbData; keep the buffer alive while DPAPI reads it.
    buffer = ctypes.create_string_buffer(data, len(data) or 1)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def _crypt32() -> Any:
    dll = _load_dll("crypt32")
    protect = dll.CryptProtectData
    protect.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_DataBlob),
    ]
    protect.restype = ctypes.c_int
    unprotect = dll.CryptUnprotectData
    unprotect.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_DataBlob),
    ]
    unprotect.restype = ctypes.c_int
    return dll


def _kernel32() -> Any:
    dll = _load_dll("kernel32")
    dll.LocalFree.argtypes = [ctypes.c_void_p]
    dll.LocalFree.restype = ctypes.c_void_p
    return dll


def _last_error_text(code: int) -> str:
    if not code:
        return ""
    try:
        text = ctypes.FormatError(code).strip()
    except Exception:  # pragma: no cover - defensive; never include secrets
        return ""
    return text


def _dpapi_error(operation: str, code: int) -> CredentialError:
    detail = _last_error_text(code)
    suffix = f"：{detail}" if detail else ""
    return CredentialError(f"DPAPI {operation}失败（错误码 {code}{suffix}），凭据未保存")


def _protect(data: bytes, entropy: bytes) -> bytes:
    """Encrypt ``data`` with user-scoped DPAPI and optional entropy."""
    _require_dpapi()
    crypt32 = _crypt32()
    kernel32 = _kernel32()
    data_in, keep_data = _blob(data)
    entropy_in, keep_entropy = _blob(entropy)
    data_out = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(data_in),
        _DESCRIPTION,
        ctypes.byref(entropy_in),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(data_out),
    )
    if not ok:
        code = ctypes.get_last_error()
        raise _dpapi_error("加密", code)
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        if data_out.pbData:
            kernel32.LocalFree(data_out.pbData)


def _unprotect(data: bytes, entropy: bytes) -> bytes:
    """Decrypt a DPAPI blob; tampered blobs raise CredentialError."""
    _require_dpapi()
    crypt32 = _crypt32()
    kernel32 = _kernel32()
    data_in, keep_data = _blob(data)
    entropy_in, keep_entropy = _blob(entropy)
    data_out = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(data_in),
        None,
        ctypes.byref(entropy_in),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(data_out),
    )
    if not ok:
        code = ctypes.get_last_error()
        raise CredentialError(
            "DPAPI 解密失败：凭据可能已损坏、被篡改，或不属于当前 Windows 用户"
            + (f"（错误码 {code}）" if code else "")
        )
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        if data_out.pbData:
            kernel32.LocalFree(data_out.pbData)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def default_root() -> Path:
    """Default credential directory, aligned with core.storage.user_root()."""
    base = os.environ.get("APPDATA")
    root = Path(base) / APP_DIR_NAME if base else Path.home() / f".{APP_DIR_NAME}"
    return root / "credentials"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _looks_like_alias_value(value: str) -> bool:
    """True when a single positional string should be read as an alias.

    ``CredentialStore("deepseek-default")`` is a convenient alias binding used
    by the UI, while ``CredentialStore("D:\\\\creds")`` or a :class:`Path` is a
    store directory.  Explicit roots with no separators can pass ``Path(...)``
    or the ``root=`` keyword to avoid the ambiguity.
    """
    text = value.strip()
    if not text or text in (".", ".."):
        return False
    if "/" in text or "\\" in text:
        return False
    if re.match(r"^[A-Za-z]:", text):
        return False
    if Path(text).exists():
        return False
    return True


def _validate_alias(alias: Any) -> str:
    if not isinstance(alias, str):
        raise CredentialError("凭据 alias 必须是字符串")
    value = alias.strip()
    if not value:
        raise CredentialError("凭据 alias 不能为空")
    if not _ALIAS_RE.match(value):
        raise CredentialError("凭据 alias 含非法字符或过长（最多 128 个字符）")
    return value


def _validate_secret(secret: Any) -> str:
    if not isinstance(secret, str):
        raise CredentialError("密钥必须是字符串")
    if not secret.strip():
        raise CredentialError("密钥不能为空")
    return secret


def _entropy(alias: str) -> bytes:
    # Binds the ciphertext to the alias/user: a blob copied to another alias
    # cannot be decrypted, which keeps refs from silently crossing records.
    return _ENTROPY_PREFIX + alias.encode("utf-8")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        # The record is already gone; a leftover encrypted blob is not usable.
        return


# ---------------------------------------------------------------------------
# Public store
# ---------------------------------------------------------------------------


class CredentialStore:
    """Versioned record store with DPAPI-encrypted secret blobs.

    Parameters
    ----------
    root:
        Store directory.  Defaults to :func:`default_root` (per-user APPDATA).
        Tests and portable runs should always pass an explicit directory.
        For UI convenience, a single positional string that looks like an alias
        and is not an existing path (e.g. ``"deepseek-default"``) is treated as
        the default alias instead; use :class:`Path` for relative roots.
    alias:
        Optional default alias so ``save(secret=...)`` can omit the alias.
    """

    def __init__(self, root: str | Path | None = None, alias: str | None = None) -> None:
        if alias is None and isinstance(root, str) and _looks_like_alias_value(root):
            root, alias = None, root
        self.root = Path(root) if root is not None else default_root()
        self.default_alias: str | None = _validate_alias(alias) if alias is not None else None

    # -- paths ---------------------------------------------------------
    @property
    def metadata_path(self) -> Path:
        return self.root / "records.json"

    def blob_path(self, ref: str) -> Path:
        match = _REF_RE.match(ref)
        if not match:
            raise CredentialError("凭据引用格式无效")
        return self.root / f"{match.group(1)}.bin"

    # -- metadata ------------------------------------------------------
    def _empty_records(self) -> dict[str, Any]:
        return {"schema": SCHEMA_VERSION, "records": {}}

    def _read_records(self) -> dict[str, Any]:
        path = self.metadata_path
        if not path.exists():
            return self._empty_records()
        try:
            raw = path.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
        except Exception:
            raise CredentialError("凭据索引损坏，无法读取；请清除后重新保存密钥") from None
        if not isinstance(data, dict):
            raise CredentialError("凭据索引格式无效")
        try:
            schema = int(data.get("schema") or SCHEMA_VERSION)
        except (TypeError, ValueError):
            schema = SCHEMA_VERSION
        if schema > SCHEMA_VERSION:
            raise CredentialError("凭据索引版本高于当前应用支持的版本，请升级应用")
        records = data.get("records")
        if not isinstance(records, dict):
            records = {}
        data["schema"] = schema
        data["records"] = records
        return data

    def _write_records(self, data: dict[str, Any]) -> None:
        text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        try:
            _atomic_write_bytes(self.metadata_path, text.encode("utf-8"))
        except OSError:
            raise CredentialError("凭据索引写入失败，密钥未保存") from None

    def _record(self, alias: str) -> dict[str, Any] | None:
        record = self._read_records()["records"].get(alias)
        return record if isinstance(record, dict) else None

    def _resolve(self, alias_or_ref: Any) -> tuple[str | None, dict[str, Any] | None]:
        value = alias_or_ref if alias_or_ref is not None else self.default_alias
        if value is None:
            raise CredentialError("未指定凭据 alias 或 ref")
        if not isinstance(value, str):
            raise CredentialError("凭据 alias/ref 必须是字符串")
        value = value.strip()
        if value.startswith(REF_PREFIX):
            records = self._read_records()["records"]
            for alias, record in records.items():
                if isinstance(record, dict) and record.get("ref") == value:
                    return str(alias), record
            return None, None
        alias = _validate_alias(value)
        return alias, self._record(alias)

    def _record_ref(self, record: dict[str, Any]) -> str:
        ref = record.get("ref")
        if not isinstance(ref, str):
            raise CredentialError("凭据记录缺少有效 ref")
        self.blob_path(ref)  # validates format
        return ref

    def _check_record_version(self, record: dict[str, Any]) -> None:
        try:
            version = int(record.get("version") or RECORD_VERSION)
        except (TypeError, ValueError):
            raise CredentialError("凭据记录版本无效") from None
        if version > RECORD_VERSION:
            raise CredentialError("凭据记录版本高于当前应用支持的版本，请升级应用")
        scheme = record.get("scheme")
        if scheme not in (None, SCHEME):
            raise CredentialError("不支持的凭据加密方案")

    # -- public API ----------------------------------------------------
    def save(self, alias: str | None = None, secret: str | None = None) -> None:
        """Encrypt and save ``secret`` under ``alias``.

        Accepts both ``store.save("alias", secret)`` and, when the store was
        constructed with a default alias, ``store.save(secret)`` or
        ``store.save(secret=secret)``.  Overwrites an existing record for the
        same alias.  No plaintext is written to disk and no secret is ever
        added to ``records.json``.
        """
        if secret is None and self.default_alias is not None and alias is not None:
            # Bound store + one positional argument: that argument is the key.
            alias, secret = None, alias
        target = self._resolve_alias(alias)
        value = _validate_secret(secret)
        records = self._read_records()
        existing = records["records"].get(target)
        existing = existing if isinstance(existing, dict) else None
        old_ref = existing.get("ref") if existing else None

        record_id = uuid.uuid4().hex
        ref = f"{REF_PREFIX}{record_id}"
        payload = json.dumps(
            {"v": RECORD_VERSION, "alias": target, "secret": value},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        encrypted = _protect(payload, _entropy(target))
        path = self.root / f"{record_id}.bin"

        try:
            _atomic_write_bytes(path, encrypted)
        except OSError:
            raise CredentialError("加密凭据写入磁盘失败，密钥未保存") from None

        now = _now_iso()
        created = ""
        if existing and isinstance(existing.get("created"), str):
            created = existing["created"]
        records["records"][target] = {
            "alias": target,
            "ref": ref,
            "created": created or now,
            "updated": now,
            "version": RECORD_VERSION,
            "scheme": SCHEME,
        }
        try:
            self._write_records(records)
        except CredentialError:
            _unlink_quiet(path)
            raise
        if isinstance(old_ref, str) and old_ref != ref:
            try:
                _unlink_quiet(self.blob_path(old_ref))
            except CredentialError:
                pass

    def load(self, alias: str | None = None) -> str | None:
        """Return the secret for ``alias``/``ref``; None when not configured."""
        target, record = self._resolve(alias)
        if target is None or record is None:
            return None
        self._check_record_version(record)
        ref = self._record_ref(record)
        path = self.blob_path(ref)
        try:
            encrypted = path.read_bytes()
        except FileNotFoundError:
            raise CredentialError("凭据密文文件缺失；请重新保存密钥") from None
        except OSError:
            raise CredentialError("凭据密文文件无法读取") from None
        plaintext = _unprotect(encrypted, _entropy(target))
        try:
            payload = json.loads(plaintext.decode("utf-8"))
        except Exception:
            raise CredentialError("凭据内容已损坏") from None
        if not isinstance(payload, dict):
            raise CredentialError("凭据内容已损坏")
        try:
            payload_version = int(payload.get("v") or 0)
        except (TypeError, ValueError):
            raise CredentialError("凭据内容已损坏") from None
        if payload_version > RECORD_VERSION:
            raise CredentialError("凭据内容版本高于当前应用支持的版本")
        if payload.get("alias") != target:
            raise CredentialError("凭据引用与内容不匹配")
        secret = payload.get("secret")
        if not isinstance(secret, str) or not secret:
            raise CredentialError("凭据内容已损坏")
        return secret

    def delete(self, alias: str | None = None) -> None:
        """Delete the record and its encrypted blob; safe to call twice."""
        target, record = self._resolve(alias)
        if target is None or record is None:
            return
        records = self._read_records()
        records["records"].pop(target, None)
        self._write_records(records)
        try:
            ref = self._record_ref(record)
        except CredentialError:
            return
        _unlink_quiet(self.blob_path(ref))

    def exists(self, alias: str | None = None) -> bool:
        """True when a record and its encrypted blob are present."""
        target, record = self._resolve(alias)
        if target is None or record is None:
            return False
        try:
            ref = self._record_ref(record)
        except CredentialError:
            return False
        return self.blob_path(ref).is_file()

    # -- refs ----------------------------------------------------------
    def ref_for(self, alias: str | None = None) -> str | None:
        """Return the opaque ref for ``alias`` (None when not saved)."""
        target = self._resolve_alias(alias)
        record = self._record(target)
        if record is None:
            return None
        return self._record_ref(record)

    def alias_for_ref(self, ref: str) -> str | None:
        """Resolve an opaque ref back to its alias."""
        if not isinstance(ref, str):
            return None
        records = self._read_records()["records"]
        for alias, record in records.items():
            if isinstance(record, dict) and record.get("ref") == ref:
                return str(alias)
        return None

    def aliases(self) -> list[str]:
        """Sorted aliases with a metadata record."""
        return sorted(str(alias) for alias in self._read_records()["records"].keys())

    # -- internals -----------------------------------------------------
    def _resolve_alias(self, alias: str | None) -> str:
        value = alias if alias is not None else self.default_alias
        if value is None:
            raise CredentialError("未指定凭据 alias")
        return _validate_alias(value)
