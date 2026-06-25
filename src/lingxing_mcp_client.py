from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_PROTOCOL_VERSION = "2025-03-26"
DEFAULT_CLIENT_NAME = "amazon_ops_automation"
DEFAULT_CLIENT_VERSION = "0.1.0"


class LingxingMcpError(RuntimeError):
    """Raised when the LingXing MCP server returns an error or invalid payload."""


@dataclass
class JsonRpcResponse:
    status_code: int
    headers: dict[str, str]
    messages: list[dict[str, Any]]


def _normalize_headers(headers: Any) -> dict[str, str]:
    if hasattr(headers, "items"):
        return {str(key): str(value) for key, value in headers.items()}
    return {}


def _extract_sse_messages(payload: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    event_lines: list[str] = []
    for raw_line in payload.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            if event_lines:
                body = "\n".join(event_lines).strip()
                if body:
                    messages.append(json.loads(body))
                event_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            event_lines.append(line[5:].lstrip())
    if event_lines:
        body = "\n".join(event_lines).strip()
        if body:
            messages.append(json.loads(body))
    return messages


def _decode_response(content_type: str, payload: bytes) -> list[dict[str, Any]]:
    text = payload.decode("utf-8")
    if "text/event-stream" in content_type:
        return _extract_sse_messages(text)

    decoded = json.loads(text)
    if isinstance(decoded, list):
        return decoded
    if isinstance(decoded, dict):
        return [decoded]
    raise LingxingMcpError("MCP response is neither a JSON object nor a JSON array.")


def _jsonrpc_error(message: dict[str, Any]) -> str | None:
    error = message.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    text = str(error.get("message") or "Unknown MCP error")
    data = error.get("data")
    if data in (None, "", {}):
        return f"{code}: {text}" if code is not None else text
    return f"{code}: {text} | data={json.dumps(data, ensure_ascii=False)}"


def _result_from_messages(messages: list[dict[str, Any]], request_id: int) -> dict[str, Any]:
    for message in messages:
        if not isinstance(message, dict):
            continue
        error_text = _jsonrpc_error(message)
        if error_text is not None and message.get("id") == request_id:
            raise LingxingMcpError(error_text)
        if message.get("id") == request_id and "result" in message:
            result = message["result"]
            if isinstance(result, dict):
                return result
            return {"value": result}
    raise LingxingMcpError(f"MCP response missing result for request id {request_id}.")


class LingxingMcpClient:
    def __init__(
        self,
        url: str,
        api_key: str,
        timeout: int = 30,
        protocol_version: str = DEFAULT_PROTOCOL_VERSION,
        client_name: str = DEFAULT_CLIENT_NAME,
        client_version: str = DEFAULT_CLIENT_VERSION,
    ) -> None:
        clean_url = (url or "").strip()
        clean_key = (api_key or "").strip()
        if not clean_url:
            raise ValueError("LingXing MCP URL is required.")
        if not clean_key:
            raise ValueError("LingXing MCP API key is required.")
        self.url = clean_url
        self.api_key = clean_key
        self.timeout = timeout
        self.protocol_version = protocol_version
        self.client_name = client_name
        self.client_version = client_version
        self.session_id = ""
        self.server_info: dict[str, Any] = {}
        self.server_capabilities: dict[str, Any] = {}
        self.instructions = ""
        self._next_request_id = 1

    def _request_id(self) -> int:
        request_id = self._next_request_id
        self._next_request_id += 1
        return request_id

    def _headers(self, include_session: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "X-Mcp-Key": self.api_key,
        }
        if include_session and self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post_message(self, message: dict[str, Any], include_session: bool) -> JsonRpcResponse:
        data = json.dumps(message, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=data,
            headers=self._headers(include_session=include_session),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                headers = _normalize_headers(response.headers)
                content_type = headers.get("Content-Type", "")
                messages = _decode_response(content_type, payload) if payload else []
                return JsonRpcResponse(
                    status_code=int(getattr(response, "status", 200)),
                    headers=headers,
                    messages=messages,
                )
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            content_type = exc.headers.get("Content-Type", "")
            details = ""
            if payload:
                try:
                    messages = _decode_response(content_type, payload)
                    error_messages = [
                        message for message in messages if isinstance(message, dict) and message.get("error")
                    ]
                    if error_messages:
                        details = " | ".join(
                            _jsonrpc_error(message) or json.dumps(message, ensure_ascii=False)
                            for message in error_messages
                        )
                    else:
                        details = payload.decode("utf-8", errors="replace")
                except Exception:
                    details = payload.decode("utf-8", errors="replace")
            status = getattr(exc, "code", "unknown")
            if details:
                raise LingxingMcpError(f"HTTP {status}: {details}") from exc
            raise LingxingMcpError(f"HTTP {status}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise LingxingMcpError(f"Network error: {exc.reason}") from exc

    def initialize(self) -> dict[str, Any]:
        request_id = self._request_id()
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": self.client_name,
                    "version": self.client_version,
                },
            },
        }
        response = self._post_message(message, include_session=False)
        result = _result_from_messages(response.messages, request_id)
        self.session_id = response.headers.get("Mcp-Session-Id", "")
        self.server_info = dict(result.get("serverInfo") or {})
        self.server_capabilities = dict(result.get("capabilities") or {})
        self.instructions = str(result.get("instructions") or "")
        self._send_initialized()
        return result

    def _send_initialized(self) -> None:
        message = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        self._post_message(message, include_session=bool(self.session_id))

    def ensure_initialized(self) -> None:
        if self.server_info:
            return
        self.initialize()

    def list_tools(self) -> list[dict[str, Any]]:
        self.ensure_initialized()
        request_id = self._request_id()
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/list",
            "params": {},
        }
        response = self._post_message(message, include_session=True)
        result = _result_from_messages(response.messages, request_id)
        tools = result.get("tools") or []
        if not isinstance(tools, list):
            raise LingxingMcpError("MCP tools/list response has invalid tools payload.")
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_initialized()
        request_id = self._request_id()
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {},
            },
        }
        response = self._post_message(message, include_session=True)
        return _result_from_messages(response.messages, request_id)
