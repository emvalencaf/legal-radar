import pytest

from legal_radar.adapters.fixture.pipeline import TAG_SCHEMA
from legal_radar.adapters.prompt_lock import refresh
from legal_radar.domain.prompts import PromptLock


class RecordingStore:
    """A GraphStore that keeps the last batch it was given."""

    def write(self, batch):
        self.batch = batch


@pytest.fixture
def store():
    return RecordingStore()


@pytest.fixture
def tag_lock() -> PromptLock:
    """A lock whose `dispositivo-concept` carries the tagging schema."""
    return refresh({"dispositivo-concept": "c1"}, lambda n, c: ("Tag:\n{text}", TAG_SCHEMA))
