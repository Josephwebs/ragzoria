from langchain_core.embeddings import Embeddings
from app.llm.ollama import post, OllamaError

class OllamaEmbeddings(Embeddings):
    def __init__(self, settings):
        self.settings = settings

    def embed_documents(self, texts):
        result = post(self.settings, "/api/embed", {
            "model": self.settings.embedding_model, "input": texts,
        }).get("embeddings")
        if not isinstance(result, list) or len(result) != len(texts):
            raise OllamaError("Ollama devolvio embeddings invalidos.")
        return result

    def embed_query(self, text):
        return self.embed_documents([text])[0]
