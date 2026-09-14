import pytest

from app.core.dataset_manager import DatasetManager, DatasetVersionLockedError
from app.core.schemas import EvaluationCase


def _case(i: int) -> EvaluationCase:
    return EvaluationCase(id=f"c{i}", system="ata-rag", input={"question": f"q{i}"})


def test_save_and_load_round_trip(tmp_dataset_root):
    dm = DatasetManager(tmp_dataset_root)
    version = dm.save_new_version("ata-rag", [_case(1), _case(2)])
    assert version == "v1"

    loaded = dm.load("ata-rag", "v1")
    assert [c.id for c in loaded] == ["c1", "c2"]


def test_versions_auto_increment(tmp_dataset_root):
    dm = DatasetManager(tmp_dataset_root)
    dm.save_new_version("ata-rag", [_case(1)])
    v2 = dm.save_new_version("ata-rag", [_case(1), _case(2)])
    assert v2 == "v2"
    assert dm.list_versions("ata-rag") == ["v1", "v2"]
    assert dm.latest_version("ata-rag") == "v2"


def test_locked_version_cannot_be_overwritten(tmp_dataset_root):
    dm = DatasetManager(tmp_dataset_root)
    dm.save_new_version("ata-rag", [_case(1)])  # v1
    dm.lock("ata-rag", "v1")  # simulates an experiment having run against it

    with pytest.raises(DatasetVersionLockedError):
        dm.save_new_version("ata-rag", [_case(1), _case(2)], version="v1")


def test_append_draft_case_extends_unlocked_version_in_place(tmp_dataset_root):
    dm = DatasetManager(tmp_dataset_root)
    dm.save_new_version("ata-rag", [_case(1)])  # v1, still a draft

    result_version = dm.append_draft_case("ata-rag", _case(2))

    assert result_version == "v1"
    assert len(dm.load("ata-rag", "v1")) == 2


def test_append_draft_case_starts_new_version_when_locked(tmp_dataset_root):
    dm = DatasetManager(tmp_dataset_root)
    dm.save_new_version("ata-rag", [_case(1)])  # v1
    dm.lock("ata-rag", "v1")

    result_version = dm.append_draft_case("ata-rag", _case(2))

    assert result_version == "v2"
    assert len(dm.load("ata-rag", "v1")) == 1  # untouched
    assert len(dm.load("ata-rag", "v2")) == 2
