import pytest
from app.config.settings import Settings

@pytest.fixture
def test_settings(tmp_path):
    return Settings(faiss_persist_dir=tmp_path / "index")
