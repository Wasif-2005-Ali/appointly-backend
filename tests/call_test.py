#!/usr/bin/env python
"""
tests/call_test.py — End-to-end integration test for WebRTC signaling & Call REST API.

Flow tested
-----------
1. Authenticate caller (User A) and callee (User B) via JWT.
   (Automatically creates a test callee account if one doesn't exist).
2. Callee connects to personal notification channel: ws://<host>/ws/notify/
3. Caller connects to call channel: ws://<host>/ws/call/<call_id>/
4. Caller sends 'call.initiate' frame for callee.
5. Callee receives 'call.incoming' notification on /ws/notify/.
6. Callee connects to call channel: ws://<host>/ws/call/<call_id>/
7. Callee sends 'call.accept'.
8. Both receive 'call.accepted' state.
9. Caller sends 'call.sdp_offer' -> Callee receives 'call.sdp_offer'.
10. Callee sends 'call.sdp_answer' -> Caller receives 'call.sdp_answer'.
11. Peer-to-peer ICE candidate exchange verified in both directions.
12. Caller sends 'call.end' -> Both receive 'call.ended' with duration.
13. Verify call history via REST: GET /api/call/history/

Usage
-----
    python tests/call_test.py
    python tests/call_test.py --base http://127.0.0.1:8000 --caller-username admin --caller-password admin
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from typing import Optional

import httpx
import websockets

# Setup Django environment for test user setup
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "appointly.settings")

from asgiref.sync import sync_to_async

try:
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    DJANGO_AVAILABLE = True
except Exception:
    DJANGO_AVAILABLE = False


parser = argparse.ArgumentParser(description="Appointly WebRTC signaling test")
parser.add_argument("--base", default="http://127.0.0.1:8000", help="Base HTTP URL")
parser.add_argument("--caller-user", default="admin", help="Caller username")
parser.add_argument("--caller-pass", default="admin", help="Caller password")
parser.add_argument("--callee-user", default="callee_test", help="Callee username")
parser.add_argument("--callee-pass", default="calleepass123", help="Callee password")
args = parser.parse_args()

BASE_HTTP = args.base.rstrip("/")
BASE_WS   = BASE_HTTP.replace("http://", "ws://").replace("https://", "wss://")

PASS = "\033[92m[OK]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m-->\033[0m"

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
        print(f"    {'PASS' if ok else 'FAIL'}  {label}")
    print("=" * 60)


@sync_to_async
def ensure_users() -> tuple[str, str]:
    """Ensure both caller and callee exist in the DB (safe for async context)."""
    if not DJANGO_AVAILABLE:
        return "", ""

    User = get_user_model()
    # Ensure caller exists or warn
    caller = User.objects.filter(username=args.caller_user).first()
    if not caller:
        # If default caller doesn't exist, create it
        caller = User.objects.create_user(username=args.caller_user, password=args.caller_pass)
        print(f"{INFO} Created caller user '{args.caller_user}'")

    # Ensure callee exists
    callee = User.objects.filter(username=args.callee_user).first()
    if not callee:
        callee = User.objects.create_user(username=args.callee_user, password=args.callee_pass)
        print(f"{INFO} Created callee user '{args.callee_user}'")

    return str(caller.pk), str(callee.pk)


def get_jwt(client: httpx.Client, username: str, password: str) -> tuple[str, str]:
    resp = client.post(
        f"{BASE_HTTP}/api/auth/token/",
        json={"username": username, "password": password},
    )
    check(f"Obtain JWT for {username}", resp.status_code == 200, f"status: {resp.status_code}")
    data = resp.json()
    token = data.get("access", "")
    check(f"Access token received for {username}", bool(token))

    # Parse user id from token
    import base64
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (4 - len(payload_b64) % 4)
    user_id = str(json.loads(base64.b64decode(payload_b64)).get("user_id", ""))
    return token, user_id


async def run_signaling_flow(
    token_caller: str,
    caller_id: str,
    token_callee: str,
    callee_id: str,
) -> None:
    call_id = uuid.uuid4().hex  # 32-char hex string
    ws_notify_url = f"{BASE_WS}/ws/notify/?token={token_callee}"
    ws_caller_url = f"{BASE_WS}/ws/call/{call_id}/?token={token_caller}"
    ws_callee_url = f"{BASE_WS}/ws/call/{call_id}/?token={token_callee}"

    print(f"\n{INFO} Step 2 — Callee connects to /ws/notify/")
    async with websockets.connect(ws_notify_url, additional_headers={"Origin": BASE_HTTP}) as ws_notify:
        check("Callee connected to /ws/notify/", True)

        print(f"\n{INFO} Step 3 — Caller connects to /ws/call/{call_id}/")
        async with websockets.connect(ws_caller_url, additional_headers={"Origin": BASE_HTTP}) as ws_caller:
            check("Caller connected to call channel", True)

            print(f"\n{INFO} Step 4 — Caller initiates call to Callee ({callee_id})")
            await ws_caller.send(json.dumps({
                "type": "call.initiate",
                "callee_id": callee_id,
                "call_type": "video",
            }))

            # Caller receives initiated confirmation
            raw_caller_init = await asyncio.wait_for(ws_caller.recv(), timeout=5.0)
            init_frame = json.loads(raw_caller_init)
            check("Caller got 'call.initiated'", init_frame.get("type") == "call.initiated")
            check("Session status is ringing", init_frame.get("session", {}).get("status") == "ringing")

            # Callee receives incoming call on /ws/notify/
            print(f"\n{INFO} Step 5 — Callee receives 'call.incoming' on /ws/notify/")
            raw_callee_incoming = await asyncio.wait_for(ws_notify.recv(), timeout=5.0)
            incoming_frame = json.loads(raw_callee_incoming)
            check("Callee got 'call.incoming'", incoming_frame.get("type") == "call.incoming")
            check("Incoming call_id matches", incoming_frame.get("call_id") == call_id)

            print(f"\n{INFO} Step 6 — Callee connects to /ws/call/{call_id}/")
            async with websockets.connect(ws_callee_url, additional_headers={"Origin": BASE_HTTP}) as ws_callee:
                check("Callee connected to call channel", True)

                # Callee joining triggers 'call.peer_connected' on caller WS
                raw_caller_peer = await asyncio.wait_for(ws_caller.recv(), timeout=5.0)
                peer_frame = json.loads(raw_caller_peer)
                check("Caller saw callee join ('call.peer_connected')", peer_frame.get("type") == "call.peer_connected")

                print(f"\n{INFO} Step 7 — Callee accepts call")
                await ws_callee.send(json.dumps({"type": "call.accept"}))

                # Both should receive call.accepted
                callee_accepted = json.loads(await asyncio.wait_for(ws_callee.recv(), timeout=5.0))
                caller_accepted = json.loads(await asyncio.wait_for(ws_caller.recv(), timeout=5.0))
                check("Callee received 'call.accepted'", callee_accepted.get("type") == "call.accepted")
                check("Caller received 'call.accepted'", caller_accepted.get("type") == "call.accepted")
                check("State is 'connected'", callee_accepted.get("session", {}).get("status") == "connected")

                print(f"\n{INFO} Step 8 — WebRTC SDP Offer / Answer Exchange")
                # Caller sends SDP offer
                sample_offer = {"type": "offer", "sdp": "v=0\r\no=- 12345 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"}
                await ws_caller.send(json.dumps({
                    "type": "call.sdp_offer",
                    "sdp": sample_offer,
                }))

                # Callee receives SDP offer
                callee_sdp = json.loads(await asyncio.wait_for(ws_callee.recv(), timeout=5.0))
                check("Callee received relayed 'call.sdp_offer'", callee_sdp.get("type") == "call.sdp_offer")
                check("SDP matches offer", callee_sdp.get("sdp", {}).get("type") == "offer")

                # Callee sends SDP answer
                sample_answer = {"type": "answer", "sdp": "v=0\r\no=- 67890 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"}
                await ws_callee.send(json.dumps({
                    "type": "call.sdp_answer",
                    "sdp": sample_answer,
                }))

                # Caller receives SDP answer
                caller_sdp = json.loads(await asyncio.wait_for(ws_caller.recv(), timeout=5.0))
                check("Caller received relayed 'call.sdp_answer'", caller_sdp.get("type") == "call.sdp_answer")
                check("SDP matches answer", caller_sdp.get("sdp", {}).get("type") == "answer")

                print(f"\n{INFO} Step 9 — WebRTC ICE Candidate Exchange")
                # Caller sends candidate
                cand_a = {"candidate": "candidate:1 1 UDP 2130706431 192.168.1.1 5000 typ host", "sdpMid": "0"}
                await ws_caller.send(json.dumps({
                    "type": "call.ice_candidate",
                    "candidate": cand_a,
                }))
                callee_cand = json.loads(await asyncio.wait_for(ws_callee.recv(), timeout=5.0))
                check("Callee received ICE candidate", callee_cand.get("type") == "call.ice_candidate")

                # Callee sends candidate
                cand_b = {"candidate": "candidate:2 1 UDP 2130706431 192.168.1.2 5001 typ host", "sdpMid": "0"}
                await ws_callee.send(json.dumps({
                    "type": "call.ice_candidate",
                    "candidate": cand_b,
                }))
                caller_cand = json.loads(await asyncio.wait_for(ws_caller.recv(), timeout=5.0))
                check("Caller received ICE candidate", caller_cand.get("type") == "call.ice_candidate")

                print(f"\n{INFO} Step 10 — Terminate Call (call.end)")
                await ws_caller.send(json.dumps({"type": "call.end"}))

                caller_ended = json.loads(await asyncio.wait_for(ws_caller.recv(), timeout=5.0))
                callee_ended = json.loads(await asyncio.wait_for(ws_callee.recv(), timeout=5.0))
                check("Caller got 'call.ended'", caller_ended.get("type") == "call.ended")
                check("Callee got 'call.ended'", callee_ended.get("type") == "call.ended")
                check("Final status is 'ended'", caller_ended.get("session", {}).get("status") == "ended")


def check_rest_history(client: httpx.Client, token: str) -> None:
    print(f"\n{INFO} Step 11 — Check Call History via REST API")
    resp = client.get(
        f"{BASE_HTTP}/api/call/history/",
        headers={"Authorization": f"Bearer {token}"},
    )
    check("GET /api/call/history/ -> 200", resp.status_code == 200, str(resp.status_code))
    history = resp.json()
    check("History is non-empty list", isinstance(history, list) and len(history) > 0)
    check("Latest call status is 'ended'", history[0].get("status") == "ended")
    print(f"     Call ID: {history[0].get('call_id')}, Duration: {history[0].get('duration_seconds')}s")


async def main() -> None:
    print("=" * 60)
    print("  Appointly Call App — WebRTC Signaling Integration Test")
    print(f"  Target: {BASE_HTTP}")
    print("=" * 60)

    await ensure_users()

    with httpx.Client(timeout=10.0) as client:
        print(f"\n{INFO} Step 1 — Authenticate Caller and Callee")
        token_caller, caller_id = get_jwt(client, args.caller_user, args.caller_pass)
        token_callee, callee_id = get_jwt(client, args.callee_user, args.callee_pass)

        await run_signaling_flow(token_caller, caller_id, token_callee, callee_id)
        check_rest_history(client, token_caller)

    _print_summary()


if __name__ == "__main__":
    asyncio.run(main())
