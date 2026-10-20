import unittest
from unittest.mock import Mock, patch
from openbroadcast.audio.com import audio_thread


class AudioComTests(unittest.TestCase):
    def test_success_and_already_initialized_are_balanced_even_on_error(self):
        for result in (0, 1):
            api = Mock()
            api.CoInitializeEx.return_value = result
            with patch("openbroadcast.audio.com.sys.platform", "win32"):
                with self.assertRaisesRegex(RuntimeError, "stream failure"):
                    with audio_thread(api):
                        api.CoUninitialize.assert_not_called()
                        raise RuntimeError("stream failure")
            api.CoInitializeEx.assert_called_once_with(None, 0)
            api.CoUninitialize.assert_called_once_with()

    def test_existing_apartment_is_preserved(self):
        api = Mock()
        api.CoInitializeEx.return_value = -2147417850  # RPC_E_CHANGED_MODE
        with patch("openbroadcast.audio.com.sys.platform", "win32"):
            with audio_thread(api):
                pass
        api.CoUninitialize.assert_not_called()

    def test_failure_does_not_open_audio_or_uninitialize(self):
        api = Mock()
        api.CoInitializeEx.return_value = -2147024882  # E_OUTOFMEMORY
        with patch("openbroadcast.audio.com.sys.platform", "win32"):
            with self.assertRaisesRegex(OSError, "8007000E"):
                with audio_thread(api):
                    self.fail("Audio must not start after COM initialization failed")
        api.CoUninitialize.assert_not_called()

    def test_other_platforms_do_not_call_com(self):
        api = Mock()
        with patch("openbroadcast.audio.com.sys.platform", "linux"):
            with audio_thread(api):
                pass
        api.CoInitializeEx.assert_not_called()
