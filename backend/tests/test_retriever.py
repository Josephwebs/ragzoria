import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document
from langchain_community.vectorstores import FAISS
from app.retrievers import faiss_retriever as module

class TestEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[float(len(t)), 1.0] for t in texts]
    def embed_query(self, text):
        return [float(len(text)), 1.0]

def test_raw_faiss_distance_and_top_two(test_settings, monkeypatch):
    embedding = TestEmbeddings()
    docs = [Document(page_content=t) for t in ["a", "abc", "abcdef"]]
    FAISS.from_documents(docs, embedding).save_local(str(test_settings.faiss_persist_dir))
    monkeypatch.setattr(module, "OllamaEmbeddings", lambda s: embedding)
    pairs = module.retrieve("abc", test_settings)
    assert len(pairs) == 2
    assert pairs[0][0].page_content == "abc"
    assert pairs[0][1] == 0
    assert pairs[1][1] == 4

def test_missing_index(test_settings):
    with pytest.raises(FileNotFoundError, match="ingest.py"):
        module.retrieve("question", test_settings)
