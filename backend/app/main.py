from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.chat import router
from app.config.settings import get_settings

app = FastAPI(title="Ragzor Assistant")
app.add_middleware(
    CORSMiddleware, allow_origins=get_settings().cors_origins.split(","),
    allow_methods=["POST"], allow_headers=["Content-Type"],
)
app.include_router(router)

@app.get("/api/health")
def health():
    return {"status": "ok"}
