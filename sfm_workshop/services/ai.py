"""AI 代码生成服务（DeepSeek 官方 API 形状 / OpenAI chat-completions）。

本模块只负责“生成候选 + 解析 + 失败分类”，**不修改工程、不覆盖代码**：
调用方拿到 :class:`AIResult` 后自行展示候选，并在用户确认后应用。

协议
----
DeepSeek 官方 API 的 ``POST <base_url>/chat/completions``，请求/响应为
OpenAI 形状的 JSON。只使用标准库 ``urllib``，无外部依赖；``transport``
可注入，测试与离线环境不会访问网络。

安全
----
- 用户 key 只出现在本次 HTTP 请求的 ``Authorization`` 头中；
  本模块不写日志、不把 key 写入 :class:`AIResult`、错误信息或 ``repr``。
- 未启用（``AISettings.enabled=False``）、没有 key、协议不支持、地址/请求非法时，
  **不会发起请求**。应用层的“AI 生成默认关闭”由独立入口控制：只有用户打开
  AI 窗口并点击生成时才构造 settings/发起调用；``enabled=False`` 是额外的硬开关。
- 失败时返回 :class:`AIResult`（不抛异常），当前代码由调用方保持不变。

状态值（``AIResult.status``）供 UI 分支使用::

    ok                   成功；code 非空
    needs_input          模型表示缺少关键信息；missing_info 非空、code 为空
    disabled             AI 功能被显式禁用（AISettings.enabled=False）
    missing_key          未配置密钥
    unsupported_protocol 不支持的协议
    invalid_request      请求参数/用户需求为空
    config_error         接口地址、模型等设置无效
    auth_error           HTTP 401/403
    timeout              超时
    network_error        无法连接/网络错误
    rate_limited         HTTP 429（重试用尽）
    server_error         HTTP 5xx（重试用尽）或服务端 error
    http_error           其他 HTTP 错误（含被拒绝的重定向）
    invalid_response     HTTP 200 但 JSON/结构无效，或返回内容无法解析
    empty_response       模型返回空内容
    truncated            返回被截断（finish_reason == "length" 或结构不完整）
    invalid_sfml         候选未通过 SFML L0 语法检查/不像 SFML
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

__all__ = [
    "AIResult",
    "AISettings",
    "AIClient",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_PROTOCOL",
    "DEFAULT_PROMPT",
    "DEFAULT_PROMPT_HASH",
    "DEFAULT_PROMPT_VERSION",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_OUTPUT",
    "DEFAULT_RETRIES",
    "HttpRequest",
    "HttpResponse",
    "PromptManager",
    "STATUS_OK",
    "STATUS_NEEDS_INPUT",
    "STATUS_DISABLED",
    "STATUS_MISSING_KEY",
    "STATUS_UNSUPPORTED_PROTOCOL",
    "STATUS_INVALID_REQUEST",
    "STATUS_CONFIG_ERROR",
    "STATUS_AUTH_ERROR",
    "STATUS_TIMEOUT",
    "STATUS_NETWORK_ERROR",
    "STATUS_RATE_LIMITED",
    "STATUS_SERVER_ERROR",
    "STATUS_HTTP_ERROR",
    "STATUS_INVALID_RESPONSE",
    "STATUS_EMPTY_RESPONSE",
    "STATUS_TRUNCATED",
    "STATUS_INVALID_SFML",
    "SUPPORTED_PROTOCOLS",
    "TransportNetworkError",
    "TransportTimeout",
    "chat_completions_url",
    "default_prompt_hash",
    "render_prompt",
    "urllib_transport",
]


# ---------------------------------------------------------------------------
# Prompt (PRD-新增需求-v1.1 §2.5, verbatim; placeholders are filled by app)
# ---------------------------------------------------------------------------

DEFAULT_PROMPT_VERSION = 1

DEFAULT_PROMPT = """你是「SFM代码生成工坊」的 SFML 代码生成与自审助手。你的唯一任务是：在给定 Minecraft/SFM 版本、工程上下文和用户需求下，生成可被 SFM 4.34.0 编译的 SFML 程序，并在输出前按规范自审。

【固定事实】
- 目标：SFM 4.34.0；Minecraft 版本/加载器：{{profile}}。
- 只能使用上下文中已声明的标签与资源；不得编造标签、方块、物品、流体、化学品或世界状态。
- 不生成 NBT/组件谓词（4.34 不支持）。
- 程序长度上限 32,367 字符；标签名 ≤256；资源 ID 1–4 段；普通 timer ≥20 tick；纯能量 timer 1 tick。
- 面：默认面不写 side；每个面写 each side；具体面写 top/bottom/north/south/east/west side。
- 只生成 SFML；不要 Markdown 代码围栏、解释、前言或后记。

