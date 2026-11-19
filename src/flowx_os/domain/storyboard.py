"""Strict, immutable storyboard and scene timeline contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TimelineScene(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    scene_number: int = Field(ge=1, le=30)
    start_ms: int = Field(ge=0, le=180_000)
    end_ms: int = Field(ge=1, le=180_000)
    beat: str = Field(min_length=1, max_length=500)
    narration_text: str = Field(default="", max_length=2_000)
    visual_prompt: str = Field(min_length=1, max_length=2_000)
    prompt_version: int = Field(default=1, ge=1, le=100_000)

    @field_validator("beat", "visual_prompt")
    @classmethod
    def required_text_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("narration_text")
    @classmethod
    def narration_is_normalized(cls, value: str) -> str:
        return value.strip()


class StoryboardTimeline(BaseModel):
    """One immutable storyboard version mapped to a contiguous millisecond timeline."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    title: str = Field(min_length=1, max_length=300)
    scenes: tuple[TimelineScene, ...] = Field(min_length=1, max_length=30)

    @field_validator("scenes", mode="before")
    @classmethod
    def freeze_input_scenes(cls, value):
        # JSON arrays arrive as Python lists; normalize before strict tuple validation.
        return tuple(value) if isinstance(value, list) else value

    @field_validator("title")
    @classmethod
    def title_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value

    @model_validator(mode="after")
    def timeline_is_contiguous_and_sequential(self) -> "StoryboardTimeline":
        if [scene.scene_number for scene in self.scenes] != list(range(1, len(self.scenes) + 1)):
            raise ValueError("scene numbers must be sequential starting at one")
        if self.scenes[0].start_ms != 0:
            raise ValueError("the first scene must start at zero milliseconds")
        for previous, current in zip(self.scenes, self.scenes[1:]):
            if current.start_ms != previous.end_ms:
                raise ValueError("scene timeline must have no gaps or overlaps")
        if any(scene.end_ms <= scene.start_ms for scene in self.scenes):
            raise ValueError("each scene must have positive duration")
        return self

    @property
    def total_duration_ms(self) -> int:
        return self.scenes[-1].end_ms
