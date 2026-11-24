"""Tests for the AI service: prompts, settings, request/response, errors.

All tests use an injected fake transport; nothing here touches the network.
"""

from __future__ import annotations

import json
import logging
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from sfm_workshop.services import ai
from sfm_workshop.services.ai import (
    AIClient,
    AIResult,
    AISettings,
    DEFAULT_BASE_URL,
    DEFAULT_MAX_OUTPUT,
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    DEFAULT_PROMPT_HASH,
    DEFAULT_PROMPT_VERSION,
    DEFAULT_PROTOCOL,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    HttpRequest,
    HttpResponse,
    PromptManager,
    STATUS_AUTH_ERROR,
    STATUS_CONFIG_ERROR,
    STATUS_DISABLED,
    STATUS_EMPTY_RESPONSE,
    STATUS_HTTP_ERROR,
    STATUS_INVALID_REQUEST,
    STATUS_INVALID_RESPONSE,
    STATUS_INVALID_SFML,
    STATUS_MISSING_KEY,
    STATUS_NEEDS_INPUT,
    STATUS_NETWORK_ERROR,
    STATUS_OK,
    STATUS_RATE_LIMITED,
    STATUS_SERVER_ERROR,
    STATUS_TIMEOUT,
    STATUS_TRUNCATED,
    STATUS_UNSUPPORTED_PROTOCOL,
    chat_completions_url,
)
from sfm_workshop.services.ai import _parse_content  # internal parser is tested directly

KEY = "sk-sfm-test-secret-0123456789abcdef"
PROFILE = "MC 1.21.1 / NeoForge / SFM 4.34.0"