【输入】
- 工程上下文：{{context_json}}
- 用户需求：{{user_requirement}}

【生成规则】
1. 如果缺少关键信息（源/目标标签、面、数量/过滤、触发器等），不要猜测；在 missing_info 中列出，不要生成假代码。
2. 优先使用现有标签；标签名按上下文原样使用。
3. 结构：EVERY ... DO ... END；INPUT 在 OUTPUT 前；需要时 FORGET；条件按 SFM 语法。
4. 保持最小、可读、确定；不写随机/时间戳/UI 布局注释。
5. 不使用未在上下文中出现的资源 ID 或标签；不生成 NBT。

【自审（必须执行）】
在输出前逐项检查：括号/END 配对；标签存在；面合法；数量/保留/过滤合法；资源 ID 格式；timer 阈值；程序长度；无 NBT；OUTPUT 前有 INPUT；FORGET 语义；IF/条件语法；不要输出未自审的草稿。

【输出格式】
只输出一个 JSON 对象，不要 Markdown：
{
  "code": "完整 SFML 代码；若 missing_info 非空可为空字符串",
  "self_review": ["逐条自审结果"],
  "assumptions": ["必须说明的假设；没有则空数组"],
  "missing_info": ["缺失的关键信息；没有则空数组"]
}"""


def default_prompt_hash() -> str:
    """SHA-256 of the built-in default prompt (for version/hash checks)."""
    return hashlib.sha256(DEFAULT_PROMPT.encode("utf-8")).hexdigest()


DEFAULT_PROMPT_HASH = default_prompt_hash()


def render_prompt(
    prompt: str,
    profile: str,
    context_json: str,
    user_requirement: str,
) -> str:
    """Fill the three documented placeholders; do not use ``str.format``."""
    return (
        str(prompt)
        .replace("{{profile}}", str(profile))
        .replace("{{context_json}}", str(context_json))
        .replace("{{user_requirement}}", str(user_requirement))
    )


class PromptManager:
    """Read-only built-in prompt + optional user override.

    The built-in prompt is never mutated.  ``set_override`` stores the user's
    text in memory (the UI persists it in app settings); ``reset`` restores the
    exact built-in text.  An override identical to the built-in prompt is
    treated as “no override”.
    """

    def __init__(self, override: str = "", *, version: int = DEFAULT_PROMPT_VERSION) -> None:
        self.version = int(version or DEFAULT_PROMPT_VERSION)
        self._override = ""
        self.set_override(override)

    @property
    def default_text(self) -> str:
        return DEFAULT_PROMPT

    @property
    def default_hash(self) -> str:
        return DEFAULT_PROMPT_HASH

    @property
    def override(self) -> str:
        return self._override

    @property
    def is_default(self) -> bool:
        return not self._override

    def get_override(self) -> str:
        return self._override

    def set_override(self, text: str | None) -> None:
        if text is None:
            self._override = ""
            return
        if not isinstance(text, str):
            raise TypeError("提示词覆盖必须是字符串")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip() or text == DEFAULT_PROMPT:
            self._override = ""
            return
        self._override = text

    def reset(self) -> None:
        self._override = ""

    def effective_prompt(self) -> str:
        return self._override or DEFAULT_PROMPT

    def render(self, profile: str, context_json: str, user_requirement: str) -> str:
        return render_prompt(self.effective_prompt(), profile, context_json, user_requirement)

    @classmethod
    def from_app_settings(cls, app_settings: Any) -> "PromptManager":
        """Build from ``core.storage.AppSettings`` without importing it."""
        try:
            version = int(getattr(app_settings, "ai_prompt_version", DEFAULT_PROMPT_VERSION) or 1)
        except (TypeError, ValueError):
            version = DEFAULT_PROMPT_VERSION
        return cls(
            getattr(app_settings, "prompt_override", "") or "",
            version=version,
        )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_PROTOCOL = "DeepSeek 官方 API"
DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRIES = 2
DEFAULT_MAX_OUTPUT = 4096
DEFAULT_TEMPERATURE = 0.2

# Accepted labels for the same official DeepSeek protocol; anything else is
# rejected explicitly instead of silently mixing protocols.
SUPPORTED_PROTOCOLS: tuple[str, ...] = (
    "DeepSeek 官方 API",
    "DeepSeek 官方第三方 API",
    "DeepSeek 官方 API 协议",
    "DeepSeek 官方第三方 API 协议",
    "deepseek",
    "deepseek api",
)

MAX_RETRIES = 5
MAX_TIMEOUT = 600.0
MAX_OUTPUT_TOKENS = 32768
MAX_PROMPT_CHARS = 200_000


def is_supported_protocol(protocol: str) -> bool:
    value = (protocol or "").strip()
    return value in SUPPORTED_PROTOCOLS or value.lower() in {
        item.lower() for item in SUPPORTED_PROTOCOLS
    }


def chat_completions_url(base_url: str) -> str:
    """Return the chat-completions endpoint for a user-supplied base URL."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("接口地址为空")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _validate_endpoint(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError("接口地址必须以 http:// 或 https:// 开头")
    if not parts.hostname:
        raise ValueError("接口地址缺少主机名")
    if parts.username or parts.password:
        raise ValueError("接口地址不能包含用户名或密码")
    if parts.query or parts.fragment:
        raise ValueError("接口地址不能包含查询参数或片段")
    host = (parts.hostname or "").lower()
    local = host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost")
    if parts.scheme == "http" and not local:
        raise ValueError("为保护密钥，远程接口地址必须使用 HTTPS（本机地址除外）")


