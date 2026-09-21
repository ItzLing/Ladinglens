"""scripts/poll.py: which run it asks for. The loop and the network are not exercised."""
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "poll.py"
spec = importlib.util.spec_from_file_location("poll_script", SCRIPT)
poll = importlib.util.module_from_spec(spec)
spec.loader.exec_module(poll)


class PollTests(unittest.TestCase):
    def test_it_asks_for_new_emails_only_by_default(self):
        self.assertEqual(poll.run_url("http://x"), "http://x/run?new_only=true")

    def test_retry_failed_switches_to_resume(self):
        self.assertEqual(poll.run_url("http://x", retry_failed=True), "http://x/run?resume=true")

    def test_a_tick_posts_to_that_url(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"emails_processed": 3}'

        with mock.patch.object(poll.urllib.request, "urlopen", return_value=Response()) as urlopen:
            self.assertTrue(poll.tick("http://x", rebuild=False))
            self.assertTrue(poll.tick("http://x", rebuild=False, retry_failed=True))
        urls = [call.args[0].full_url for call in urlopen.call_args_list]
        methods = [call.args[0].get_method() for call in urlopen.call_args_list]
        self.assertEqual(urls, ["http://x/run?new_only=true", "http://x/run?resume=true"])
        self.assertEqual(methods, ["POST", "POST"])


if __name__ == "__main__":
    unittest.main()
