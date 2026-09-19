import pytest
import pytest_asyncio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def sample_state():
    """A minimal valid PipelineState for use in unit tests."""
    from app.pipeline.state import initial_state
    return initial_state(run_id="test-run-123", topic_override="LangGraph 0.2 deep dive")
