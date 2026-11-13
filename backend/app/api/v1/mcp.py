"""MCP server: AI assistants (Claude, ChatGPT and others) use Bull AI Calling as a set of tools.

Streamable HTTP transport, stateless: every JSON-RPC message is a POST to /api/v1/mcp and is answered with plain
JSON (no server-sent events, no session id). Sign in with an API key: "Authorization: Bearer bmk_..." or
"X-API-Key: bmk_...". The tools listed depend on what the key may do (see app/services/mcp.py).
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.deps import ContextDep, CurrentUser, SessionDep, allowed
from app.core.errors import AppError
from app.services.mcp import TOOLS, TOOLS_BY_NAME, Caller

log = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "bull-ai-calling", "title": "Bull AI Calling", "version": "1.0.0"}
INSTRUCTIONS = (
    "Bull AI Calling places AI phone calls for Bull Machines departments. A campaign = a published script + "
    "the people to call. Typical flow: list_scripts -> create_campaign -> add_contacts (dry_run first) -> "
    "submit_campaign -> a person approves it in the app -> control_campaign start -> list_calls / "
    "get_call_result. Phone numbers in results are masked. Never invent people or numbers."
)


def _error(message_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _result(message_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _tool_error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _visible(request: Request, caller: Caller):
    return [t for t in TOOLS if allowed(request, caller.user, t.permission)]


async def _call_tool(request: Request, caller: Caller, params: dict) -> dict | None:
    tool = TOOLS_BY_NAME.get(params.get("name", ""))
    if tool is None or not allowed(request, caller.user, tool.permission):
        return None
    try:
        args = tool.args.model_validate(params.get("arguments") or {})
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in exc.errors())
        return _tool_error(f"Invalid arguments: {problems}")
    try:
        output = jsonable_encoder(await tool.run(caller, args))
    except AppError as exc:
        await caller.session.rollback()
        details = f" Details: {exc.details}" if exc.details else ""
        return _tool_error(f"{exc.message}.{details}")
    except Exception:
        await caller.session.rollback()
        log.exception("MCP tool %s failed", tool.name)
        return _tool_error("Something went wrong on the server. Try again, or check the app.")
    text = json.dumps(output, ensure_ascii=False, indent=1)
    return {"content": [{"type": "text", "text": text}], "structuredContent": output}


async def _handle(message: Any, request: Request, caller: Caller) -> dict | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Invalid request")
    method = message.get("method")
    if method is None or "id" not in message:
        return None  # a notification, or a client's reply: nothing to answer
    message_id = message["id"]
    params = message.get("params") or {}
    match method:
        case "initialize":
            requested = params.get("protocolVersion")
            return _result(
                message_id,
                {
                    "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                    "instructions": INSTRUCTIONS,
                },
            )
        case "ping":
            return _result(message_id, {})
        case "tools/list":
            tools = [
                {
                    "name": t.name,
                    "title": t.title,
                    "description": t.description,
                    "inputSchema": t.args.model_json_schema(),
                    "annotations": {
                        "title": t.title,
                        "readOnlyHint": t.read_only,
                        "destructiveHint": False,
                        "openWorldHint": False,
                    },
                }
                for t in _visible(request, caller)
            ]
            return _result(message_id, {"tools": tools})
        case "tools/call":
            outcome = await _call_tool(request, caller, params)
            if outcome is None:
                return _error(message_id, -32602, f"Unknown tool: {params.get('name')}")
            return _result(message_id, outcome)
        case _:
            return _error(message_id, -32601, f"Method not found: {method}")


@router.post("/mcp")
async def mcp(request: Request, user: CurrentUser, session: SessionDep, ctx: ContextDep) -> Response:
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(_error(None, -32700, "Parse error"))
    caller = Caller(session=session, user=user, ctx=ctx)
    if isinstance(body, list):
        if not body:
            return JSONResponse(_error(None, -32600, "Invalid request"))
        replies = [r for m in body if (r := await _handle(m, request, caller)) is not None]
        return JSONResponse(replies) if replies else Response(status_code=202)
    reply = await _handle(body, request, caller)
    return JSONResponse(reply) if reply is not None else Response(status_code=202)


@router.get("/mcp", include_in_schema=False)
@router.delete("/mcp", include_in_schema=False)
async def mcp_other() -> Response:
    """This server keeps no sessions and sends no server-initiated messages."""
    return Response(status_code=405, headers={"Allow": "POST"})
