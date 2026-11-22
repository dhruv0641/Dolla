import sys
import tempfile
import unittest
from pathlib import Path

from flowx_os.audio.tts_evaluation import TtsEngineSpec, TtsEvaluationPolicy, TtsEvaluator, TtsEvaluationError


class TtsEvaluationTests(unittest.TestCase):
    def _fake(self, body: str) -> str:
        path = Path(tempfile.mkdtemp()) / "fake_tts.py"
        path.write_text(body, encoding="utf-8")
        return f"{sys.executable} {path}"

    def test_unavailable_engine_is_explicit(self):
        result = TtsEvaluator(TtsEvaluationPolicy((TtsEngineSpec("missing", "definitely-no-local-tts"),))).evaluate()
        self.assertFalse(result.engines[0].available)
        self.assertEqual(result.engines[0].error_code, "EXECUTABLE_UNAVAILABLE")
        self.assertIsNone(result.recommended_engine)
        self.assertFalse(result.synthesis_performed)

    def test_configured_fake_engine_version_and_voices(self):
        executable = self._fake("""import sys
if sys.argv[1:] == ['--version']:
 print('fake-tts 1.2')
elif sys.argv[1:] == ['--voices']:
 print('en-US-A')
 print('en-IN-B')
else:
 raise SystemExit(2)
""")
        command, script = executable.split(" ", 1)
        result = TtsEvaluator(TtsEvaluationPolicy((TtsEngineSpec("fake", command, version_args=(script, "--version"), voices_args=(script, "--voices")),))).evaluate()
        self.assertTrue(result.engines[0].available)
        self.assertEqual(result.engines[0].voices, ("en-US-A", "en-IN-B"))
        self.assertEqual(result.recommended_engine, "fake")

    def test_policy_rejects_invalid_timeout(self):
        with self.assertRaises(TtsEvaluationError):
            TtsEvaluationPolicy((), timeout_seconds=0)

    def test_probe_timeout_and_output_are_bounded(self):
        executable = self._fake("""import sys, time
if sys.argv[1:] == ['--version']:
 print('x' * 100000, flush=True)
 time.sleep(5)
""")
        command, script = executable.split(" ", 1)
        spec = TtsEngineSpec("noisy", command, version_args=(script, "--version"))
        result = TtsEvaluator(TtsEvaluationPolicy((spec,), timeout_seconds=1, output_limit_bytes=1024)).evaluate()
        self.assertFalse(result.engines[0].available)
        self.assertEqual(result.engines[0].error_code, "PROBE_OUTPUT_LIMIT")


if __name__ == "__main__":
    unittest.main()
