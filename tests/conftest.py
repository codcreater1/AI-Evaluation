import pytest

# Importing this registers every built-in evaluator + adapter exactly once,
# so tests can reference them by name without duplicating registration.
import app.bootstrap  # noqa: F401


@pytest.fixture
def tmp_dataset_root(tmp_path):
    return tmp_path / "datasets"