@dataclass
class AISettings:
    """User-editable AI service settings.  Never contains a secret key.

    ``enabled`` defaults to True because the application already keeps AI
    behind its independent, default-closed entry; callers that need a hard
    local kill switch can set ``enabled=False`` (no request is then sent).
    """

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    protocol: str = DEFAULT_PROTOCOL
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    max_output: int = DEFAULT_MAX_OUTPUT
    enabled: bool = True
    temperature: float = DEFAULT_TEMPERATURE

    def __post_init__(self) -> None:
        self.base_url = str(self.base_url or "").strip()
        self.model = str(self.model or "").strip()
        self.protocol = str(self.protocol or "").strip()
        try:
            self.timeout = float(self.timeout)
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT
        if not (0 < self.timeout <= MAX_TIMEOUT):
            self.timeout = DEFAULT_TIMEOUT
        try:
            self.retries = int(self.retries)
        except (TypeError, ValueError):
            self.retries = DEFAULT_RETRIES
        self.retries = min(MAX_RETRIES, max(0, self.retries))
        try:
            self.max_output = int(self.max_output)
        except (TypeError, ValueError):
            self.max_output = DEFAULT_MAX_OUTPUT
        self.max_output = min(MAX_OUTPUT_TOKENS, max(1, self.max_output))
        try:
            self.temperature = float(self.temperature)
        except (TypeError, ValueError):
            self.temperature = DEFAULT_TEMPERATURE
        if not (0.0 <= self.temperature <= 2.0):
            self.temperature = DEFAULT_TEMPERATURE
        self.enabled = bool(self.enabled)

    @property
    def endpoint(self) -> str:
        return chat_completions_url(self.base_url)

    @classmethod
    def from_app_settings(cls, app_settings: Any) -> "AISettings":
        """Map ``core.storage.AppSettings.ai_*`` fields (duck-typed)."""

        def pick(*names: str, default: Any) -> Any:
            for name in names:
                if hasattr(app_settings, name):
                    value = getattr(app_settings, name)
                    if value is not None and value != "":
                        return value
            return default

        return cls(
            base_url=pick("ai_base_url", "base_url", default=DEFAULT_BASE_URL),
            model=pick("ai_model", "model", default=DEFAULT_MODEL),
            protocol=pick("ai_protocol", "protocol", default=DEFAULT_PROTOCOL),
            timeout=pick("ai_timeout", "timeout", default=DEFAULT_TIMEOUT),
            retries=pick("ai_retries", "retries", default=DEFAULT_RETRIES),
            max_output=pick("ai_max_output", "max_output", default=DEFAULT_MAX_OUTPUT),
            enabled=bool(getattr(app_settings, "ai_enabled", False)),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "AISettings":
        if not isinstance(data, Mapping):
            return cls()
        aliases = {
            "ai_base_url": "base_url",
            "ai_model": "model",
            "ai_protocol": "protocol",
            "ai_timeout": "timeout",
            "ai_retries": "retries",
            "ai_max_output": "max_output",
            "ai_enabled": "enabled",
        }
        fields = set(cls.__dataclass_fields__)
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            name = aliases.get(key, key)
            if name in fields:
                kwargs[name] = value
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "protocol": self.protocol,
            "timeout": self.timeout,
            "retries": self.retries,
            "max_output": self.max_output,
            "enabled": self.enabled,
            "temperature": self.temperature,
        }


