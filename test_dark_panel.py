import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from dark_panel import DarkPanel, number, sms_entries, button_text


class ParsingTests(unittest.TestCase):
    def test_button_unicode_spacing(self):
        self.assertEqual(button_text('📱 LIVE\u00a0\u00a0DE\u200bVICES'), 'live devices')
        self.assertEqual(button_text('📱 𝐋𝐈𝐕𝐄 𝐃𝐄𝐕𝐈𝐂𝐄𝐒'), 'live devices')
    def test_number_does_not_match_partial_long_identifiers(self):
        self.assertEqual(number('🟢 +91 9876543210 (Jio) · Device-2'), '9876543210')
        self.assertIsNone(number('123456789012345'))

    def test_sms_fingerprint_ignores_list_order(self):
        old = '#1 📩 From: TEST - 26-11-2026 / 08:51 PM\n⚡ OTP: 4127\nYour OTP is 4127'
        self.assertEqual(sms_entries(old), sms_entries(old.replace('#1', '#2')))
        self.assertEqual(list(sms_entries(old).values()), ['4127'])
        self.assertEqual(sms_entries('Copy OTP: 4127'), {})


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_hindi_panel_skips_refresh_and_checks_next(self):
        def screen(text, labels):
            return SimpleNamespace(raw_text=text, buttons=[[
                SimpleNamespace(text=label, url=None)] for label in labels])
        menu = screen('', ['Fresh number', 'Fresh today'])
        empty = screen('Abhi koi active SIM online nahi mili.', ['Refresh Numbers', 'Back to Panels'])
        listing = screen('', ['9876543210'])
        worker = DarkPanel(SimpleNamespace(get_entity=AsyncMock(return_value='bot')), AsyncMock(return_value=False))
        worker.panels = AsyncMock(return_value=menu)
        worker.click = AsyncMock(side_effect=[empty, listing])
        worker.wait_for_numbers = AsyncMock(side_effect=[empty, listing])
        worker.return_to_panels = AsyncMock(return_value=menu)
        await worker.run()
        self.assertEqual(worker.click.await_count, 2)
        worker.return_to_panels.assert_awaited_once_with(empty)
        worker.claim.assert_awaited_once_with('9876543210')
        self.assertEqual(worker.state['phase'], 'exhausted')

    async def test_waits_for_number_keyboard_after_loading(self):
        loading = SimpleNamespace(raw_text='Loading numbers', buttons=[])
        ready = SimpleNamespace(raw_text='Active Numbers', buttons=[[
            SimpleNamespace(text='9876543210', url=None)]])
        worker = DarkPanel(None, None)
        worker.screen = AsyncMock(side_effect=[loading, loading, ready])
        with patch('dark_panel.asyncio.sleep', new=AsyncMock()) as sleep:
            self.assertIs(await worker.wait_for_numbers(), ready)
        self.assertEqual(sleep.await_args_list[0].args, (3,))
        self.assertEqual(worker.screen.await_count, 3)

    async def test_return_handles_delayed_back_button_and_already_open_menu(self):
        def msg(mid, label):
            return SimpleNamespace(id=mid, raw_text='', click=AsyncMock(), buttons=[[
                SimpleNamespace(text=label, url=None, data=b'x')]])
        loading = msg(1, 'Loading')
        empty = msg(2, '⬅ Back to Panels')
        menu = msg(3, '🌐 Fresh number')
        worker = DarkPanel(None, None)
        worker.screen = AsyncMock(side_effect=[empty, empty, menu])
        with patch('dark_panel.asyncio.sleep', new=AsyncMock()):
            self.assertIs(await worker.return_to_panels(loading), menu)
            self.assertIs(await worker.return_to_panels(menu), menu)
        empty.click.assert_awaited_once_with(0, 0)
        menu.click.assert_not_awaited()

    async def test_device_selection_waits_past_list_updates(self):
        def msg(mid, text, label):
            return SimpleNamespace(id=mid, raw_text=text, click=AsyncMock(), buttons=[[
                SimpleNamespace(text=label, url=None, data=b'x')]])
        listing = msg(1, '9876543210 8765432109', '9876543210')
        updated = msg(1, 'Updated list 8765432109 9876543210', '9876543210')
        detail = msg(2, 'Phone Number: 9876543210 | Carrier: Jio', 'Refresh SMS')
        worker = DarkPanel(None, None)
        worker.screen = AsyncMock(side_effect=[updated, detail])
        with patch('dark_panel.asyncio.sleep', new=AsyncMock()):
            self.assertIs(await worker.open_device(listing, 0, 0, '9876543210'), detail)
        listing.click.assert_awaited_once_with(0, 0)

    async def test_start_waits_for_live_devices_not_intermediate_screen(self):
        def message(mid, label):
            return SimpleNamespace(id=mid, out=False, raw_text='', buttons=[[
                SimpleNamespace(text=label, url=None, data=b'menu')]])
        old = message(1, 'LIVE DEVICES')
        interim = message(3, 'Loading')
        menu = message(4, '📱 LIVE\u00a0DEVICES')
        client = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=2)),
            get_messages=AsyncMock(side_effect=[[interim, old], [menu, interim, old]]))
        worker = DarkPanel(client, None)
        worker.entity = 'bot'
        worker.screen = AsyncMock(return_value=old)
        worker.click = AsyncMock(return_value='panels')
        with patch('dark_panel.asyncio.sleep', new=AsyncMock()):
            self.assertEqual(await worker.panels(), 'panels')
        self.assertIs(worker.click.await_args.args[0], menu)

    async def test_selected_number_is_kept_without_automatic_advance(self):
        btn = lambda text: SimpleNamespace(text=text, url=None)
        menu = SimpleNamespace(raw_text='', buttons=[[btn('Fresh number')]])
        listing = SimpleNamespace(raw_text='', buttons=[[btn('9876543210')], [btn('8765432109')]])
        detail = SimpleNamespace(raw_text='Phone Number: 9876543210')
        worker = DarkPanel(SimpleNamespace(get_entity=AsyncMock(return_value='bot')), AsyncMock(return_value=True))
        worker.panels = AsyncMock(return_value=menu)
        worker.click = AsyncMock(return_value=listing)
        worker.wait_for_numbers = AsyncMock(return_value=listing)
        worker.open_device = AsyncMock(return_value=detail)
        async def monitor(msg, phone):
            worker.state['phone'] = phone
        worker.monitor = AsyncMock(side_effect=monitor)
        await worker.run()
        self.assertEqual(worker.state['phone'], '9876543210')
        self.assertEqual(worker.state['phase'], 'ready')
        self.assertEqual(worker.claim.await_count, 1)
        self.assertEqual(worker.click.await_count, 1)
        worker.open_device.assert_awaited_once()
        self.assertFalse(worker.state['running'])

    async def test_old_sms_ignored_and_new_otp_retains_phone(self):
        old = 'Phone Number: 9876543210\n#1 From: TEST - 08:51\nOTP: 4127'
        new = 'Phone Number: 9876543210\n#1 From: TEST - 08:52\nOTP: 5533\n#2 From: TEST - 08:51\nOTP: 4127'
        worker = DarkPanel(None, None)
        worker.named = AsyncMock(side_effect=[SimpleNamespace(raw_text=old), SimpleNamespace(raw_text=new)])
        with patch('dark_panel.asyncio.sleep', new=AsyncMock()):
            await worker.monitor(SimpleNamespace(raw_text=old), '9876543210')
        self.assertEqual(worker.named.await_count, 2)
        self.assertEqual([(x['phone'], x['code']) for x in worker.state['history']], [('9876543210', '5533')])

    async def test_timeout_rotates_without_accepting_old_otp(self):
        worker = DarkPanel(None, None)
        msg = SimpleNamespace(raw_text='Phone Number: 9876543210')
        with patch('dark_panel.time.monotonic', side_effect=[0, 0, 0, 0, 30]), patch('dark_panel.asyncio.sleep', new=AsyncMock()):
            self.assertIs(await worker.monitor(msg, '9876543210'), msg)
        self.assertEqual(worker.state['history'], [])
        self.assertIn('30 seconds', worker.state['last_result'])

    async def test_start_replaces_existing_task_and_stop_cancels(self):
        worker = DarkPanel(None, None)
        worker.run = AsyncMock(side_effect=lambda: None)
        await worker.start()
        first = worker.task
        await worker.start()
        self.assertIs(worker.task, first)
        await worker.stop()
        self.assertTrue(worker.task.done())
        self.assertFalse(worker.state['running'])

    async def test_database_failure_stops_before_device_click(self):
        worker = DarkPanel(SimpleNamespace(get_entity=AsyncMock(return_value='bot')), AsyncMock(side_effect=RuntimeError('Firebase offline')))
        btn = lambda text: SimpleNamespace(text=text, url=None)
        menu = SimpleNamespace(raw_text='', buttons=[[btn('Fresh number')]])
        listing = SimpleNamespace(raw_text='', buttons=[[btn('9876543210')]])
        worker.panels = AsyncMock(return_value=menu)
        worker.click = AsyncMock(return_value=listing)
        worker.wait_for_numbers = AsyncMock(return_value=listing)
        await worker.run()
        self.assertEqual(worker.click.await_count, 1)
        self.assertEqual(worker.state['phase'], 'error')
        self.assertFalse(worker.state['running'])

    async def test_duplicate_batches_and_identical_panel_labels(self):
        def screen(labels):
            return SimpleNamespace(raw_text='', buttons=[[SimpleNamespace(text=t, url=None)] for t in labels])
        menu = screen(['Fresh number', 'Fresh number'])
        batch1 = screen(['9876543210', 'Refresh Numbers (1/2)'])
        batch2 = screen(['8765432109', 'Refresh Numbers (2/2)'])
        final = screen(['7654321098'])
        worker = DarkPanel(SimpleNamespace(get_entity=AsyncMock(return_value='bot')), AsyncMock(return_value=False))
        worker.panels = AsyncMock(return_value=menu)
        worker.click = AsyncMock(side_effect=[batch1, batch2, batch1, final])
        worker.wait_for_numbers = AsyncMock(side_effect=[batch1, batch2, batch1, final])
        worker.return_to_panels = AsyncMock(return_value=menu)
        await worker.run()
        self.assertEqual(worker.state['phase'], 'exhausted')
        self.assertEqual(worker.panels.await_count, 1)
        worker.return_to_panels.assert_awaited_once_with(batch1)
        self.assertEqual([call.args[0] for call in worker.claim.await_args_list],
                         ['9876543210', '8765432109', '7654321098'])


if __name__ == '__main__':
    unittest.main()
