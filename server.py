import os
import re
import asyncio
import hmac
from dark_panel import DarkPanel
from datetime import datetime
import aiohttp
from aiohttp import web
from telethon import TelegramClient, errors
from telethon.sessions import StringSession

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load .env file if present (for local runs; Render injects env vars directly)
_env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

API_ID = int(os.environ.get("TG_API_ID", "2040"))
API_HASH = os.environ.get("TG_API_HASH", "b18441a1ff607e10a989891a5462e627")
PORT = int(os.environ.get("PORT", "8500"))

FIREBASE_ADPE_URL = "https://shoaib-gaurd-default-rtdb.firebaseio.com/adpe_numbers"

SESSION_STRING = os.environ.get("TG_SESSION_STRING", "").strip().strip('"').strip("'")
SESSION_PATH = os.path.join(BASE_DIR, "main_account")

if SESSION_STRING:
    try:
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    except Exception as _se:
        print(f"Invalid TG_SESSION_STRING ({_se}), falling back to file session", flush=True)
        client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
else:
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

http_session: aiohttp.ClientSession = None
pending_auth = {}
ACCESS_TOKEN = os.environ.get("OTP_ACCESS_TOKEN", "").strip()


async def claim_number(phone):
    """Reserve only absent records, atomically; database errors stop automation."""
    url = f"{FIREBASE_ADPE_URL}/{phone}.json"
    async with http_session.get(url, headers={"X-Firebase-ETag": "true"}, timeout=8) as resp:
        resp.raise_for_status()
        existing = await resp.json()
        etag = resp.headers.get("ETag")
    if existing is not None:
        return False
    if not etag:
        raise RuntimeError("Firebase did not return a reservation ETag")
    now = format_adpe_time()
    record = dict(raw="+91 " + phone, status="received", time=now, firstSeen=now, platform="adpe")
    async with http_session.put(url, headers={"If-Match": etag}, json=record, timeout=8) as resp:
        if resp.status == 412:
            return False
        resp.raise_for_status()
        return True


dark_panel = DarkPanel(client, claim_number)


def format_adpe_time():
    d = datetime.now()
    return d.strftime("%#d %b, %#I:%M %p") if os.name == "nt" else d.strftime("%-d %b, %-I:%M %p")


async def check_adpe_firebase(phone: str) -> dict | None:
    clean = re.sub(r"\D", "", phone)[-10:]
    if len(clean) < 10:
        return None
    try:
        async with http_session.get(f"{FIREBASE_ADPE_URL}/{clean}.json", timeout=8) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception:
        pass
    return None


async def save_adpe_firebase(phone: str):
    clean = re.sub(r"\D", "", phone)[-10:]
    if len(clean) < 10:
        return False
    now_str = format_adpe_time()
    record = {
        "raw": "+91 " + clean,
        "status": "received",
        "time": now_str,
        "firstSeen": now_str,
        "platform": "adpe",
    }
    try:
        async with http_session.put(f"{FIREBASE_ADPE_URL}/{clean}.json", json=record, timeout=8) as resp:
            return resp.status == 200
    except Exception:
        return False


async def get_adpe_count() -> int:
    try:
        async with http_session.get(f"{FIREBASE_ADPE_URL}.json?shallow=true", timeout=8) as resp:
            if resp.status == 200:
                data = await resp.json()
                return len(data) if isinstance(data, dict) else 0
    except Exception:
        pass
    return 0


def extract_phone_and_otps(text: str):
    if not text:
        return None, []

    phone = None
    phone_match = re.search(
        r"(?:Phone\s*Number|Number|Mobile|Phone)\s*[:\-]?\s*(\+?\d[\d\s\-]{8,14}\d)",
        text,
        re.IGNORECASE,
    )
    if phone_match:
        digits = re.sub(r"\D", "", phone_match.group(1))
        if len(digits) >= 10:
            phone = digits[-10:]
    else:
        m = re.search(r"\b([6-9]\d{9})\b", text)
        if m:
            phone = m.group(1)

    otps = []
    for line in text.splitlines():
        otp_m = re.search(r"(?:OTP|code|pin)\s*(?:is|:|\-)?\s*(\d{4,8})\b", line, re.IGNORECASE)
        if otp_m:
            code = otp_m.group(1)
            if code not in [o["code"] for o in otps]:
                otps.append({"code": code, "context": line.strip()})

    return phone, otps