# ---------------------------------------------------------------------------
# Result & transport types
# ---------------------------------------------------------------------------

STATUS_OK = "ok"
STATUS_NEEDS_INPUT = "needs_input"
STATUS_DISABLED = "disabled"
STATUS_MISSING_KEY = "missing_key"
STATUS_UNSUPPORTED_PROTOCOL = "unsupported_protocol"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_CONFIG_ERROR = "config_error"
STATUS_AUTH_ERROR = "auth_error"
STATUS_TIMEOUT = "timeout"
STATUS_NETWORK_ERROR = "network_error"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_SERVER_ERROR = "server_error"
STATUS_HTTP_ERROR = "http_error"
STATUS_INVALID_RESPONSE = "invalid_response"
STATUS_EMPTY_RESPONSE = "empty_response"
STATUS_TRUNCATED = "truncated"
STATUS_INVALID_SFML = "invalid_sfml"


@dataclass
class AIResult:
    """One generation attempt.  Never overwrites project code by itself."""

    code: str = ""
    raw: str = ""
    self_review: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    status: str = STATUS_INVALID_RESPONSE
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and bool(self.code.strip())

    @property
    def needs_input(self) -> bool:
        return self.status == STATUS_NEEDS_INPUT

    @property
    def has_code(self) -> bool:
        return bool(self.code.strip())


@dataclass(frozen=True)
class HttpRequest:
    url: str
    method: str
    headers: dict[str, str]
    body: bytes
    timeout: float

    def __repr__(self) -> str:  # never show Authorization in logs/tracebacks
        masked = {
            key: ("[REDACTED]" if key.lower() == "authorization" else value)
            for key, value in self.headers.items()
        }
        return (
            f"HttpRequest(url={self.url!r}, method={self.method!r}, "
            f"headers={masked!r}, timeout={self.timeout!r})"
        )

    __str__ = __repr__


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes | str = b""
    headers: dict[str, str] = field(default_factory=dict)


class TransportTimeout(TimeoutError):
    """Raised by a transport when the request times out."""


class TransportNetworkError(OSError):
    """Raised by a transport when no HTTP response can be obtained."""


Transport = Callable[[HttpRequest], HttpResponse | tuple[int, bytes | str]]


# ---------------------------------------------------------------------------
# Default urllib transport (no third-party deps)
# ---------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the key is never sent to a different host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


