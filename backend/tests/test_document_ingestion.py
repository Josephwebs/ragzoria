from app.rag.loaders import load_documents
from app.rag.chunking import split_documents

def test_local_sources_and_chunks(test_settings):
    docs = load_documents(test_settings)
    assert {d.metadata["tipo_fuente"] for d in docs} == {"internal", "external"}
    assert all(set(d.metadata) == {"source", "tipo_fuente", "categoria", "seccion"} for d in docs)
    chunks = split_documents(docs)
    assert chunks and all(len(d.page_content) <= 350 for d in chunks)
    assert all(d.metadata["source"] for d in chunks)
