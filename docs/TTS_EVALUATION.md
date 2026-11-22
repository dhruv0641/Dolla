# Local TTS evaluation

`flowx_os.audio.tts_evaluation.TtsEvaluator` inspects explicitly configured local executables. It runs bounded version and optional voice-list commands with closed stdin, no shell, no network setup, and output/time limits. It never downloads a model, synthesizes audio, connects an account, or consumes paid credits.

An engine is available only when its executable resolves and the version probe succeeds. Voice output is evidence supplied by the configured command, not a promise that synthesis succeeds. License status remains `UNVERIFIED` until an operator records a verified license reference. Missing executables, nonzero probes, timeouts and output overflow are returned as stable error codes.

The evaluator returns a deterministic recommendation among available configured engines, preferring one with a discovered voice list and preserving configuration order for ties. The recommendation is an evaluation result only; voice selection, consent, synthesis, WAV encoding, duration checks and asset registration belong to later tasks.

The repository does not claim that a local engine is installed on CI or production. Run the focused tests with `python -m unittest tests.test_tts_evaluation -v`; the tests use a temporary fake executable and do not synthesize or access a network.
