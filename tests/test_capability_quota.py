import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from ChatGPTWeb.ChatGPTWeb import chatgpt
from ChatGPTWeb.api import restore_session_state
from ChatGPTWeb.capability_quota import (
    FILE_UPLOAD,
    IMAGE_GENERATION,
    IMAGE_UPLOAD,
    infer_request_capabilities,
)
from ChatGPTWeb.config import IOFile, MsgData, Session, Status
from ChatGPTWeb.storage import RuntimeStorage
from ChatGPTWeb.verification import VerificationBroker


class _Logger:
    def debug(self, _message):
        pass

    def info(self, _message):
        pass

    def warning(self, _message):
        pass

    def error(self, _message):
        pass


class CapabilityQuotaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = chatgpt.__new__(chatgpt)
        self.runtime.logger = _Logger()
        self.runtime.storage = RuntimeStorage(Path(self.directory.name))
        self.runtime.manage = {"start": True}
        self.runtime.ready_timeout = 1
        self.runtime.capability_quota_enabled = True
        self.runtime.free_upload_daily_limit = 2
        self.runtime.free_image_generation_daily_limit = 2
        self.runtime.capability_rate_limit_cooldown_seconds = 86400
        self.runtime.account_selection_strategy = "least_recently_used"
        self.runtime.account_selection_window_seconds = 3600
        self.runtime._account_selection_history = {}
        self.runtime._activity = []
        self.runtime._usage_by_account = {}
        self.runtime._control_login_tasks = {}
        self.runtime._ensure_session_runtime = AsyncMock(return_value=True)
        self.runtime.verification_broker = VerificationBroker()

    def tearDown(self):
        self.directory.cleanup()

    def _session(self, email: str, *, minutes_old: int = 1) -> Session:
        return Session(
            email=email,
            account_plan="free",
            status=Status.Ready.value,
            login_state=True,
            last_active=datetime.now() - timedelta(minutes=minutes_old),
        )

    def test_request_capabilities_are_inferred_conservatively(self):
        image = IOFile(content=b"not-a-real-image", name="sample.png", mime_type="image/png")
        document = IOFile(content=b"plain text", name="sample.txt", mime_type="text/plain")

        inferred = infer_request_capabilities(
            "请生成一张粉色主题的图片",
            [image, document],
        )
        ordinary = infer_request_capabilities("介绍一下图片生成技术", [], [])
        short_command = infer_request_capabilities("帮我画一只猫", [], [])
        image_edit = infer_request_capabilities("那你把上面的字改成好想玩猪咪，然后发我", [], [])
        ordinary_edit = infer_request_capabilities("把这段文字改成更自然一点", [], [])

        self.assertEqual(inferred, [IMAGE_UPLOAD, FILE_UPLOAD, IMAGE_GENERATION])
        self.assertEqual(ordinary, [])
        self.assertEqual(short_command, [IMAGE_GENERATION])
        self.assertEqual(image_edit, [IMAGE_GENERATION])
        self.assertEqual(ordinary_edit, [])

    async def test_new_upload_request_skips_account_with_exhausted_soft_budget(self):
        exhausted = self._session("exhausted@example.com", minutes_old=10)
        exhausted.capability_usage_day = datetime.now().date().isoformat()
        exhausted.capability_usage["upload_total"] = 2
        available = self._session("available@example.com")
        self.runtime.Sessions = [exhausted, available]

        selected = await self.runtime._prepare_chat_session(MsgData(
            msg_send="看看附件",
            upload_file=[
                IOFile(content=b"hello", name="note.txt", mime_type="text/plain")
            ],
        ))

        self.assertIs(selected, available)

    async def test_exhausted_upload_budget_does_not_disable_text_chat(self):
        session = self._session("text@example.com")
        session.capability_usage_day = datetime.now().date().isoformat()
        session.capability_usage["upload_total"] = 2
        self.runtime.Sessions = [session]

        selected = await self.runtime._prepare_chat_session(
            MsgData(msg_send="普通文本聊天")
        )

        self.assertIs(selected, session)

    async def test_existing_conversation_reports_capability_cooldown_without_moving(self):
        session = self._session("owner@example.com")
        session.capability_usage_day = datetime.now().date().isoformat()
        session.capability_usage["upload_total"] = 2
        self.runtime.Sessions = [session]
        data = MsgData(
            msg_send="继续看附件",
            conversation_id="conversation-1",
            p_msg_id="message-1",
            account_hint=session.email,
            upload_file=[
                IOFile(content=b"hello", name="note.txt", mime_type="text/plain")
            ],
        )

        selected = await self.runtime._prepare_chat_session(data)

        self.assertIsNone(selected)
        self.assertEqual(
            data.error_list[-1]["kind"],
            "conversation_capability_rate_limited",
        )
        self.assertEqual(data.error_list[-1]["capability"], FILE_UPLOAD)

    def test_successful_capabilities_are_counted_and_persisted(self):
        session = self._session("usage@example.com")
        data = MsgData(
            status=True,
            msg_send="生成图片并参考附件",
            upload_file=[
                IOFile(content=b"hello", name="note.txt", mime_type="text/plain")
            ],
            image_gen=True,
            img_list=[{"url": "https://example.invalid/image.png"}],
        )

        self.runtime._record_capability_usage(session, data)
        stored = self.runtime.storage.load_session(session.email)

        self.assertEqual(session.capability_usage["upload_total"], 1)
        self.assertEqual(session.capability_usage[FILE_UPLOAD], 1)
        self.assertEqual(session.capability_usage[IMAGE_GENERATION], 1)
        self.assertEqual(stored["capability_usage"]["upload_total"], 1)

        restored = restore_session_state(
            Session(email=session.email),
            self.runtime.storage,
            self.runtime.logger,
        )
        self.assertEqual(restored.capability_usage[FILE_UPLOAD], 1)
        self.assertEqual(restored.capability_usage[IMAGE_GENERATION], 1)

    def test_upstream_upload_limit_cools_the_shared_upload_capabilities(self):
        session = self._session("limited@example.com")
        data = MsgData(
            msg_send="分析附件",
            required_capabilities=[FILE_UPLOAD],
        )

        self.runtime._handle_upstream_rate_limit(
            session,
            data,
            "File upload rate limit. Try again in 10 minutes.",
            attempt=1,
        )

        self.assertFalse(session.is_chat_rate_limited())
        self.assertTrue(session.is_capability_rate_limited(FILE_UPLOAD))
        self.assertTrue(session.is_capability_rate_limited(IMAGE_UPLOAD))
        self.assertEqual(data.error_list[-1]["kind"], "capability_rate_limited")

    async def test_status_exposes_local_estimates_without_disabling_account(self):
        session = self._session("status@example.com")
        session.capability_usage_day = datetime.now().date().isoformat()
        session.capability_usage.update({
            "upload_total": 1,
            IMAGE_UPLOAD: 1,
            IMAGE_GENERATION: 2,
        })
        self.runtime.Sessions = [session]

        account = (await self.runtime.token_status())["accounts"][0]

        self.assertTrue(account["available"])
        self.assertEqual(account["capability_quota"]["upload_total"], 1)
        self.assertEqual(
            account["capability_quota"][IMAGE_GENERATION]["limit_reason"],
            "local_soft_budget",
        )
