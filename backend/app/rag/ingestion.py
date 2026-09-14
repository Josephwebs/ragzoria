from langchain_community.vectorstores import FAISS
from app.config.settings import get_settings
from app.embeddings.provider import OllamaEmbeddings
from app.rag.loaders import load_documents
from app.rag.chunking import split_documents

def ingest_all(settings=None):
    settings = settings or get_settings()
    documents = load_documents(settings)
    chunks = split_documents(documents, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        raise ValueError("No hay documentos locales para indexar.")
    store = FAISS.from_documents(chunks, OllamaEmbeddings(settings))
    store.save_local(str(settings.faiss_persist_dir))
    return {"documents": len(documents), "chunks": len(chunks)}
