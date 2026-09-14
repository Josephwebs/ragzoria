import json
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config.settings import get_settings
from app.retrievers.faiss_retriever import retrieve

def main():
    settings = get_settings()
    cases = json.loads((ROOT / "evaluation/questions.json").read_text())
    hits = 0
    for case in cases:
        started = time.perf_counter()
        pairs = retrieve(case["question"], settings)
        sources = [doc.metadata["source"] for doc, _ in pairs]
        hit = case["expected_source"] in sources
        hits += hit
        print(json.dumps({
            "question": case["question"], "hit": hit, "chunks": len(pairs),
            "expected": case["expected_source"], "found": sources,
            "distances": [float(distance) for _, distance in pairs],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }, ensure_ascii=False))
    print(f"Hit Rate@{settings.top_k}: {hits}/{len(cases)} = {hits/len(cases):.1%}")
    print("Retrieval only; does not evaluate generated answers.")

if __name__ == "__main__":
    main()
