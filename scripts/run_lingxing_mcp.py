from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.lingxing_mcp_client import LingxingMcpClient, LingxingMcpError


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call LingXing MCP tools without changing the daily report pipeline."
    )
    parser.add_argument(
        "command",
        choices=["info", "list-tools", "call-tool"],
        help="info: initialize only; list-tools: print tools; call-tool: execute one tool",
    )
    parser.add_argument("--url", default=os.environ.get("LINGXING_MCP_URL", "").strip())
    parser.add_argument("--api-key", default=os.environ.get("LINGXING_MCP_KEY", "").strip())
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--tool-name", default="")
    parser.add_argument("--arguments-json", default="{}")
    parser.add_argument("--arguments-file", default="")
    parser.add_argument("--output", default="")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output. Enabled by default when writing to stdout.",
    )
    return parser.parse_args()


def _load_arguments(args_json: str, args_file: str) -> dict[str, Any]:
    if args_file:
        payload = Path(args_file).read_text(encoding="utf-8")
    else:
        payload = args_json
    loaded = json.loads(payload or "{}")
    if not isinstance(loaded, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    return loaded


def _write_output(payload: dict[str, Any], output_path: str, pretty: bool) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2 if pretty or not output_path else None)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(str(path.resolve()))
        return
    print(text)


def _build_client(url: str, api_key: str, timeout: int) -> LingxingMcpClient:
    if not url:
        raise ValueError("Missing LingXing MCP URL. Set --url or env LINGXING_MCP_URL.")
    if not api_key:
        raise ValueError("Missing LingXing MCP API key. Set --api-key or env LINGXING_MCP_KEY.")
    return LingxingMcpClient(url=url, api_key=api_key, timeout=timeout)


def main() -> int:
    args = _parse_args()
    try:
        client = _build_client(args.url, args.api_key, args.timeout)
        if args.command == "info":
            result = client.initialize()
            _write_output(
                {
                    "session_id_present": bool(client.session_id),
                    "server_info": client.server_info,
                    "server_capabilities": client.server_capabilities,
                    "instructions": client.instructions,
                    "initialize_result": result,
                },
                args.output,
                pretty=True,
            )
            return 0

        if args.command == "list-tools":
            tools = client.list_tools()
            _write_output(
                {
                    "server_info": client.server_info,
                    "tool_count": len(tools),
                    "tools": tools,
                },
                args.output,
                pretty=True,
            )
            return 0

        if not args.tool_name:
            raise ValueError("call-tool requires --tool-name.")
        tool_args = _load_arguments(args.arguments_json, args.arguments_file)
        result = client.call_tool(args.tool_name, tool_args)
        _write_output(
            {
                "server_info": client.server_info,
                "tool_name": args.tool_name,
                "arguments": tool_args,
                "result": result,
            },
            args.output,
            pretty=True,
        )
        return 0
    except (ValueError, json.JSONDecodeError, LingxingMcpError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
