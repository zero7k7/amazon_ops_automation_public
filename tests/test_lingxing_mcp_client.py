from __future__ import annotations

import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from src.lingxing_mcp_client import (
    LingxingMcpClient,
    LingxingMcpError,
    _decode_response,
    _extract_sse_messages,
    _result_from_messages,
)


def test_extract_sse_messages_parses_multiple_events() -> None:
    payload = (
        'event: message\n'
        'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n'
        "\n"
        ': keep-alive\n'
        'data: {"jsonrpc":"2.0","id":2,"result":{"name":"tool"}}\n'
        "\n"
    )

    messages = _extract_sse_messages(payload)

    assert messages == [
        {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
        {"jsonrpc": "2.0", "id": 2, "result": {"name": "tool"}},
    ]


def test_decode_response_accepts_json_array_and_object() -> None:
    array_payload = json.dumps([{"id": 1, "result": {"ok": True}}]).encode("utf-8")
    object_payload = json.dumps({"id": 2, "result": {"ok": True}}).encode("utf-8")

    assert _decode_response("application/json", array_payload) == [{"id": 1, "result": {"ok": True}}]
    assert _decode_response("application/json", object_payload) == [{"id": 2, "result": {"ok": True}}]


def test_result_from_messages_raises_jsonrpc_error() -> None:
    with pytest.raises(LingxingMcpError, match="bad request"):
        _result_from_messages(
            [{"jsonrpc": "2.0", "id": 7, "error": {"code": -32602, "message": "bad request"}}],
            7,
        )


def test_client_requires_url_and_key() -> None:
    with pytest.raises(ValueError, match="URL"):
        LingxingMcpClient(url="", api_key="abc")
    with pytest.raises(ValueError, match="API key"):
        LingxingMcpClient(url="http://example.com", api_key="")


def test_http_error_payload_uses_jsonrpc_error_text(monkeypatch: pytest.MonkeyPatch) -> None:
    headers = Message()
    headers["Content-Type"] = "application/json"
    error = HTTPError(
        url="http://example.com",
        code=400,
        msg="Bad Request",
        hdrs=headers,
        fp=None,
    )
    error.read = lambda: json.dumps(
        {"jsonrpc": "2.0", "id": 9, "error": {"code": -32602, "message": "invalid args"}}
    ).encode("utf-8")

    def _raise_http_error(*args: object, **kwargs: object) -> object:
        raise error

    monkeypatch.setattr("urllib.request.urlopen", _raise_http_error)
    client = LingxingMcpClient(url="http://example.com", api_key="secret")

    with pytest.raises(LingxingMcpError, match="invalid args"):
        client._post_message({"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}}, include_session=False)