VALID_SFML = (
    'NAME "AI 生成"\n'
    "EVERY 20 TICKS DO\n"
    '  INPUT FROM "原料箱"\n'
    '  OUTPUT TO "熔炉"\n'
    "END"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_settings(**overrides) -> AISettings:
    values = {"enabled": True, "retries": 0}
    values.update(overrides)
    return AISettings(**values)


def envelope(**overrides) -> str:
    data = {
        "code": VALID_SFML,
        "self_review": ["END 配对", "标签存在"],
        "assumptions": [],
        "missing_info": [],
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def chat_response(content: str, finish_reason: str = "stop") -> HttpResponse:
    body = {
        "id": "chatcmpl-test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
    }
    return HttpResponse(status=200, body=json.dumps(body, ensure_ascii=False))


def context() -> dict:
    return {
        "profile": PROFILE,
        "labels": ["原料箱", "熔炉"],
        "code": "",
        "notes": "测试用工程",
    }


class Recorder:
    """Fake transport: records requests and replays queued responses/exceptions."""

    def __init__(self, responses=None) -> None:
        self.responses = list(responses or [])
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("fake transport called more times than expected")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


# ---------------------------------------------------------------------------
# Default prompt / PromptManager
# ---------------------------------------------------------------------------


def test_default_prompt_matches_prd_verbatim():
    prd_path = Path(__file__).resolve().parents[1] / "docs" / "PRD-新增需求-v1.1.md"
    if not prd_path.exists():
        pytest.skip("PRD document is not available")
    text = prd_path.read_text(encoding="utf-8")
    marker = "### 2.5 默认提示词"
    assert marker in text
    start = text.index(marker)
    fence_start = text.index("```text\n", start) + len("```text\n")
    fence_end = text.index("\n```", fence_start)
    assert DEFAULT_PROMPT == text[fence_start:fence_end]
    assert DEFAULT_PROMPT_HASH == ai.default_prompt_hash()
    assert DEFAULT_PROMPT_VERSION == 1

    for token in (
        "{{profile}}",
        "{{context_json}}",
        "{{user_requirement}}",
        '"self_review"',
        '"assumptions"',
        '"missing_info"',
        "只输出一个 JSON 对象",
        "SFM 4.34.0",
    ):
        assert token in DEFAULT_PROMPT


def test_prompt_manager_default_override_reset_and_render():
    manager = PromptManager()
    assert manager.default_text == DEFAULT_PROMPT
    assert manager.default_hash == DEFAULT_PROMPT_HASH
    assert manager.get_override() == ""
    assert manager.effective_prompt() == DEFAULT_PROMPT
    assert manager.is_default

    # built-in prompt is read-only (no setter)
    with pytest.raises(AttributeError):
        manager.default_text = "changed"  # type: ignore[misc]

    custom = "自定义 {{profile}}\n上下文：{{context_json}}\n需求：{{user_requirement}}"
    manager.set_override(custom)
    assert manager.get_override() == custom
    assert manager.effective_prompt() == custom
    assert ai.default_prompt_hash() == DEFAULT_PROMPT_HASH  # built-in unchanged
    assert "{{profile}}" in manager.default_text

    rendered = manager.render("P", '{"a": 1}', "R")
    assert "P" in rendered and '{"a": 1}' in rendered and "R" in rendered
    assert "{{" not in rendered

    manager.reset()
    assert manager.effective_prompt() == DEFAULT_PROMPT
    manager.set_override(DEFAULT_PROMPT)
    assert manager.is_default
    manager.set_override("   \n")
    assert manager.is_default
    manager.set_override("CRLF\r\n第二行")
    assert manager.effective_prompt() == "CRLF\n第二行"


def test_prompt_manager_from_app_settings():
    manager = PromptManager.from_app_settings(
        SimpleNamespace(prompt_override="自定义", ai_prompt_version=3)
    )
    assert manager.get_override() == "自定义"
    assert manager.version == 3


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_defaults_and_endpoint():
    settings = AISettings()
    assert settings.base_url == DEFAULT_BASE_URL == "https://api.deepseek.com"
    assert settings.model == DEFAULT_MODEL == "deepseek-chat"
    assert settings.protocol == DEFAULT_PROTOCOL == "DeepSeek 官方 API"
    assert settings.timeout == DEFAULT_TIMEOUT > 0
    assert settings.retries == DEFAULT_RETRIES >= 0
    assert settings.max_output == DEFAULT_MAX_OUTPUT > 0
    assert settings.enabled is True, "settings on their own do not block; the UI entry is opt-in"
    assert AISettings(enabled=False).enabled is False
    assert settings.endpoint == "https://api.deepseek.com/chat/completions"
    assert "key" not in AISettings.__dataclass_fields__


def test_settings_from_app_settings_and_dict():
    app = SimpleNamespace(
        ai_enabled=True,
        ai_base_url="https://example.test/v1/",
        ai_model="deepseek-reasoner",
        ai_protocol="DeepSeek 官方 API",
        ai_timeout=30,
        ai_retries=1,
        ai_max_output=2048,
    )
    settings = AISettings.from_app_settings(app)
    assert settings.enabled is True
    assert settings.base_url == "https://example.test/v1/"
    assert settings.model == "deepseek-reasoner"
    assert settings.timeout == 30
    assert settings.retries == 1
    assert settings.max_output == 2048
    assert settings.endpoint == "https://example.test/v1/chat/completions"

    mapped = AISettings.from_dict(
        {"ai_enabled": True, "ai_base_url": "https://x.test", "ai_model": "m"}
    )
    assert mapped.enabled is True and mapped.base_url == "https://x.test" and mapped.model == "m"
    assert "key" not in json.dumps(mapped.to_dict())


def test_chat_completions_url_variants():
    assert chat_completions_url("https://api.deepseek.com") == (
        "https://api.deepseek.com/chat/completions"
    )
    assert chat_completions_url("https://api.deepseek.com/") == (
        "https://api.deepseek.com/chat/completions"
    )
    assert chat_completions_url("https://api.deepseek.com/v1") == (
        "https://api.deepseek.com/v1/chat/completions"
    )
    assert chat_completions_url("https://host/chat/completions") == (
        "https://host/chat/completions"
    )
    with pytest.raises(ValueError):
        chat_completions_url("")


# ---------------------------------------------------------------------------
# Successful generation
# ---------------------------------------------------------------------------


def test_generate_json_envelope_success_and_request_shape():
    content = envelope(assumptions=["默认使用 20 tick"])
    recorder = Recorder([chat_response(content)])
    client = AIClient(transport=recorder)

    result = client.generate(make_settings(), KEY, context(), "把原料箱送进熔炉")

    assert result.status == STATUS_OK
    assert result.ok
    assert result.code == VALID_SFML
    assert result.raw == content
    assert result.self_review == ["END 配对", "标签存在"]
    assert result.assumptions == ["默认使用 20 tick"]
    assert result.missing_info == []
    assert result.error == ""

    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request.url == "https://api.deepseek.com/chat/completions"
    assert request.method == "POST"
    assert request.timeout == DEFAULT_TIMEOUT
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert "json" in request.headers["Content-Type"].lower()

    payload = json.loads(request.body.decode("utf-8"))
    assert payload["model"] == "deepseek-chat"
    assert payload["stream"] is False
    assert payload["max_tokens"] == DEFAULT_MAX_OUTPUT
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"
    assert payload["messages"][1]["content"] == "把原料箱送进熔炉"
    system_prompt = payload["messages"][0]["content"]
    assert PROFILE in system_prompt
    assert "原料箱" in system_prompt
    assert "把原料箱送进熔炉" in system_prompt
    assert "{{profile}}" not in system_prompt
    assert "{{context_json}}" not in system_prompt
    assert "{{user_requirement}}" not in system_prompt


def test_ui_style_settings_without_enabled_flag_can_generate():
    """AIDialog builds AISettings(base_url=..., model=..., protocol=...) only."""
    settings = AISettings(
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        protocol="DeepSeek 官方 API",
    )
    recorder = Recorder([chat_response(envelope())])
    result = AIClient(transport=recorder).generate(settings, KEY, context(), "需求")
    assert settings.enabled is True
    assert result.status == STATUS_OK
    assert len(recorder.requests) == 1


def test_generate_fenced_code_fallback():
    recorder = Recorder([chat_response(f"```sfm\n{VALID_SFML}\n```")])
    result = AIClient(transport=recorder).generate(
        make_settings(), KEY, context(), "生成一个最简任务"
    )
    assert result.status == STATUS_OK
    assert result.code == VALID_SFML
    assert "```" in result.raw


def test_generate_fenced_json_fallback():
    body = "```json\n" + envelope(self_review=["来自围栏"]) + "\n```"
    recorder = Recorder([chat_response(body)])
    result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    assert result.status == STATUS_OK
    assert result.code == VALID_SFML
    assert result.self_review == ["来自围栏"]


def test_generate_bare_sfml_fallback():
    recorder = Recorder([chat_response(VALID_SFML)])
    result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    assert result.status == STATUS_OK
    assert result.code == VALID_SFML


def test_custom_prompt_manager_is_used():
    recorder = Recorder([chat_response(envelope())])
    manager = PromptManager("自定义 {{profile}} | {{context_json}} | {{user_requirement}}")
    result = AIClient(transport=recorder, prompt_manager=manager).generate(
        make_settings(), KEY, context(), "用户需求"
    )
    assert result.status == STATUS_OK
    payload = json.loads(recorder.requests[0].body.decode("utf-8"))
    system_prompt = payload["messages"][0]["content"]
    assert system_prompt.startswith("自定义 ")
    assert PROFILE in system_prompt
    assert "用户需求" in system_prompt

    # per-call override wins
    recorder2 = Recorder([chat_response(envelope())])
    client = AIClient(transport=recorder2, prompt_manager=manager)
    client.generate(
        make_settings(), KEY, context(), "第二次", prompt_manager=PromptManager("覆盖 {{user_requirement}}")
    )
    payload2 = json.loads(recorder2.requests[0].body.decode("utf-8"))
    assert payload2["messages"][0]["content"].startswith("覆盖 ")


def test_context_is_not_mutated():
    context_data = context()
    snapshot = json.loads(json.dumps(context_data, ensure_ascii=False))
    recorder = Recorder([chat_response(envelope())])
    AIClient(transport=recorder).generate(make_settings(), KEY, context_data, "需求")
    assert context_data == snapshot


# ---------------------------------------------------------------------------
# Missing information / invalid model output
# ---------------------------------------------------------------------------


def test_missing_info_returns_needs_input_without_code():
    content = envelope(code="", missing_info=["缺少目标标签", "缺少面"], self_review=[])
    recorder = Recorder([chat_response(content)])
    result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    assert result.status == STATUS_NEEDS_INPUT
    assert result.needs_input
    assert not result.ok
    assert result.code == ""
    assert result.missing_info == ["缺少目标标签", "缺少面"]
    assert result.error == ""


def test_invalid_sfml_keeps_candidate_for_display():
    content = json.dumps({"code": "hello world"}, ensure_ascii=False)
    recorder = Recorder([chat_response(content)])
    result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    assert result.status == STATUS_INVALID_SFML
    assert not result.ok
    assert result.code == "hello world"
    assert "SFML" in result.error
    assert result.raw == content


def test_empty_model_content():
    recorder = Recorder([chat_response("   ")])
    result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    assert result.status == STATUS_EMPTY_RESPONSE


def test_malformed_api_envelope():
    responses = [
        HttpResponse(200, b"<html>not json</html>"),
        HttpResponse(200, json.dumps({"choices": []})),
        HttpResponse(200, json.dumps({"choices": [{"message": {"content": None}}]})),
    ]
    for response in responses:
        recorder = Recorder([response])
        result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
        assert result.status == STATUS_INVALID_RESPONSE
        assert result.error


def test_truncated_by_finish_reason():
    recorder = Recorder([chat_response(envelope(), finish_reason="length")])
    result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    assert result.status == STATUS_TRUNCATED
    assert not result.ok
    assert result.code == VALID_SFML  # candidate kept for display
    assert "截断" in result.error or "长度上限" in result.error


def test_truncated_unbalanced_json_without_finish_reason():
    truncated = '{"code": "NAME \\"x\\"\\nEVERY 20 TICKS DO", "self_review": ['
    recorder = Recorder([chat_response(truncated)])
    result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    assert result.status == STATUS_TRUNCATED


def test_parse_content_fenced_json():
    parsed = _parse_content("```json\n" + envelope() + "\n```")
    assert parsed is not None
    assert parsed.kind == "json"
    assert parsed.code == VALID_SFML


# ---------------------------------------------------------------------------
# Preflight: no request when disabled / misconfigured
# ---------------------------------------------------------------------------


def test_explicitly_disabled_settings_send_nothing():
    recorder = Recorder([])
    result = AIClient(transport=recorder).generate(
        AISettings(enabled=False), KEY, context(), "需求"
    )
    assert result.status == STATUS_DISABLED
    assert recorder.requests == []


def test_unconfigured_default_settings_send_nothing_without_key():
    recorder = Recorder([])
    result = AIClient(transport=recorder).generate(AISettings(), "", context(), "需求")
    assert result.status == STATUS_MISSING_KEY
    assert recorder.requests == []


def test_missing_key_sends_nothing():
    recorder = Recorder([])
    result = AIClient(transport=recorder).generate(make_settings(), "", context(), "需求")
    assert result.status == STATUS_MISSING_KEY
    assert recorder.requests == []

    result = AIClient(transport=recorder).generate(make_settings(), "   ", context(), "需求")
    assert result.status == STATUS_MISSING_KEY
    assert recorder.requests == []


def test_key_with_control_characters_sends_nothing():
    recorder = Recorder([])
    result = AIClient(transport=recorder).generate(
        make_settings(), "sk-test\r\nInjected: 1", context(), "需求"
    )
    assert result.status == STATUS_CONFIG_ERROR
    assert recorder.requests == []
    assert "Injected" not in result.error


def test_unsupported_protocol_sends_nothing():
    recorder = Recorder([])
    settings = make_settings(protocol="Some Other Vendor API")
    result = AIClient(transport=recorder).generate(settings, KEY, context(), "需求")
    assert result.status == STATUS_UNSUPPORTED_PROTOCOL
    assert "协议" in result.error
    assert recorder.requests == []


def test_invalid_request_and_endpoint_send_nothing():
    recorder = Recorder([])
    client = AIClient(transport=recorder)

    assert client.generate(make_settings(), KEY, context(), "").status == STATUS_INVALID_REQUEST
    assert client.generate(make_settings(), KEY, context(), "   ").status == STATUS_INVALID_REQUEST
    assert client.generate(make_settings(), KEY, [], "需求").status == STATUS_INVALID_REQUEST

    http_remote = client.generate(
        make_settings(base_url="http://example.com"), KEY, context(), "需求"
    )
    assert http_remote.status == STATUS_CONFIG_ERROR
    assert "HTTPS" in http_remote.error

    bad_scheme = client.generate(
        make_settings(base_url="ftp://example.com"), KEY, context(), "需求"
    )
    assert bad_scheme.status == STATUS_CONFIG_ERROR

    assert recorder.requests == []


def test_preflight_never_calls_default_network_transport(monkeypatch):
    called: list[HttpRequest] = []
    monkeypatch.setattr(ai, "urllib_transport", lambda request: called.append(request))
    client = AIClient()

    assert (
        client.generate(
            AISettings(enabled=False), KEY, context(), "需求"
        ).status
        == STATUS_DISABLED
    )
    assert client.generate(make_settings(), "", context(), "需求").status == STATUS_MISSING_KEY
    assert (
        client.generate(
            make_settings(protocol="unknown"), KEY, context(), "需求"
        ).status
        == STATUS_UNSUPPORTED_PROTOCOL
    )
    assert called == []


def test_local_http_endpoint_allowed():
    recorder = Recorder([chat_response(envelope())])
    result = AIClient(transport=recorder).generate(
        make_settings(base_url="http://127.0.0.1:8000"), KEY, context(), "需求"
    )
    assert result.status == STATUS_OK
    assert recorder.requests[0].url == "http://127.0.0.1:8000/chat/completions"


# ---------------------------------------------------------------------------
# HTTP / transport errors
# ---------------------------------------------------------------------------


def test_auth_error_401_does_not_retry_and_never_leaks_key():
    body = json.dumps({"error": {"message": f"invalid api key {KEY}"}}, ensure_ascii=False)
    recorder = Recorder([HttpResponse(401, body)])
    result = AIClient(transport=recorder).generate(
        make_settings(retries=3), KEY, context(), "需求"
    )
    assert result.status == STATUS_AUTH_ERROR
    assert len(recorder.requests) == 1, "401 must not be retried"
    assert KEY not in result.error
    assert result.raw == ""


def test_auth_error_403():
    recorder = Recorder([HttpResponse(403, b'{"error": {"message": "forbidden"}}')])
    result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    assert result.status == STATUS_AUTH_ERROR
    assert len(recorder.requests) == 1


def test_timeout_is_not_retried_automatically():
    recorder = Recorder([TimeoutError("slow")])
    result = AIClient(transport=recorder).generate(
        make_settings(retries=3), KEY, context(), "需求"
    )
    assert result.status == STATUS_TIMEOUT
    assert "超时" in result.error
    assert len(recorder.requests) == 1


def test_network_error_from_urlerror():
    recorder = Recorder([urllib.error.URLError(ConnectionRefusedError("refused"))])
    result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    assert result.status == STATUS_NETWORK_ERROR
    assert "网络" in result.error
    assert len(recorder.requests) == 1


def test_rate_limit_retries_then_succeeds():
    recorder = Recorder(
        [
            HttpResponse(429, b'{"error": {"message": "rate limited"}}'),
            chat_response(envelope()),
        ]
    )
    delays: list[float] = []
    result = AIClient(transport=recorder, sleeper=delays.append).generate(
        make_settings(retries=2), KEY, context(), "需求"
    )
    assert result.status == STATUS_OK
    assert len(recorder.requests) == 2
    assert delays == [0.5]


def test_server_error_retries_then_reports_without_key():
    body = json.dumps({"error": {"message": f"server exploded {KEY}"}}, ensure_ascii=False)
    recorder = Recorder([HttpResponse(503, body), HttpResponse(500, body)])
    delays: list[float] = []
    result = AIClient(transport=recorder, sleeper=delays.append).generate(
        make_settings(retries=1), KEY, context(), "需求"
    )
    assert result.status == STATUS_SERVER_ERROR
    assert len(recorder.requests) == 2
    assert delays == [0.5]
    assert KEY not in result.error


def test_redirect_is_rejected():
    recorder = Recorder([HttpResponse(302, b"")])
    result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    assert result.status == STATUS_HTTP_ERROR
    assert "重定向" in result.error


def test_other_http_error_includes_sanitized_detail():
    body = json.dumps({"error": {"message": f"bad request with {KEY}"}}, ensure_ascii=False)
    recorder = Recorder([HttpResponse(400, body)])
    result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    assert result.status == STATUS_HTTP_ERROR
    assert "400" in result.error
    assert KEY not in result.error


def test_unknown_transport_exception_is_sanitized():
    recorder = Recorder([RuntimeError(f"boom with {KEY}")])
    result = AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    assert result.status == STATUS_NETWORK_ERROR
    assert KEY not in result.error


# ---------------------------------------------------------------------------
# Key hygiene
# ---------------------------------------------------------------------------


def test_key_never_in_logs_or_result_and_repr_is_masked(caplog):
    body = json.dumps({"error": {"message": f"rejected {KEY}"}}, ensure_ascii=False)
    recorder = Recorder([HttpResponse(500, body), HttpResponse(500, body)])
    with caplog.at_level(logging.DEBUG):
        result = AIClient(transport=recorder, sleeper=lambda _: None).generate(
            make_settings(retries=1), KEY, context(), "需求"
        )
    assert caplog.text == ""
    assert KEY not in result.error
    assert KEY not in result.raw
    request = recorder.requests[0]
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert KEY not in repr(request)
    assert KEY not in str(request)
    assert "[REDACTED]" in repr(request)


def test_result_object_has_contract_fields():
    result = AIResult()
    for name in (
        "code",
        "raw",
        "self_review",
        "assumptions",
        "missing_info",
        "status",
        "error",
    ):
        assert hasattr(result, name)


def test_prompt_and_context_do_not_contain_key():
    recorder = Recorder([chat_response(envelope())])
    AIClient(transport=recorder).generate(make_settings(), KEY, context(), "需求")
    request = recorder.requests[0]
    assert KEY.encode("utf-8") not in request.body
