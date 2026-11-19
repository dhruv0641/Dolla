import unittest

from pydantic import ValidationError

from flowx_os.domain.storyboard import StoryboardTimeline


def timeline(**overrides):
    value = {
        "title": "A falling apple",
        "scenes": [
            {"scene_number": 1, "start_ms": 0, "end_ms": 4_000,
             "beat": "The setup", "narration_text": "Look up.", "visual_prompt": "Apple tree"},
            {"scene_number": 2, "start_ms": 4_000, "end_ms": 8_000,
             "beat": "The turn", "narration_text": "An apple falls.", "visual_prompt": "Falling apple"},
        ],
    }
    value.update(overrides)
    return value


class StoryboardTimelineTests(unittest.TestCase):
    def test_valid_timeline_is_bounded_and_reports_total_duration(self):
        result = StoryboardTimeline.model_validate(timeline())
        self.assertEqual(result.total_duration_ms, 8_000)
        self.assertEqual(result.scenes[0].prompt_version, 1)

    def test_rejects_gaps_overlaps_or_nonzero_start(self):
        cases = [
            timeline(scenes=[
                {"scene_number": 1, "start_ms": 1, "end_ms": 4_000, "beat": "a", "visual_prompt": "a"},
                {"scene_number": 2, "start_ms": 4_000, "end_ms": 8_000, "beat": "b", "visual_prompt": "b"},
            ]),
            timeline(scenes=[
                {"scene_number": 1, "start_ms": 0, "end_ms": 4_000, "beat": "a", "visual_prompt": "a"},
                {"scene_number": 2, "start_ms": 4_001, "end_ms": 8_000, "beat": "b", "visual_prompt": "b"},
            ]),
            timeline(scenes=[
                {"scene_number": 1, "start_ms": 0, "end_ms": 4_001, "beat": "a", "visual_prompt": "a"},
                {"scene_number": 2, "start_ms": 4_000, "end_ms": 8_000, "beat": "b", "visual_prompt": "b"},
            ]),
        ]
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    StoryboardTimeline.model_validate(value)

    def test_rejects_nonsequential_scene_numbers_and_unknown_fields(self):
        value = timeline(scenes=[
            {"scene_number": 2, "start_ms": 0, "end_ms": 8_000, "beat": "a", "visual_prompt": "a"},
        ])
        with self.assertRaises(ValidationError):
            StoryboardTimeline.model_validate(value)
        with self.assertRaises(ValidationError):
            StoryboardTimeline.model_validate(timeline(extra="ignored"))

    def test_rejects_blank_prompts_and_out_of_bounds_timeline(self):
        value = timeline(scenes=[
            {"scene_number": 1, "start_ms": 0, "end_ms": 180_001, "beat": " ", "visual_prompt": "x"},
        ])
        with self.assertRaises(ValidationError):
            StoryboardTimeline.model_validate(value)


if __name__ == "__main__":
    unittest.main()
