import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ChatGPTWeb.core_server import (
    CoreServerSettings,
    load_env_file,
    load_sessions,
    main,
    validate_settings,
)


class CoreServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.sessions_file = self.root / "sessions.json"
        self.sessions_file.write_text('[{"email": "test@example.com"}]', "utf8")

    def tearDown(self):
        self.directory.cleanup()

    def _environment(self):
        return {
            "CHATGPTWEB_SESSIONS_FILE": str(self.sessions_file),
            "CHATGPTWEB_STORAGE_DIR": str(self.root / "storage"),
            "CHATGPTWEB_HTTP_API_KEY": "http-secret",
            "CHATGPTWEB_CONTROL_API_KEY": "control-secret",
        }

    def test_load_sessions_requires_account_objects(self):
        invalid = self.root / "invalid.json"
        invalid.write_text('["not-an-account"]', "utf8")

        with self.assertRaisesRegex(ValueError, "account objects"):
            load_sessions(invalid)

    def test_env_file_preserves_process_environment_by_default(self):
        env_file = self.root / "core.env"
        env_file.write_text(
            "# comment\nexport CHATGPTWEB_HTTP_API_KEY=file-secret\nCUSTOM_SETTING='quoted value'\n",
            "utf8",
        )
        with patch.dict(os.environ, {"CHATGPTWEB_HTTP_API_KEY": "process-secret"}, clear=True):
            load_env_file(env_file)
            self.assertEqual(os.environ["CHATGPTWEB_HTTP_API_KEY"], "process-secret")
            self.assertEqual(os.environ["CUSTOM_SETTING"], "quoted value")

    def test_settings_validate_configured_ports_and_sessions(self):
        with patch.dict(os.environ, self._environment(), clear=True):
            settings = CoreServerSettings.from_environment()
            validate_settings(settings)

        self.assertEqual(settings.sessions_file, self.sessions_file)
        self.assertEqual(settings.control_port, 8765)
        self.assertEqual(settings.max_attachment_bytes, 20 * 1024 * 1024)
        self.assertEqual(settings.max_attachment_count, 8)
        self.assertTrue(settings.remote_input_enabled)
        self.assertEqual(settings.remote_input_timeout_seconds, 15)
        self.assertEqual(settings.remote_input_max_redirects, 3)

    def test_remote_input_settings_can_be_disabled_and_validated(self):
        environment = {
            **self._environment(),
            "CHATGPTWEB_REMOTE_INPUT_ENABLED": "false",
            "CHATGPTWEB_REMOTE_INPUT_TIMEOUT_SECONDS": "5.5",
            "CHATGPTWEB_REMOTE_INPUT_MAX_REDIRECTS": "1",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = CoreServerSettings.from_environment()
            validate_settings(settings)

        self.assertFalse(settings.remote_input_enabled)
        self.assertEqual(settings.remote_input_timeout_seconds, 5.5)
        self.assertEqual(settings.remote_input_max_redirects, 1)

    def test_check_config_exits_without_launching_runtime(self):
        environment = self._environment()
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(output):
            main(["--check-config"])

        self.assertIn("configuration is valid", output.getvalue())
