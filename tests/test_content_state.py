import unittest
import re
from pathlib import Path

from flowx_os.domain.content_state import (
    ALLOWED_CONTENT_TRANSITIONS,
    ContentStatus,
    InvalidContentTransition,
    require_content_transition,
)


class ContentStateTests(unittest.TestCase):
    def test_lifecycle_forward_path_is_allowed(self):
        path = [
            ContentStatus.IDEA, ContentStatus.RESEARCHED, ContentStatus.BRIEF_READY,
            ContentStatus.SCRIPT_READY, ContentStatus.STORYBOARD_READY,
            ContentStatus.GENERATING, ContentStatus.ASSEMBLING, ContentStatus.QA_PENDING,
            ContentStatus.NEEDS_REVIEW, ContentStatus.READY, ContentStatus.SCHEDULED,
            ContentStatus.READY, ContentStatus.NEEDS_REVIEW, ContentStatus.ARCHIVED,
        ]
        for current, target in zip(path, path[1:]):
            with self.subTest(current=current, target=target):
                require_content_transition(current, target)

    def test_rework_and_failure_edges_are_explicit(self):
        require_content_transition(ContentStatus.NEEDS_REVIEW, ContentStatus.SCRIPT_READY)
        require_content_transition(ContentStatus.FAILED, ContentStatus.IDEA)
        require_content_transition(ContentStatus.PUBLISHED, ContentStatus.ARCHIVED)

    def test_skips_and_terminal_transitions_are_rejected(self):
        with self.assertRaises(InvalidContentTransition):
            require_content_transition(ContentStatus.IDEA, ContentStatus.SCRIPT_READY)
        with self.assertRaises(InvalidContentTransition):
            require_content_transition(ContentStatus.SCHEDULED, ContentStatus.PUBLISHED)
        with self.assertRaises(InvalidContentTransition):
            require_content_transition(ContentStatus.SCHEDULED, ContentStatus.PARTIALLY_PUBLISHED)
        with self.assertRaises(InvalidContentTransition):
            require_content_transition(ContentStatus.PUBLISHED, ContentStatus.READY)
        with self.assertRaises(InvalidContentTransition):
            require_content_transition(ContentStatus.ARCHIVED, ContentStatus.IDEA)
        with self.assertRaises(InvalidContentTransition):
            require_content_transition("IDEA", ContentStatus.RESEARCHED)

    def test_every_typed_status_has_an_explicit_transition_set(self):
        self.assertEqual(set(ALLOWED_CONTENT_TRANSITIONS), set(ContentStatus))
        self.assertEqual(ALLOWED_CONTENT_TRANSITIONS[ContentStatus.ARCHIVED], frozenset())
        inbound = {target for targets in ALLOWED_CONTENT_TRANSITIONS.values() for target in targets}
        self.assertNotIn(ContentStatus.PUBLISHED, inbound)
        self.assertNotIn(ContentStatus.PARTIALLY_PUBLISHED, inbound)

    def test_typed_statuses_match_the_database_check_constraint(self):
        migration = (Path(__file__).resolve().parents[1] / "migrations" / "0001_initial_schema.sql").read_text()
        match = re.search(
            r"status text NOT NULL DEFAULT 'IDEA' CHECK \(status IN \((.*?)\)\)",
            migration,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        database_states = set(re.findall(r"'([A-Z_]+)'", match.group(1)))
        self.assertEqual(database_states, {status.value for status in ContentStatus})


if __name__ == "__main__":
    unittest.main()