async def serialize_message(msg):
    if not msg:
        return None
    buttons = []
    if msg.buttons:
        for r_idx, row in enumerate(msg.buttons):
            btn_row = []
            for c_idx, btn in enumerate(row):
                btn_row.append({
                    "text": btn.text,
                    "row": r_idx,
                    "col": c_idx,
                    "has_url": bool(getattr(btn, "url", None)),
                })
            buttons.append(btn_row)

    text = msg.raw_text or ""
    phone, otps = extract_phone_and_otps(text)
    existing = await check_adpe_firebase(phone) if phone else None

    return {
        "id": msg.id,
        "text": text,
        "date": msg.date.strftime("%Y-%m-%d %H:%M:%S") if msg.date else "",
        "buttons": buttons,
        "phone": phone,
        "is_duplicate": existing is not None,
        "auto_saved": False,
        "existing_info": existing,
        "otps": otps,
    }


async def auto_save_current_number(serialized_msgs: list):
    """Automatically save the current fresh number to Firebase DB so duplicates are prevented next time."""
    for m in serialized_msgs:
        if m and m.get("phone"):
            if not m["is_duplicate"]:
                saved = await save_adpe_firebase(m["phone"])
                if saved:
                    m["auto_saved"] = True
            break


@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(
            status=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            },
        )
    if request.path.startswith("/api/") and ACCESS_TOKEN and not hmac.compare_digest(
        request.headers.get("Authorization", ""), "Bearer " + ACCESS_TOKEN
    ):
        resp = web.json_response({"ok": False, "error": "Server access token required"}, status=401)
    else:
        resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp


async def handle_index(request):
    return web.FileResponse(os.path.join(BASE_DIR, "index.html"))


async def handle_auth_status(request):
    try:
        return await asyncio.wait_for(auth_status_response(), timeout=20)
    except asyncio.TimeoutError:
        return web.json_response({"ok": False, "error": "Telegram connection timed out. Check backend connectivity and retry."}, status=504)
    except Exception:
        return web.json_response({"ok": False, "error": "Telegram status check failed. Check backend logs and retry."}, status=503)


async def auth_status_response():
    if not client.is_connected():
        await client.connect()
    authorized = await client.is_user_authorized()
    user_info = None
    if authorized:
        me = await client.get_me()
        user_info = {
            "id": me.id,
            "first_name": me.first_name or "",
            "username": me.username or "",
            "phone": me.phone or "",
        }
    return web.json_response({
        "authorized": authorized,
        "user": user_info,
        "used_count": await get_adpe_count(),
    })


async def handle_session_string(request):
    if not await client.is_user_authorized():
        return web.json_response({"ok": False, "error": "Not logged in"}, status=401)
    ss = StringSession.save(client.session)
    return web.json_response({"ok": True, "session_string": ss})


