import unittest

from flowx_os.domain.scene_jobs import (
    SceneAttemptLimitExceeded,
    SceneAttemptStateConflict,
    SceneJobState,
    SceneRetryPolicy,
)


class SceneRetryPolicyTests(unittest.TestCase):
    def test_two_regenerations_allow_three_total_attempts(self):
        policy = SceneRetryPolicy(max_scene_regenerations=2)
        self.assertEqual(policy.max_attempts, 3)
        self.assertTrue(policy.should_schedule_retry(attempt_index=1, retryable=True))
        self.assertTrue(policy.should_schedule_retry(attempt_index=2, retryable=True))
        self.assertFalse(policy.should_schedule_retry(attempt_index=3, retryable=True))
        self.assertFalse(policy.should_schedule_retry(attempt_index=1, retryable=False))
        with self.assertRaises(SceneAttemptLimitExceeded):
            policy.require_index(4)

    def test_initial_and_retry_attempts_require_expected_scene_state(self):
        policy = SceneRetryPolicy(2)
        policy.require_attempt(attempt_index=1, state=SceneJobState.PENDING, retry_count=0)
        policy.require_attempt(attempt_index=2, state=SceneJobState.RETRY_WAIT, retry_count=1)
        with self.assertRaises(SceneAttemptStateConflict):
            policy.require_attempt(attempt_index=2, state=SceneJobState.PENDING, retry_count=0)
        with self.assertRaises(SceneAttemptStateConflict):
            policy.require_attempt(attempt_index=2, state=SceneJobState.RETRY_WAIT, retry_count=0)


if __name__ == "__main__":
    unittest.main()
