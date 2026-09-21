import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from app import llm_client


def response_with(content: str = '{"ok": true}'):
    choice = SimpleNamespace(
        finish_reason="stop",
        message=SimpleNamespace(content=content),
    )
    return SimpleNamespace(choices=[choice])


def status_error(status_code: int, error_class=APIStatusError):
    response = SimpleNamespace(status_code=status_code, request=object(), headers={})
    return error_class("provider failure", response=response, body=None)


def client_with(*side_effects):
    create = Mock(side_effect=list(side_effects))
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        )
    )
    return client, create


class LLMRetryTests(unittest.TestCase):
    def generate(self, *side_effects, json_mode=True):
        client, create = client_with(*side_effects)
        sleeps = []
        with patch.object(llm_client, "_get_client", return_value=client):
            result = llm_client._generate(
                "model",
                [{"role": "user", "content": "private input"}],
                128,
                json_mode,
                sleep_fn=sleeps.append,
            )
        return result, create, sleeps

    def test_success_on_first_attempt_and_json_mode_is_preserved(self):
        expected = response_with()
        result, create, sleeps = self.generate(expected)

        self.assertIs(result, expected)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(
            create.call_args.kwargs["response_format"], {"type": "json_object"}
        )

    def test_plain_text_mode_for_vision_omits_json_response_format(self):
        expected = response_with("transcribed text")
        result, create, sleeps = self.generate(expected, json_mode=False)

        self.assertIs(result, expected)
        self.assertEqual(sleeps, [])
        self.assertNotIn("response_format", create.call_args.kwargs)

    def test_timeout_then_success_uses_real_sdk_exception(self):
        expected = response_with()
        result, create, sleeps = self.generate(APITimeoutError(object()), expected)

        self.assertIs(result, expected)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(sleeps, [0.5])

    def test_connection_error_then_success_uses_real_sdk_exception(self):
        expected = response_with()
        failure = APIConnectionError(request=object())
        result, create, sleeps = self.generate(failure, expected)

        self.assertIs(result, expected)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(sleeps, [0.5])

    def test_rate_limit_then_success_has_safe_context_log(self):
        expected = response_with()
        client, create = client_with(status_error(429, RateLimitError), expected)
        sleeps = []

        with self.assertLogs("app.llm_client", level="WARNING") as logs:
            with llm_client.llm_request_context("email_007", "classification"):
                with patch.object(llm_client, "_get_client", return_value=client):
                    result = llm_client._generate(
                        "model",
                        [{"role": "user", "content": "private email body"}],
                        128,
                        True,
                        sleep_fn=sleeps.append,
                    )

        self.assertIs(result, expected)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(sleeps, [0.5])
        retry_record = next(
            record for record in logs.records if record.msg == "llm_request_retry"
        )
        self.assertEqual(retry_record.email_id, "email_007")
        self.assertEqual(retry_record.processing_stage, "classification")
        self.assertEqual(retry_record.attempt_number, 1)
        self.assertEqual(retry_record.status_code, 429)
        self.assertNotIn("private email body", "\n".join(logs.output))
        self.assertNotIn("provider failure", "\n".join(logs.output))

    def test_http_408_then_success(self):
        expected = response_with()
        result, create, sleeps = self.generate(status_error(408), expected)

        self.assertIs(result, expected)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(sleeps, [0.5])

    def test_server_error_then_success(self):
        expected = response_with()
        result, create, sleeps = self.generate(status_error(503), expected)

        self.assertIs(result, expected)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(sleeps, [0.5])

    def test_every_5xx_is_retryable(self):
        expected = response_with()
        result, create, sleeps = self.generate(status_error(599), expected)

        self.assertIs(result, expected)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(sleeps, [0.5])

    def test_authentication_failure_is_not_retried(self):
        original = status_error(401, AuthenticationError)
        client, create = client_with(original)
        sleeps = []

        with patch.object(llm_client, "_get_client", return_value=client):
            with self.assertRaises(llm_client.LLMUnavailableError) as caught:
                llm_client._generate(
                    "model", [], 128, True, sleep_fn=sleeps.append
                )

        self.assertEqual(create.call_count, 1)
        self.assertEqual(sleeps, [])
        self.assertIs(caught.exception.__cause__, original)

    def test_permanent_http_errors_are_not_retried(self):
        for status_code in (400, 403, 404, 409):
            with self.subTest(status_code=status_code):
                original = status_error(status_code)
                client, create = client_with(original)
                sleeps = []

                with patch.object(llm_client, "_get_client", return_value=client):
                    with self.assertRaises(llm_client.LLMUnavailableError) as caught:
                        llm_client._generate(
                            "model", [], 128, True, sleep_fn=sleeps.append
                        )

                self.assertEqual(create.call_count, 1)
                self.assertEqual(sleeps, [])
                self.assertIs(caught.exception.__cause__, original)

    def test_generic_exception_is_not_retried_or_wrapped(self):
        original = RuntimeError("private implementation detail")
        client, create = client_with(original)
        sleeps = []

        with patch.object(llm_client, "_get_client", return_value=client):
            with self.assertRaises(RuntimeError) as caught:
                llm_client._generate(
                    "model", [], 128, True, sleep_fn=sleeps.append
                )

        self.assertIs(caught.exception, original)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(sleeps, [])

    def test_three_transient_failures_exhaust_retries(self):
        failures = [APIConnectionError(request=object()) for _ in range(3)]
        client, create = client_with(*failures)
        sleeps = []

        with self.assertLogs("app.llm_client", level="WARNING") as logs:
            with patch.object(llm_client, "_get_client", return_value=client):
                with self.assertRaises(llm_client.LLMUnavailableError) as caught:
                    llm_client._generate(
                        "model",
                        [{"role": "user", "content": "private user content"}],
                        128,
                        True,
                        sleep_fn=sleeps.append,
                    )

        self.assertEqual(create.call_count, 3)
        self.assertEqual(sleeps, [0.5, 1.0])
        self.assertIs(caught.exception.__cause__, failures[-1])
        final_record = next(
            record for record in logs.records if record.msg == "llm_request_failed"
        )
        self.assertEqual(final_record.attempt_number, 3)
        self.assertTrue(final_record.retry_exhausted)
        self.assertEqual(final_record.final_status, "provider_error")
        self.assertNotIn("private user content", "\n".join(logs.output))

    def test_malformed_json_is_not_retried_or_exposed(self):
        client, create = client_with(response_with("not-json private output"))

        with patch.object(llm_client, "_get_client", return_value=client):
            with patch.object(llm_client.time, "sleep") as sleep:
                with self.assertRaisesRegex(
                    ValueError, "model did not return valid JSON"
                ) as caught:
                    llm_client.call_json("system", "private input")

        self.assertEqual(create.call_count, 1)
        sleep.assert_not_called()
        self.assertNotIn("private output", str(caught.exception))

    def test_truncated_response_is_not_retried(self):
        truncated = response_with("private partial output")
        truncated.choices[0].finish_reason = "length"
        client, create = client_with(truncated)

        with patch.object(llm_client, "_get_client", return_value=client):
            with patch.object(llm_client.time, "sleep") as sleep:
                with self.assertRaises(llm_client.LLMUnavailableError):
                    llm_client.call_json("system", "private input", max_tokens=64)

        self.assertEqual(create.call_count, 1)
        sleep.assert_not_called()

    def test_sdk_retries_are_disabled(self):
        fake_client = object()
        llm_client._client = None
        self.addCleanup(setattr, llm_client, "_client", None)

        with patch.object(llm_client, "OpenAI", return_value=fake_client) as constructor:
            with patch.dict(
                os.environ,
                {
                    "LLM_BASE_URL": "https://example.invalid/v1",
                    "LLM_API_KEY": "test-key",
                    "LLM_TIMEOUT": "12",
                },
                clear=False,
            ):
                result = llm_client._get_client()

        self.assertIs(result, fake_client)
        self.assertEqual(constructor.call_args.kwargs["max_retries"], 0)
        self.assertEqual(constructor.call_args.kwargs["timeout"], 12.0)


if __name__ == "__main__":
    unittest.main()
