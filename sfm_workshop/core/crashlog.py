"""Runtime logs, fatal-signal capture and unclean-shutdown detection.

The packaged app is built with ``console=False``, so Qt and Python otherwise
lose every diagnostic message.  This module keeps a small, user-readable log
directory under the app data root and leaves a marker while a session is
running.  A marker that survives to the next launch means the previous run did
not close normally; the UI can then show the exact log paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import faulthandler
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import sys
import threading
import traceback
from typing import Any

from .storage import APP_DIR_NAME, user_root


@dataclass(frozen=True)
class CrashInfo:
    previous_started: str
    runtime_log: str
    faulthandler_log: str
    crash_log: str
    logs_dir: str
    marker: str


_logger = logging.getLogger("sfm_workshop")
_log_handle = None
_installed = False
_current: CrashInfo | None = None
_crash_recorded = False


def logs_dir() -> Path:
    d = user_root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def runtime_log_path() -> Path:
    return logs_dir() / "runtime.log"


def faulthandler_log_path() -> Path:
    return logs_dir() / "faulthandler.log"


def marker_path() -> Path:
    return logs_dir() / "session.json"


def latest_crash_log() -> Path:
    try:
        files = sorted(logs_dir().glob("crash-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    except Exception:
        pass
    return logs_dir() / "crash.log"


def _environment() -> str:
    return "\n".join(
        [
            f"time={datetime.now().isoformat(timespec='seconds')}",
            f"python={sys.version}",
            f"executable={sys.executable}",
            f"frozen={getattr(sys, 'frozen', False)}",
            f"platform={platform.platform()}",
            f"pid={os.getpid()}",
            f"cwd={os.getcwd()}",
            f"appdata={os.environ.get('APPDATA', '')}",
            f"argv={sys.argv!r}",
        ]
    )


def _read_previous() -> tuple[dict[str, Any] | None, bool]:
    path = marker_path()
    if not path.exists():
        return None, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None, True
        # A marker is only removed on a clean exit. Do not use the PID as a
        # liveness test here: Windows reuses PIDs, and a false "still alive"
        # result would hide exactly the crash this feature exists to report.
        return data, True
    except Exception:
        return None, True


def _process_creation_time(pid: int) -> int | None:
    """Windows process creation FILETIME, used to distinguish PID reuse."""
    if pid <= 0 or os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        kernel32.CloseHandle(handle)
        if not ok:
            return None
        return (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _same_running_process(data: dict[str, Any]) -> bool:
    try:
        pid = int(data.get("pid") or 0)
        if not _pid_alive(pid):
            return False
        previous_start = int(data.get("proc_start") or 0)
        current_start = _process_creation_time(pid)
        # Old markers without creation time are intentionally treated as
        # stale; a PID alone is not proof that the process is still alive.
        return bool(previous_start and current_start and previous_start == current_start)
    except Exception:
        return False


def install() -> CrashInfo | None:
    """Install file logs and fatal handlers. Safe to call once."""
    global _installed, _current, _log_handle
    if _installed:
        return _current
    _installed = True
    try:
        folder = logs_dir()
        previous, unclean = _read_previous()
        same_alive = bool(previous and unclean and _same_running_process(previous))
        if same_alive:
            # A second window must not report the first live window as a
            # crash, and must not overwrite its marker.
            unclean = False
        runtime = runtime_log_path()
        fatal = faulthandler_log_path()
        if _log_handle is None or Path(getattr(_log_handle, "name", "")) != fatal:
            if _log_handle is not None:
                try:
                    _log_handle.close()
                except Exception:
                    pass
            _log_handle = open(fatal, "a", encoding="utf-8")
            faulthandler.enable(file=_log_handle, all_threads=True)
        handler = RotatingFileHandler(
            runtime, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s")
        )
        _logger.setLevel(logging.INFO)
        _logger.handlers[:] = [handler]
        _logger.propagate = False
        _logger.info("=" * 72)
        _logger.info("startup\n%s", _environment())
        sys.excepthook = _exception_hook
        threading.excepthook = _thread_exception_hook
        if unclean:
            started = str((previous or {}).get("started", "未知"))
            info = CrashInfo(
                previous_started=started,
                runtime_log=str(runtime),
                faulthandler_log=str(fatal),
                crash_log=str(latest_crash_log()),
                logs_dir=str(folder),
                marker=str(marker_path()),
            )
            _current = info
            _logger.warning("previous session did not close cleanly; started=%s", started)
        else:
            _current = None
        marker = marker_path()
        if same_alive:
            _logger.info("another running instance owns the crash marker; leaving it untouched")
            return _current
        marker.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "proc_start": _process_creation_time(os.getpid()) or 0,
                    "started": datetime.now().isoformat(timespec="seconds"),
                    "frozen": bool(getattr(sys, "frozen", False)),
                    "argv": sys.argv,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return _current
    except Exception:
        # Logging must never prevent the app from starting.
        return None


def _exception_hook(exc_type, exc_value, exc_tb) -> None:
    global _crash_recorded
    _crash_recorded = True
    try:
        _logger.error(
            "unhandled exception\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        crash = logs_dir() / f"crash-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        with open(crash, "a", encoding="utf-8") as fh:
            fh.write(_environment() + "\n\n")
            fh.write("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        _logger.error("crash report written: %s", crash)
    except Exception:
        pass
    try:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    except Exception:
        pass


def _thread_exception_hook(args) -> None:
    global _crash_recorded
    _crash_recorded = True
    try:
        _logger.error(
            "unhandled thread exception in %s\n%s",
            getattr(args.thread, "name", "?"),
            "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
        )
    except Exception:
        pass


def mark_clean_exit() -> None:
    try:
        if _crash_recorded:
            _logger.warning("clean exit suppressed: a crash was recorded")
            return
        marker = marker_path()
        if marker.exists():
            try:
                data = json.loads(marker.read_text(encoding="utf-8"))
                owner = int(data.get("pid") or 0)
                owner_start = int(data.get("proc_start") or 0)
                my_start = _process_creation_time(os.getpid()) or 0
                if owner and owner != os.getpid():
                    _logger.info("clean exit leaves another instance's marker untouched")
                    return
                if owner_start and my_start and owner_start != my_start:
                    _logger.info("clean exit leaves a recycled-PID marker untouched")
                    return
            except Exception:
                pass
        marker.unlink(missing_ok=True)
        _logger.info("clean exit")
    except Exception:
        pass


def log_event(message: str) -> None:
    try:
        _logger.info(message)
    except Exception:
        pass


def report_startup_failure() -> None:
    global _crash_recorded
    _crash_recorded = True
    try:
        text = traceback.format_exc()
        path = logs_dir() / "startup-failure.log"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(_environment() + "\n\n" + text + "\n")
        _logger.error("startup failure\n%s", text)
    except Exception:
        pass


def show_startup_failure() -> None:
    """Best-effort Windows message box for failures after Qt failed to start."""
    try:
        message = (
            "SFM 代码生成工坊启动失败。\n\n"
            "运行日志和崩溃信息已写入：\n"
            f"{logs_dir()}\n\n"
            "请把该目录中的 runtime.log / faulthandler.log 发给开发者。"
        )
        if os.name == "nt":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, message, "SFM 代码生成工坊 / 启动失败", 0x10
            )
        else:
            print(message, file=sys.stderr)
    except Exception:
        pass


def crash_info() -> CrashInfo | None:
    return _current


def qt_message_handler(mode, context, message) -> None:  # noqa: ANN001
    try:
        level = {
            0: logging.DEBUG,
            1: logging.INFO,
            2: logging.WARNING,
            3: logging.CRITICAL,
        }.get(int(mode), logging.INFO)
        _logger.log(level, "Qt: %s", message)
    except Exception:
        pass
