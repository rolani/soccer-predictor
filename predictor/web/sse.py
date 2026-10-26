"""Convert Cursor SDK messages to SSE-friendly events."""

from __future__ import annotations

from typing import Any


def message_to_event(msg: Any) -> dict[str, Any] | None:
    """Map SDKMessage to a small JSON event for the UI."""
    if isinstance(msg, dict):
        msg_type = msg.get("type")
        if msg_type == "assistant":
            content = msg.get("message", {}).get("content", [])
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            text = "".join(text_parts).strip()
            if text:
                return {"type": "assistant", "text": text[:2000]}
        if msg_type == "thinking":
            return {"type": "thinking", "text": (msg.get("text") or "")[:500]}
        if msg_type == "tool_call":
            return {
                "type": "tool",
                "name": msg.get("name", ""),
                "status": msg.get("status", ""),
            }
        if msg_type == "status":
            return {"type": "status", "text": msg.get("message", "")}
        return None

    msg_type = getattr(msg, "type", None)
    if msg_type == "assistant":
        content = getattr(getattr(msg, "message", None), "content", []) or []
        text_parts = []
        for block in content:
            btype = getattr(block, "type", None) or (
                block.get("type") if isinstance(block, dict) else None
            )
            if btype == "text":
                text = getattr(block, "text", None) or (
                    block.get("text") if isinstance(block, dict) else ""
                )
                text_parts.append(text or "")
        text = "".join(text_parts).strip()
        if text:
            return {"type": "assistant", "text": text[:2000]}
    if msg_type == "thinking":
        return {"type": "thinking", "text": (getattr(msg, "text", "") or "")[:500]}
    if msg_type == "tool_call":
        return {
            "type": "tool",
            "name": getattr(msg, "name", ""),
            "status": getattr(msg, "status", ""),
        }
    if msg_type == "status":
        return {"type": "status", "text": getattr(msg, "message", "")}
    return None
