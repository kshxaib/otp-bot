"""Single server-owned Dark Panel navigation and monitoring task."""
import asyncio
import re
import time
import unicodedata
from datetime import datetime, timezone

BOT = "Dark_Panel_83_bot"


def buttons(message):
    if message is None:
        return []
    return [(r, c, b) for r, row in enumerate(message.buttons or [])
            for c, b in enumerate(row) if not getattr(b, "url", None)]


def button_text(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    text = ''.join(c for c in text if unicodedata.category(c) != 'Cf')
    return ' '.join(re.findall(r'\w+', text))


def number(text):
    match = re.search(r"(?<!\d)(?:\+?91[ -]?)?([6-9]\d{9})(?!\d)", text)
    return match.group(1) if match else None


def device_phone(message):
    """Only a device detail screen identifies the selected phone."""
    if not message or not any('refresh sms' in button_text(b.text)
                              for _, _, b in buttons(message)):
        return None
    text = unicodedata.normalize('NFKC', message.raw_text or '')
    match = re.search(r'Phone\s*Number\s*:\s*([+\d -]+)', text, re.I)
    return number(match.group(1)) if match else None


def empty_panel(message):
    text = button_text(message.raw_text or '') if message else ''
    return any(marker in text for marker in (
        'no active devices', 'no online devices', 'no numbers available',
        'online devices 0', '0 active online',
        'abhi koi active sim online nahi mili'))


def sms_entries(text):
    # Ignore changing screen timestamps and list positions; fingerprint SMS content.
    entries = {}
    for block in re.split(r"#\d+\s*", text):
        if "From:" not in block:
            continue
        match = re.search(r"OTP\s*:\s*(\d{4,8})\b", block, re.I)
        if match:
            stable = block.split("SMS #")[0].split("Copy OTP")[0].strip()
            entries[stable] = match.group(1)
    return entries


class DarkPanel:
    def __init__(self, client, claim):
        self.client, self.claim = client, claim
        self.task = None
        self.lock = asyncio.Lock()
        self.state = dict(running=False, phase="idle", phone=None, history=[], error=None)

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.state.update(running=False, phase="stopped", phone=None)

    async def start(self):
        async with self.lock:
            if self.state['running'] and self.state['phase'] == 'searching':
                return
            await self.stop()
            self.state.update(running=True, phase="searching", error=None, phone=None, last_result="")
            self.task = asyncio.create_task(self.run())

    async def screen(self):
        messages = await self.client.get_messages(self.entity, limit=8)
        return next((m for m in messages if not m.out and m.buttons), None)

    @staticmethod
    def signature(msg):
        return (msg.id, msg.raw_text, tuple((r, c, b.text, getattr(b, "data", None))
                                         for r, c, b in buttons(msg))) if msg else None

    async def changed(self, before):
        for _ in range(20):
            await asyncio.sleep(0.5)
            msg = await self.screen()
            if msg and self.signature(msg) != before:
                return msg
        raise RuntimeError("Bot did not update its screen. Try New Number again.")

    async def click(self, msg, r, c, unchanged=False):
        signature = self.signature(msg)
        await msg.click(r, c)
        if unchanged:
            for _ in range(4):
                await asyncio.sleep(0.5)
                current = await self.screen()
                if current and self.signature(current) != signature:
                    return current
            return current
        return await self.changed(signature)

    async def named(self, msg, label, unchanged=False):
        for r, c, b in buttons(msg):
            if button_text(label) in button_text(b.text):
                return await self.click(msg, r, c, unchanged)
        raise RuntimeError(f"Expected '{label}' button was not found.")

    async def return_to_panels(self, msg):
        clicked = set()
        for _ in range(30):
            labels = [(r, c, button_text(b.text)) for r, c, b in buttons(msg)]
            if any(text in ('fresh number', 'fresh today') for _, _, text in labels):
                return msg
            # Empty panels and device screens can expose different back routes.
            target = next(((r, c) for r, c, text in labels
                           if text in ('panels', 'back panels', 'back to panels',
                                       'back to numbers', 'back to menu', 'back menu',
                                       'live devices')), None)
            key = (self.signature(msg), target)
            if target is not None and key not in clicked:
                clicked.add(key)
                await msg.click(*target)
            await asyncio.sleep(0.5)
            msg = await self.screen()
        visible = ', '.join(b.text for _, _, b in buttons(msg))
        raise RuntimeError(f'Could not return to panel list. Available buttons: {visible or "none"}')

    async def wait_for_numbers(self):
        # Telegram can change the caption before the number keyboard arrives.
        # Never treat that intermediate screen as an empty/exhausted batch.
        await asyncio.sleep(3)
        for _ in range(24):
            msg = await self.screen()
            labels = [button_text(b.text) for _, _, b in buttons(msg)]
            if any(number(b.text) for _, _, b in buttons(msg)):
                return msg
            if empty_panel(msg) and any('panels' in label for label in labels):
                return msg
            await asyncio.sleep(0.5)
        raise RuntimeError('Numbers did not finish loading. Search stopped without skipping this panel; tap Find Number to retry.')

    async def open_device(self, listing, row, col, phone):
        before = self.signature(listing)
        await listing.click(row, col)
        for _ in range(30):
            await asyncio.sleep(0.5)
            detail = await self.screen()
            if not detail or self.signature(detail) == before:
                continue
            actual = device_phone(detail)
            if actual == phone:
                return detail
            if actual:
                raise RuntimeError('Bot selected a different device. Tap Find Number to retry.')
        raise RuntimeError('Selected device details did not arrive within 15 seconds. Tap Find Number to retry.')

    async def panels(self):
        before = self.signature(await self.screen())
        sent = await self.client.send_message(self.entity, "/start")
        # A bot may send an intermediate screen or attach its keyboard later.
        # Wait for the expected menu, not merely the first changed message.
        for _ in range(30):
            await asyncio.sleep(0.5)
            messages = await self.client.get_messages(self.entity, limit=12)
            for menu in messages:
                if menu.out or not menu.buttons:
                    continue
                if menu.id <= sent.id and not (
                    before and menu.id == before[0] and self.signature(menu) != before
                ):
                    continue
                if any('live devices' in button_text(b.text) for _, _, b in buttons(menu)):
                    return await self.named(menu, 'live devices')
        raise RuntimeError("LIVE DEVICES menu did not arrive within 15 seconds. Try Find Number again.")

    async def monitor(self, msg, phone):
        baseline = set(sms_entries(msg.raw_text or ""))
        deadline = time.monotonic() + 30
        self.state.update(phase="waiting", phone=phone, remaining=30)
        next_poll = time.monotonic() + 3
        while time.monotonic() < deadline:
            await asyncio.sleep(max(0, min(next_poll, deadline) - time.monotonic()))
            if time.monotonic() >= deadline:
                break
            msg = await self.named(msg, "refresh sms", unchanged=True)
            next_poll += 3
            if not msg or number(msg.raw_text or "") != phone:
                raise RuntimeError("Selected device changed during monitoring; stopped.")
            entries = sms_entries(msg.raw_text or "")
            fresh = [(key, code) for key, code in entries.items() if key not in baseline]
            if fresh:
                for _, code in fresh:
                    self.state["history"].insert(0, dict(phone=phone, code=code,
                        received_at=datetime.now(timezone.utc).isoformat()))
                self.state["history"] = self.state["history"][:20]
                self.state["last_result"] = f"OTP received for {phone}"
                return msg
            self.state["remaining"] = max(0, round(deadline - time.monotonic()))
        self.state["last_result"] = f"No new OTP in 30 seconds for {phone}"
        return msg

    async def run(self):
        try:
            self.entity = await self.client.get_entity(BOT)
            panel_menu = await self.panels()
            checked_numbers = set()
            self.state.update(checked=0, duplicates=0)
            # Callback data/coordinates distinguish panels with identical labels.
            panels = [(r, c, b.text, getattr(b, "data", None)) for r, c, b in buttons(panel_menu)
                      if "back" not in b.text.casefold()]
            for index, (r, c, label, callback) in enumerate(panels):
                if index:
                    panel_menu = await self.return_to_panels(msg)
                if callback is not None:
                    match = next(((rr, cc) for rr, cc, b in buttons(panel_menu)
                                  if getattr(b, "data", None) == callback), None)
                    if not match:
                        continue
                    r, c = match
                self.state.update(panel=index + 1, panels=len(panels), panel_name=label)
                msg = await self.click(panel_menu, r, c)
                msg = await self.wait_for_numbers()
                seen_batches = set()
                for _ in range(100):
                    if empty_panel(msg):
                        self.state['last_result'] = f'Panel {index + 1} has no online SIMs; checking next panel'
                        break
                    candidates = [(r, c, number(b.text)) for r, c, b in buttons(msg)
                                  if number(b.text)]
                    batch = tuple(sorted(p for _, _, p in candidates))
                    if batch in seen_batches:
                        break
                    seen_batches.add(batch)
                    for row, col, phone in candidates:
                        self.state.update(phase="searching", phone=None, remaining=0)
                        if phone in checked_numbers:
                            continue
                        checked_numbers.add(phone)
                        self.state['checked'] += 1
                        self.state['last_result'] = f"Checking panel {index + 1}/{len(panels)}; {self.state['checked']} numbers checked, {self.state['duplicates']} duplicates"
                        if not await self.claim(phone):
                            self.state['duplicates'] += 1
                            continue
                        position = next(((rr, cc) for rr, cc, b in buttons(msg)
                                         if number(b.text) == phone), None)
                        if position is None:
                            continue
                        row, col = position
                        detail = await self.open_device(msg, row, col, phone)
                        await self.monitor(detail, phone)
                        self.state.update(phase="ready", remaining=0)
                        return
                    self.state.update(phase="searching", phone=None, remaining=0)
                    refresh = next(((rr, cc) for rr, cc, b in buttons(msg)
                                    if "refresh numbers" in button_text(b.text)), None)
                    if not refresh:
                        break
                    msg = await self.click(msg, *refresh, unchanged=True)
                    msg = await self.wait_for_numbers()
            self.state.update(phase="exhausted", phone=None,
                              last_result="All available panels checked. No unused numbers remain.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.update(phase="error", error=str(exc), phone=None)
        finally:
            self.state["running"] = False