def urllib_transport(request: HttpRequest) -> HttpResponse:
    """Perform one HTTP request with urllib; map errors to typed exceptions."""
    req = urllib.request.Request(
        request.url,
        data=request.body,
        headers=dict(request.headers),
        method=request.method or "POST",
    )
    opener = urllib.request.build_opener(
        _NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    try:
        with opener.open(req, timeout=request.timeout) as response:
            return HttpResponse(
                status=int(response.getcode() or 0),
                body=response.read(),
                headers={str(k): str(v) for k, v in response.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:  # pragma: no cover - defensive
            body = b""
        return HttpResponse(
            status=int(exc.code or 0),
            body=body,
            headers={str(k): str(v) for k, v in (exc.headers or {}).items()},
        )
    except (TimeoutError, socket.timeout):
        raise TransportTimeout("请求超时") from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise TransportTimeout("请求超时") from None
        raise TransportNetworkError("网络错误") from None
    except ssl.SSLError:
        raise TransportNetworkError("TLS 连接失败") from None
    except OSError:
        raise TransportNetworkError("网络错误") from None


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(
    r"```[ \t]*(?P<lang>[A-Za-z0-9_+.-]*)[ \t]*\r?\n(?P<body>.*?)```",
    re.DOTALL,
)
_SFML_LINE_RE = re.compile(r"(?m)^[ \t]*(?:NAME|EVERY)\b")
_SFML_WORD_RE = re.compile(r"\b(?:INPUT|OUTPUT|FORGET)\b")


@dataclass
class _ParsedContent:
    kind: str
    code: str = ""
    self_review: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    missing_info: list[str] = field(default_factory=list)
    error: str = ""


def _sanitize(text: Any, key: str) -> str:
    """Defensively remove the user's key from any text shown to the user."""
    value = "" if text is None else str(text)
    secrets = {key, key.strip()}
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    return value


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            if item is None:
                continue
            text = item.strip() if isinstance(item, str) else str(item).strip()
            if text:
                result.append(text)
        return result
    return []


def _looks_like_sfml(text: str) -> bool:
    value = text.lstrip("\ufeff").strip()
    if not value:
        return False
    return bool(_SFML_LINE_RE.search(value)) or bool(_SFML_WORD_RE.search(value))


def _sfml_syntax_errors(code: str) -> list[str]:
    """L0 syntax check using the bundled 4.34 grammar (optional)."""
    if not code.strip():
        return []
    try:
        from sfm_workshop.grammar import parse_sfml
    except Exception:
        return []
    try:
        return [str(item) for item in parse_sfml(code)]
    except Exception:
        # Parser infrastructure failure is not a model-output error; let the
        # UI's normal validation path report it.
        return []


def _looks_truncated(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return False
    if stripped.count("```") % 2 == 1:
        return True
    if stripped.startswith("{") and stripped.count("{") > stripped.count("}"):
        return True
    return False


def _try_json_object(text: str) -> dict[str, Any] | None:
    candidates = [text.strip()]
    for match in _FENCE_RE.finditer(text):
        lang = (match.group("lang") or "").lower()
        body = match.group("body").strip()
        if lang in ("", "json", "json5") or body.startswith("{"):
            candidates.append(body)
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1].strip())

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            value = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _extract_fenced_code(text: str) -> str:
    for match in _FENCE_RE.finditer(text):
        lang = (match.group("lang") or "").lower()
        body = match.group("body").strip("\r\n")
        if not body.strip():
            continue
        if lang in ("json", "json5"):
            continue
        if lang in ("", "sfm", "sfml", "text", "plaintext") and _looks_like_sfml(body):
            return body.strip()
    for match in _FENCE_RE.finditer(text):
        body = match.group("body").strip("\r\n")
        if body.strip() and _looks_like_sfml(body):
            return body.strip()
    return ""


def _extract_bare_code(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    # Unclosed fence (truncated model output): keep whatever follows it.
    if stripped.startswith("```"):
        body = re.sub(r"^```[A-Za-z0-9_+.-]*[ \t]*\r?\n?", "", stripped)
        body = body.rsplit("```", 1)[0].strip()
        if _looks_like_sfml(body):
            return body
    if not stripped.startswith("{") and _looks_like_sfml(stripped):
        return stripped
    match = _SFML_LINE_RE.search(text)
    if match:
        candidate = text[match.start() :].strip()
        candidate = candidate.split("```", 1)[0].strip()
        if _looks_like_sfml(candidate):
            return candidate
    return ""


def _parse_content(text: str) -> _ParsedContent | None:
    data = _try_json_object(text)
    if data is not None and any(
        key in data for key in ("code", "self_review", "assumptions", "missing_info", "error")
    ):
        code = data.get("code")
        error = data.get("error")
        return _ParsedContent(
            kind="json",
            code=code if isinstance(code, str) else "",
            self_review=_as_text_list(data.get("self_review")),
            assumptions=_as_text_list(data.get("assumptions")),
            missing_info=_as_text_list(data.get("missing_info")),
            error=error.strip() if isinstance(error, str) else "",
        )
    fenced = _extract_fenced_code(text)
    if fenced:
        return _ParsedContent(kind="fenced", code=fenced)
    bare = _extract_bare_code(text)
    if bare:
        return _ParsedContent(kind="bare", code=bare)
    return None


def _decode_body(body: bytes | str) -> str | None:
    if isinstance(body, bytes):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return None
    elif isinstance(body, str):
        text = body
    else:
        return None
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    return text


def _coerce_status(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _coerce_response(value: Any) -> HttpResponse | None:
    if isinstance(value, HttpResponse):
        return value
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        status = _coerce_status(value[0])
        body = value[1]
        if status is not None and isinstance(body, (bytes, str)):
            return HttpResponse(status=status, body=body)
        return None
    if hasattr(value, "status") and hasattr(value, "body"):
        status = _coerce_status(getattr(value, "status"))
        body = getattr(value, "body")
        if status is not None and isinstance(body, (bytes, str)):
            return HttpResponse(status=status, body=body)
    return None


def _error_detail(data: Any, key: str) -> str:
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    message = ""
    if isinstance(error, dict):
        message = error.get("message") or error.get("msg") or error.get("detail") or ""
    elif isinstance(error, str):
        message = error
    elif isinstance(data.get("message"), str):
        message = data["message"]
    if not message:
        return ""
    text = _sanitize(str(message), key)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:240]


# ---------------------------------------------------------------------------
# AIClient
# ---------------------------------------------------------------------------

_BACKOFF_BASE = 0.5
_BACKOFF_MAX = 8.0


class AIClient:
    """Generate SFML candidates via a DeepSeek-compatible chat completions API."""

    def __init__(
        self,
        prompt_manager: PromptManager | None = None,
        transport: Transport | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.prompt_manager = prompt_manager or PromptManager()
        self.transport = transport
        self._sleeper = sleeper or time.sleep

    # -- public API ----------------------------------------------------
    def generate(
        self,
        settings: AISettings,
        key: str | None,
        project_context: dict[str, Any],
        user_request: str,
        transport: Transport | None = None,
        *,
        prompt_manager: PromptManager | None = None,
    ) -> AIResult:
        """Run one generation attempt; always returns an :class:`AIResult`."""
        key_text = key.strip() if isinstance(key, str) else ""
        try:
            return self._generate(
                settings,
                key_text,
                project_context,
                user_request,
                transport=transport,
                prompt_manager=prompt_manager,
            )
        except Exception as exc:  # defensive: never leak a key via traceback text
            return AIResult(
                status=STATUS_INVALID_RESPONSE,
                error=f"AI 生成失败（内部错误：{type(exc).__name__}）",
            )

    # -- preflight -----------------------------------------------------
    def _generate(
        self,
        settings: AISettings,
        key: str,
        project_context: dict[str, Any],
        user_request: str,
        *,
        transport: Transport | None,
        prompt_manager: PromptManager | None,
    ) -> AIResult:
        if not isinstance(settings, AISettings):
            return AIResult(status=STATUS_CONFIG_ERROR, error="AI 设置无效")
        if not settings.enabled:
            return AIResult(
                status=STATUS_DISABLED,
                error="AI 生成已被显式禁用（AISettings.enabled=False）；请检查 AI 服务设置",
            )
        if not key:
            return AIResult(status=STATUS_MISSING_KEY, error="未配置密钥；请先在设置 → AI 服务中填写 key")
        if any(ord(char) < 32 for char in key):
            return AIResult(status=STATUS_CONFIG_ERROR, error="密钥包含非法控制字符；请重新输入 key")
        if not is_supported_protocol(settings.protocol):
            return AIResult(
                status=STATUS_UNSUPPORTED_PROTOCOL,
                error=f"未支持的协议：{settings.protocol or '（空）'}；当前仅支持 DeepSeek 官方 API",
            )
        if not isinstance(project_context, Mapping):
            return AIResult(status=STATUS_INVALID_REQUEST, error="工程上下文必须是 JSON 对象")
        if not isinstance(user_request, str) or not user_request.strip():
            return AIResult(status=STATUS_INVALID_REQUEST, error="请先填写生成需求")
        if not settings.model:
            return AIResult(status=STATUS_CONFIG_ERROR, error="模型名称不能为空")
        if not settings.base_url:
            return AIResult(status=STATUS_CONFIG_ERROR, error="接口地址不能为空")
        try:
            url = chat_completions_url(settings.base_url)
            _validate_endpoint(url)
        except ValueError as exc:
            return AIResult(status=STATUS_CONFIG_ERROR, error=f"接口地址无效：{exc}")

        manager = prompt_manager or self.prompt_manager
        if not isinstance(manager, PromptManager):
            return AIResult(status=STATUS_CONFIG_ERROR, error="提示词管理器无效")
        try:
            context_json = json.dumps(
                dict(project_context), ensure_ascii=False, indent=2, default=str
            )
        except (TypeError, ValueError):
            return AIResult(status=STATUS_INVALID_REQUEST, error="工程上下文无法序列化为 JSON")
        profile = _profile_text(project_context)
        prompt = manager.render(
            profile=profile,
            context_json=context_json,
            user_requirement=user_request.strip(),
        )
        if len(prompt) > MAX_PROMPT_CHARS:
            return AIResult(status=STATUS_CONFIG_ERROR, error="提示词与工程上下文过长；请缩短上下文或需求")

        request = self._build_request(settings, key, prompt, user_request.strip())
        sender = transport or self.transport or urllib_transport
        if not callable(sender):
            return AIResult(status=STATUS_CONFIG_ERROR, error="AI 传输实现不可调用")

        attempts = settings.retries + 1
        for attempt in range(attempts):
            try:
                raw_response = sender(request)
            except (TransportTimeout, TimeoutError):
                return AIResult(
                    status=STATUS_TIMEOUT,
                    error=f"请求超时：AI 服务在 {settings.timeout:g} 秒内没有响应；可点击重试",
                )
            except (TransportNetworkError, urllib.error.URLError, OSError, socket.error):
                return AIResult(
                    status=STATUS_NETWORK_ERROR,
                    error="网络错误：无法连接 AI 服务；请检查网络、代理或接口地址（不会自动切换地址）",
                )
            except Exception as exc:  # unknown transport failure; sanitize type only
                return AIResult(
                    status=STATUS_NETWORK_ERROR,
                    error=f"AI 请求失败（{_sanitize(type(exc).__name__, key)}）",
                )

            response = _coerce_response(raw_response)
            if response is None:
                return AIResult(status=STATUS_INVALID_RESPONSE, error="AI 传输返回了无法识别的响应对象")

            status = _coerce_status(response.status)
            if status is None:
                return AIResult(status=STATUS_INVALID_RESPONSE, error="AI 服务返回了无效的 HTTP 状态码")

            if 200 <= status < 300:
                return self._parse_success(response, key)

            if (status == 429 or 500 <= status < 600) and attempt < attempts - 1:
                self._sleep(_BACKOFF_BASE * (2**attempt))
                continue
            return self._http_error(status, response.body, key)

        return AIResult(status=STATUS_NETWORK_ERROR, error="AI 请求未完成")  # pragma: no cover

    # -- request -------------------------------------------------------
    def _build_request(
        self,
        settings: AISettings,
        key: str,
        prompt: str,
        user_request: str,
    ) -> HttpRequest:
        payload = {
            "model": settings.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_request},
            ],
            "stream": False,
            "temperature": settings.temperature,
            "max_tokens": settings.max_output,
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "SFMCodeWorkshop/0.1 (DeepSeek chat/completions)",
        }
        return HttpRequest(
            url=chat_completions_url(settings.base_url),
            method="POST",
            headers=headers,
            body=body,
            timeout=settings.timeout,
        )

    def _sleep(self, seconds: float) -> None:
        try:
            self._sleeper(max(0.0, seconds))
        except Exception:  # pragma: no cover - a broken sleeper must not crash
            pass

    # -- HTTP error mapping -------------------------------------------
    def _http_error(self, status: int, body: bytes | str, key: str) -> AIResult:
        text = _decode_body(body)
        data: Any = None
        if text and text.strip():
            try:
                data = json.loads(text)
            except (ValueError, TypeError):
                data = None
        detail = _error_detail(data, key)

        if status == 401:
            return AIResult(
                status=STATUS_AUTH_ERROR,
                error="认证失败（HTTP 401）：请检查 key 是否正确、是否过期",
            )
        if status == 403:
            return AIResult(
                status=STATUS_AUTH_ERROR,
                error="认证失败（HTTP 403）：key 无权访问该接口，请检查账号/权限",
            )
        if status == 429:
            return AIResult(
                status=STATUS_RATE_LIMITED,
                error="请求过于频繁（HTTP 429）；已达到重试上限，请稍后再试",
            )
        if 400 <= status < 500:
            message = f"请求被拒绝（HTTP {status}）：请检查接口地址、模型或请求参数"
            if detail:
                message += f"。服务返回：{_sanitize(detail, key)}"
            return AIResult(status=STATUS_HTTP_ERROR, error=message)
        if 300 <= status < 400:
            return AIResult(
                status=STATUS_HTTP_ERROR,
                error=f"请求被重定向（HTTP {status}），为保护密钥已拒绝跟随；请检查接口地址",
            )
        if 500 <= status < 600:
            message = f"AI 服务暂时不可用（HTTP {status}）；已重试，请稍后再试"
            if detail:
                message += f"。服务返回：{_sanitize(detail, key)}"
            return AIResult(status=STATUS_SERVER_ERROR, error=message)
        return AIResult(status=STATUS_HTTP_ERROR, error=f"AI 请求失败（HTTP {status}）")

    # -- success parsing ----------------------------------------------
    def _parse_success(self, response: HttpResponse, key: str) -> AIResult:
        text = _decode_body(response.body)
        if text is None:
            return AIResult(status=STATUS_INVALID_RESPONSE, error="AI 服务返回了无法解码的响应")
        if not text.strip():
            return AIResult(status=STATUS_EMPTY_RESPONSE, error="AI 服务返回了空响应")
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return AIResult(status=STATUS_INVALID_RESPONSE, error="AI 服务返回的不是有效 JSON")
        if not isinstance(data, dict):
            return AIResult(status=STATUS_INVALID_RESPONSE, error="AI 服务返回的 JSON 不是对象")
        if data.get("error"):
            detail = _error_detail(data, key)
            message = "AI 服务返回错误"
            if detail:
                message += f"：{_sanitize(detail, key)}"
            return AIResult(status=STATUS_SERVER_ERROR, error=message)

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return AIResult(status=STATUS_INVALID_RESPONSE, error="AI 响应缺少 choices[0]")
        choice = choices[0]
        if not isinstance(choice, dict):
            return AIResult(status=STATUS_INVALID_RESPONSE, error="AI 响应的 choices[0] 格式无效")
        message = choice.get("message")
        if not isinstance(message, dict):
            message = {}
        content = message.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            content = "\n".join(parts)
        if not isinstance(content, str):
            return AIResult(status=STATUS_INVALID_RESPONSE, error="AI 响应缺少 message.content")
        if not content.strip():
            return AIResult(status=STATUS_EMPTY_RESPONSE, error="模型返回了空内容")
        finish_reason = str(choice.get("finish_reason") or "")
        return self._result_from_content(content, finish_reason, key)

    def _result_from_content(self, content: str, finish_reason: str, key: str) -> AIResult:
        raw = _sanitize(content, key)
        parsed = _parse_content(content)
        if parsed is None:
            if finish_reason == "length" or _looks_truncated(content):
                return AIResult(
                    status=STATUS_TRUNCATED,
                    raw=raw,
                    error="模型输出被截断（finish_reason=length），未生成完整代码；可重试",
                )
            return AIResult(
                status=STATUS_INVALID_RESPONSE,
                raw=raw,
                error="模型返回内容不是有效的 JSON 或 SFML 代码",
            )

        self_review = [_sanitize(item, key) for item in parsed.self_review]
        assumptions = [_sanitize(item, key) for item in parsed.assumptions]
        missing_info = [_sanitize(item, key) for item in parsed.missing_info]
        code = _sanitize(parsed.code, key).lstrip("\ufeff")
        code = code.replace("\r\n", "\n").replace("\r", "\n").strip()

        if parsed.error and not code:
            return AIResult(
                raw=raw,
                self_review=self_review,
                assumptions=assumptions,
                missing_info=missing_info,
                status=STATUS_INVALID_RESPONSE,
                error=_sanitize(f"模型返回错误：{parsed.error}", key),
            )

        if not code:
            if missing_info:
                return AIResult(
                    raw=raw,
                    self_review=self_review,
                    assumptions=assumptions,
                    missing_info=missing_info,
                    status=STATUS_NEEDS_INPUT,
                )
            if finish_reason == "length" or _looks_truncated(content):
                return AIResult(
                    raw=raw,
                    self_review=self_review,
                    assumptions=assumptions,
                    missing_info=missing_info,
                    status=STATUS_TRUNCATED,
                    error="模型输出被截断，未生成完整代码；可重试或补充信息",
                )
            return AIResult(
                raw=raw,
                self_review=self_review,
                assumptions=assumptions,
                missing_info=missing_info,
                status=STATUS_EMPTY_RESPONSE,
                error="模型没有返回代码",
            )

        base = AIResult(
            code=code,
            raw=raw,
            self_review=self_review,
            assumptions=assumptions,
            missing_info=missing_info,
        )

        if finish_reason == "length":
            base.status = STATUS_TRUNCATED
            base.error = "模型输出达到长度上限，代码可能不完整；未自动应用，请重试或调整需求"
            return base
        if finish_reason == "content_filter":
            base.status = STATUS_INVALID_RESPONSE
            base.error = "模型因内容安全策略未完成生成；请调整需求"
            return base

        syntax_errors = _sfml_syntax_errors(code)
        if syntax_errors:
            base.status = STATUS_INVALID_SFML
            base.error = "AI 候选未通过 SFML 语法检查：" + "；".join(syntax_errors[:3])
            return base
        if not _looks_like_sfml(code):
            base.status = STATUS_INVALID_SFML
            base.error = "AI 候选不像 SFML 代码（缺少 NAME/EVERY/INPUT/OUTPUT）"
            return base
        base.status = STATUS_OK
        return base


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


def _profile_text(project_context: Mapping[str, Any]) -> str:
    profile = project_context.get("profile")
    if isinstance(profile, str) and profile.strip():
        return profile.strip()
    if isinstance(profile, Mapping):
        for name in ("label", "name", "id"):
            value = profile.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for name in ("profile_label", "profile_id"):
        value = project_context.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "未提供（以工程上下文为准）"