async def handle_send_code(request):
    data = await request.json()
    phone = data.get("phone", "").strip()
    if not phone:
        return web.json_response({"ok": False, "error": "Please enter a phone number"}, status=400)
    if not phone.startswith("+"):
        phone = ("+91" + phone) if len(phone) == 10 else ("+" + phone)

    try:
        if not client.is_connected():
            await client.connect()
        sent = await client.send_code_request(phone)
        pending_auth["phone"] = phone
        pending_auth["phone_code_hash"] = sent.phone_code_hash
        return web.json_response({"ok": True, "phone": phone})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def handle_sign_in(request):
    data = await request.json()
    code = data.get("code", "").strip()
    password = data.get("password", "").strip()
    phone = pending_auth.get("phone") or data.get("phone", "").strip()
    phone_code_hash = pending_auth.get("phone_code_hash")

    if not client.is_connected():
        await client.connect()

    try:
        if password and not code:
            await client.sign_in(password=password)
        else:
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            except errors.SessionPasswordNeededError:
                if password:
                    await client.sign_in(password=password)
                else:
                    return web.json_response({"ok": False, "need_password": True, "error": "2FA password required"})
        me = await client.get_me()
        return web.json_response({
            "ok": True,
            "user": {"first_name": me.first_name, "phone": me.phone, "username": me.username},
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def handle_logout(request):
    await dark_panel.stop()
    try:
        if await client.is_user_authorized():
            await client.log_out()
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def handle_dialogs(request):
    if not await client.is_user_authorized():
        return web.json_response({"ok": False, "error": "Not logged in"}, status=401)
    bots = []
    async for d in client.iter_dialogs(limit=60):
        ent = d.entity
        if getattr(ent, "bot", False):
            bots.append({
                "id": ent.id,
                "name": d.name or "Bot",
                "username": getattr(ent, "username", "") or "",
            })
    return web.json_response({"ok": True, "bots": bots})


async def resolve_bot(bot_ref: str):
    bot_ref = bot_ref.strip()
    if bot_ref.lstrip("-").isdigit():
        return int(bot_ref)
    return bot_ref


async def handle_bot_messages(request):
    if not await client.is_user_authorized():
        return web.json_response({"ok": False, "error": "Not logged in"}, status=401)
    bot_ref = request.query.get("bot", "").strip()
    if not bot_ref:
        return web.json_response({"ok": False, "error": "Please select a bot"}, status=400)
    try:
        entity = await client.get_entity(await resolve_bot(bot_ref))
        msgs = await client.get_messages(entity, limit=6)
        serialized = [await serialize_message(m) for m in msgs if m]
        if getattr(entity, "username", "").lower() != "dark_panel_83_bot":
            await auto_save_current_number(serialized)
        return web.json_response({
            "ok": True,
            "messages": serialized,
            "used_count": await get_adpe_count(),
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def handle_bot_click(request):
    if dark_panel.state["running"]:
        return web.json_response({"ok": False, "error": "Stop automation before manual navigation"}, status=409)
    if not await client.is_user_authorized():
        return web.json_response({"ok": False, "error": "Not logged in"}, status=401)
    data = await request.json()
    bot_ref = data.get("bot", "").strip()
    msg_id = data.get("msg_id")
    row = data.get("row")
    col = data.get("col")
    text_cmd = data.get("text")

    try:
        entity = await client.get_entity(await resolve_bot(bot_ref))
        if text_cmd:
            await client.send_message(entity, text_cmd)
        elif msg_id is not None and row is not None and col is not None:
            msg = await client.get_messages(entity, ids=int(msg_id))
            if msg and msg.buttons:
                await msg.click(int(row), int(col))
        await asyncio.sleep(1.5)
        msgs = await client.get_messages(entity, limit=6)
        serialized = [await serialize_message(m) for m in msgs if m]
        if getattr(entity, "username", "").lower() != "dark_panel_83_bot":
            await auto_save_current_number(serialized)
        return web.json_response({
            "ok": True,
            "messages": serialized,
            "used_count": await get_adpe_count(),
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def handle_find_fresh(request):
    if dark_panel.state["running"]:
        return web.json_response({"ok": False, "error": "Stop automation before manual navigation"}, status=409)
    if not await client.is_user_authorized():
        return web.json_response({"ok": False, "error": "Not logged in"}, status=401)

    data = await request.json()
    bot_ref = data.get("bot", "").strip()
    btn_keyword = data.get("button_text", "").strip().lower()
    max_tries = int(data.get("max_tries", 12))

    try:
        entity = await client.get_entity(await resolve_bot(bot_ref))
        for attempt in range(max_tries):
            msgs = await client.get_messages(entity, limit=5)
            latest = msgs[0] if msgs else None
            if not latest:
                break

            s = await serialize_message(latest)
            if attempt > 0 and s["phone"] and not s["is_duplicate"]:
                serialized = [await serialize_message(m) for m in msgs]
                await auto_save_current_number(serialized)
                return web.json_response({
                    "ok": True,
                    "found_fresh": True,
                    "attempts": attempt,
                    "message": serialized[0],
                    "messages": serialized,
                    "used_count": await get_adpe_count(),
                })

            clicked = False
            for m in msgs:
                if m.buttons:
                    for r_idx, row in enumerate(m.buttons):
                        for c_idx, btn in enumerate(row):
                            if btn_keyword and btn_keyword in btn.text.lower():
                                await m.click(r_idx, c_idx)
                                clicked = True
                                break
                        if clicked:
                            break
                if clicked:
                    break

            if not clicked:
                return web.json_response({
                    "ok": False,
                    "error": f"Button '{btn_keyword}' not found.",
                    "messages": [await serialize_message(m) for m in msgs],
                })

            await asyncio.sleep(2.0)

        msgs = await client.get_messages(entity, limit=5)
        serialized = [await serialize_message(m) for m in msgs]
        await auto_save_current_number(serialized)
        return web.json_response({
            "ok": True,
            "found_fresh": False,
            "attempts": max_tries,
            "messages": serialized,
            "used_count": await get_adpe_count(),
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def on_startup(app):
    global http_session
    if os.environ.get("RENDER") and (not ACCESS_TOKEN or not SESSION_STRING):
        raise RuntimeError("Render requires OTP_ACCESS_TOKEN and TG_SESSION_STRING")
    http_session = aiohttp.ClientSession()
    try:
        await asyncio.wait_for(client.connect(), timeout=15)
        print("Telegram client connected on startup.", flush=True)
    except Exception as e:
        print(f"Telegram startup connect warning: {e}", flush=True)


async def handle_automation(request):
    if not await client.is_user_authorized():
        return web.json_response({"ok": False, "error": "Telegram login required"}, status=401)
    if request.method == "POST":
        data = await request.json()
        if data.get("action") == "stop":
            async with dark_panel.lock:
                await dark_panel.stop()
        elif data.get("action") == "start":
            await dark_panel.start()
        else:
            return web.json_response({"ok": False, "error": "Invalid action"}, status=400)
    return web.json_response({"ok": True, **dark_panel.state})


async def handle_health(request):
    return web.json_response({"ok": True})


async def handle_check_number(request):
    data = await request.json() if request.method == 'POST' else request.query
    raw = str(data.get('phone', ''))
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    if not re.fullmatch(r'[6-9]\d{9}', digits):
        return web.json_response({'ok': False, 'error': 'Enter a valid 10-digit Indian number'}, status=400)
    try:
        if request.method == 'POST':
            saved = await claim_number(digits)
            return web.json_response({'ok': True, 'phone': digits,
                                      'is_duplicate': not saved, 'saved': saved})
        async with http_session.get(f'{FIREBASE_ADPE_URL}/{digits}.json', timeout=8) as resp:
            resp.raise_for_status()
            record = await resp.json()
        return web.json_response({'ok': True, 'phone': digits, 'is_duplicate': record is not None})
    except Exception:
        return web.json_response({'ok': False, 'error': 'Database request failed. Check/save could not be confirmed; retry.'}, status=503)


async def on_cleanup(app):
    await dark_panel.stop()
    if http_session:
        await http_session.close()
    await client.disconnect()


def create_app():
    app = web.Application(middlewares=[cors_middleware])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    app.router.add_get("/", handle_index)
    app.router.add_get("/health", handle_health)
    app.router.add_get('/api/numbers/check', handle_check_number)
    app.router.add_post('/api/numbers/check', handle_check_number)
    app.router.add_get("/api/dark-panel", handle_automation)
    app.router.add_post("/api/dark-panel", handle_automation)
    app.router.add_get("/api/auth/status", handle_auth_status)
    app.router.add_get("/api/auth/session_string", handle_session_string)
    app.router.add_post("/api/auth/send_code", handle_send_code)
    app.router.add_post("/api/auth/sign_in", handle_sign_in)
    app.router.add_post("/api/auth/logout", handle_logout)
    app.router.add_get("/api/dialogs", handle_dialogs)
    app.router.add_get("/api/bot/messages", handle_bot_messages)
    app.router.add_post("/api/bot/click", handle_bot_click)
    app.router.add_post("/api/bot/find_fresh", handle_find_fresh)
    return app


if __name__ == "__main__":
    print(f"OTP Bot running on http://0.0.0.0:{PORT}")
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
