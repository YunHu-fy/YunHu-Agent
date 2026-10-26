"""Standard newline-delimited MCP stdio transport forwarding to the local bridge."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP stdio adapter for the running Android Agent bridge")
    parser.add_argument("--url", default="http://127.0.0.1:8686/mcp")
    parser.add_argument("--token-file", type=Path, default=Path(__file__).resolve().parents[1] / "data/runtime.token")
    parser.add_argument("--timeout", type=int, default=14430, help="HTTP timeout in seconds; must outlast the server task deadline (30..14430)")
    args = parser.parse_args()
    if not 30 <= args.timeout <= 14430:
        parser.error("timeout must be30..14430 seconds")
    parsed = urllib.parse.urlsplit(args.url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("MCP bridge URL must be an HTTP endpoint on numeric127.0.0.1.")
    # MCP stdout contains JSON-RPC messages only; diagnostics belong to stderr.
    for raw in sys.stdin.buffer:
        body = {}
        try:
            if len(raw) > 1024 * 1024:
                raise ValueError("MCP message exceeds1MiB")
            body = json.loads(raw)
            request_id = body.get("id") if isinstance(body, dict) else None
            if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
                raise ValueError("Invalid JSON-RPC message")
            token = args.token_file.read_text(encoding="ascii").strip()
            request = urllib.request.Request(args.url, data=json.dumps(body).encode(), headers={"Authorization":"Bearer "+token,"Content-Type":"application/json","Accept":"application/json"}, method="POST")
            with urllib.request.urlopen(request,timeout=args.timeout) as response:
                payload = response.read(2*1024*1024)
            if "id" not in body:
                continue
            output = json.loads(payload)
        except Exception as exc:
            request_id = None
            try:
                request_id = body.get("id")
                if "id" not in body:
                    continue
            except Exception:
                pass
            output = {"jsonrpc":"2.0","id":request_id,"error":{"code":-32603,"message":"Local bridge unavailable or invalid message: "+type(exc).__name__}}
        sys.stdout.buffer.write((json.dumps(output,ensure_ascii=False,separators=(",",":"))+"\n").encode("utf-8"))
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
