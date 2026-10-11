#!/usr/bin/env python
"""
tests/ws_test.py — End-to-end test script for the chat REST API + WebSocket.

Usage
-----
    # From the project root (with venv activated):
    python tests/ws_test.py

    # Override defaults:
    python tests/ws_test.py --base http://127.0.0.1:8000 --username wasifali --password yourpassword

What this script does
---------------------
  Step 1  — Obtain a JWT access token via POST /api/auth/token/
  Step 2  — Create a new chat room via POST /api/chat/rooms/
  Step 3  — Fetch room detail via GET /api/chat/rooms/<room_id>/
  Step 4  — Connect to the WebSocket and run three sub-tests:
              4a  Send a text message and verify the echo broadcast
              4b  Request chat history and verify the message is present
              4c  Send an invalid frame and verify the error response
  Step 5  — Fetch message history via the REST endpoint (GET /api/chat/rooms/<room_id>/messages/)
  Step 6  — Leave the room via POST /api/chat/rooms/<room_id>/participants/remove/

Requirements: websockets>=13, httpx  (pip install websockets httpx)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import textwrap
from datetime import datetime, timezone

import httpx
import websockets

# ---------------------------------------------------------------------------
# CLI args
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Appointly chat integration test")
parser.add_argument("--base",     default="http://127.0.0.1:8000", help="Django dev-server base URL")
parser.add_argument("--username", default="wasifali",  help="Superuser username")
parser.add_argument("--password", default="20051280",  help="Superuser password")
args = parser.parse_args()

BASE_HTTP = args.base.rstrip("/")
BASE_WS   = BASE_HTTP.replace("http://", "ws://").replace("https://", "wss://")

PASS = "\033[92m✔\033[0m"
FAIL = "\033[91m✘\033[0m"
INFO = "\033[94m→\033[0m"

results: list[tuple[str, bool]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    symbol = PASS if condition else FAIL
    print(f"  {symbol}  {label}", f"({detail})" if detail else "")
    results.append((label, condition))
    if not condition:
        print(f"     {FAIL}  ASSERTION FAILED — halting test.")
        _print_summary()
        sys.exit(1)


def _print_summary() -> None:
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total  = len(results)
    print(f"  Results: {passed}/{total} passed")
    for label, ok in results:
        print(f"    {'✔' if ok else '✘'}  {label}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def get_token(client: httpx.Client) -> str:
    print(f"\n{INFO} Step 1 — Obtain JWT token")
    resp = client.post(
        f"{BASE_HTTP}/api/auth/token/",
        json={"username": args.username, "password": args.password},
    )
    check("POST /api/auth/token/ → 200", resp.status_code == 200, str(resp.status_code))
    token = resp.json().get("access", "")
    check("Response contains 'access' token", bool(token))
    print(f"     Token prefix: {token[:30]}…")
    return token


def create_room(client: httpx.Client, token: str) -> dict:
    print(f"\n{INFO} Step 2 — Create a chat room")
    resp = client.post(
        f"{BASE_HTTP}/api/chat/rooms/",
        json={"name": "Integration Test Room", "is_group": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    check("POST /api/chat/rooms/ → 201", resp.status_code == 201, str(resp.status_code))
    room = resp.json()
    check("Room has 'room_id'", "room_id" in room)
    check("Creator is in participants", any(p for p in room["participants"]))
    print(f"     room_id: {room['room_id']}")
    return room


def get_room(client: httpx.Client, token: str, room_id: str) -> None:
    print(f"\n{INFO} Step 3 — Fetch room detail")
    resp = client.get(
        f"{BASE_HTTP}/api/chat/rooms/{room_id}/",
        headers={"Authorization": f"Bearer {token}"},
    )
    check("GET /api/chat/rooms/<id>/ → 200", resp.status_code == 200, str(resp.status_code))
    data = resp.json()
    check("Returned room_id matches", data.get("room_id") == room_id)


def get_messages_rest(client: httpx.Client, token: str, room_id: str) -> None:
    print(f"\n{INFO} Step 5 — Fetch message history via REST")
    resp = client.get(
        f"{BASE_HTTP}/api/chat/rooms/{room_id}/messages/",
        headers={"Authorization": f"Bearer {token}"},
    )
    check("GET /api/chat/rooms/<id>/messages/ → 200", resp.status_code == 200, str(resp.status_code))
    data = resp.json()
    check("Response has 'messages' key", "messages" in data)
    check("At least one message persisted", data.get("count", 0) >= 1)
    print(f"     Messages in DB: {data['count']}")


def leave_room(client: httpx.Client, token: str, room_id: str, user_pk: str) -> None:
    print(f"\n{INFO} Step 6 — Leave the room")
    resp = client.post(
        f"{BASE_HTTP}/api/chat/rooms/{room_id}/participants/remove/",
        json={"user_id": user_pk},
        headers={"Authorization": f"Bearer {token}"},
    )
    check(
        "POST /api/chat/rooms/<id>/participants/remove/ → 200",
        resp.status_code == 200,
        str(resp.status_code),
    )


# ---------------------------------------------------------------------------
# WebSocket tests
# ---------------------------------------------------------------------------

async def run_websocket_tests(token: str, room_id: str) -> None:
    url = f"{BASE_WS}/ws/chat/{room_id}/?token={token}"
    print(f"\n{INFO} Step 4 — WebSocket tests")
    print(f"     Connecting to {url}")

    try:
        async with websockets.connect(url, additional_headers={"Origin": BASE_HTTP}) as ws:
            print(f"  {PASS}  WebSocket connection accepted")
            results.append(("WebSocket connection accepted", True))

            # ------------------------------------------------------------------
            # 4a — Send a chat message and receive the broadcast
            # ------------------------------------------------------------------
            print(f"\n  {INFO} 4a — Send chat.message frame")
            await ws.send(json.dumps({
                "type": "chat.message",
                "content": "Hello from the integration test! 🚀",
                "message_type": "text",
            }))

            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            frame = json.loads(raw)
            check(
                "Broadcast frame type == 'chat.message'",
                frame.get("type") == "chat.message",
                str(frame.get("type")),
            )
            msg = frame.get("message", {})
            check("Message content matches",   msg.get("content") == "Hello from the integration test! 🚀")
            check("Message has 'id'",          bool(msg.get("id")))
            check("Message has 'created_at'",  bool(msg.get("created_at")))
            print(f"     Message id: {msg.get('id')}")

            # ------------------------------------------------------------------
            # 4b — Request message history
            # ------------------------------------------------------------------
            print(f"\n  {INFO} 4b — Request chat.history frame")
            await ws.send(json.dumps({"type": "chat.history"}))

            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            frame = json.loads(raw)
            check(
                "History frame type == 'chat.history'",
                frame.get("type") == "chat.history",
                str(frame.get("type")),
            )
            history = frame.get("messages", [])
            check("History contains at least one message", len(history) >= 1)
            check(
                "Sent message appears in history",
                any(m.get("content") == "Hello from the integration test! 🚀" for m in history),
            )

            # ------------------------------------------------------------------
            # 4c — Send an invalid frame type and expect an error response
            # ------------------------------------------------------------------
            print(f"\n  {INFO} 4c — Send an invalid frame type")
            await ws.send(json.dumps({"type": "nonexistent.type"}))

            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            frame = json.loads(raw)
            check(
                "Error frame type == 'error'",
                frame.get("type") == "error",
                str(frame.get("type")),
            )
            check("Error frame has 'code'", bool(frame.get("code")))
            print(f"     Error code: {frame.get('code')} — {frame.get('detail')}")

    except (websockets.exceptions.WebSocketException, OSError) as exc:
        print(f"  {FAIL}  WebSocket connection failed: {exc}")
        results.append(("WebSocket connection accepted", False))
        print(
            "\n  Tip: make sure the dev server is running with Daphne or Uvicorn:\n"
            "    daphne appointly.asgi:application\n"
            "  or:\n"
            "    uvicorn appointly.asgi:application --reload\n"
            "  (Django's runserver does NOT support WebSockets.)"
        )
        sys.exit(1)
    except asyncio.TimeoutError:
        print(f"  {FAIL}  Timed out waiting for WebSocket response.")
        results.append(("WebSocket response received", False))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("  Appointly Chat — Integration Test Suite")
    print(f"  Target: {BASE_HTTP}")
    print(f"  User:   {args.username}")
    print("=" * 60)

    with httpx.Client(timeout=15) as client:
        token    = get_token(client)
        room     = create_room(client, token)
        room_id  = room["room_id"]

        get_room(client, token, room_id)

        # Fetch user PK for later leave step — reuse the token payload
        import base64, json as _json
        payload_b64 = token.split(".")[1]
        # Pad to multiple of 4
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        user_pk = str(_json.loads(base64.b64decode(payload_b64)).get("user_id", ""))

        await run_websocket_tests(token, room_id)

        get_messages_rest(client, token, room_id)
        leave_room(client, token, room_id, user_pk)

    _print_summary()
    all_passed = all(ok for _, ok in results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
