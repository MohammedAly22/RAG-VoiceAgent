"""Build the REAL restaurant benchmark prompts (Section 3 fixture).

Instead of benchmarking the models on generic prompts, we benchmark them on the
*actual* task this product performs: answering restaurant questions **grounded on
the retrieved knowledge-base context** — exactly the prompt `agent/graph.py`
builds at run time (retrieve_kb tool → grounded generation).

Run this ONCE in the `voiceagent` env (it has FAISS + the embedder). It writes
`quantization/restaurant_prompts.json`, which the model benchmarks then consume so
every backend (bf16 / 4-bit / Gemini) answers the *identical* grounded prompts.

    conda activate voiceagent
    python quantization/build_prompts.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from config import CFG                       # noqa: E402
from agent.personas import build_system_prompt  # noqa: E402
from agent.graph import _retrieve, _context_block, _public_docs  # noqa: E402

# Real questions a restaurant customer asks (Egyptian Arabic) — the ones the
# assignment calls out (working hours, grill prices) plus core menu/booking Qs.
QUESTIONS = [
    "مواعيد عمل المطعم إيه؟",
    "أسعار المشويات كام؟",
    "بكام الكشري؟",
    "فين عنوان المطعم؟",
    "عندكم أصناف نباتية؟",
    "إزاي أحجز ترابيزة؟",
]


def main() -> None:
    system = build_system_prompt()
    out = []
    for q in QUESTIONS:
        hits = _retrieve(q)
        if hits:
            user = (f"معلومات من قاعدة المعرفة:\n\n{_context_block(hits)}\n\n"
                    f"بناءً على المعلومات دي فقط، جاوب على السؤال ده بإيجاز بالعامية "
                    f"المصرية واذكر المصدر باختصار في النهاية:\n{q}")
        else:
            user = (f"مفيش معلومات في قاعدة المعرفة تخص السؤال ده. اعتذر بأدب بالعامية "
                    f"المصرية ووضّح إنك تقدر تساعد فقط في مجالك.\nالسؤال: {q}")
        out.append({
            "question": q,
            "system": system,
            "user": user,
            "n_context": len(hits),
            "sources": [f"{d['source']}" + (f" ص{d['page']}" if d.get("page") else "")
                        for d in _public_docs(hits)],
        })
        print(f"  {q:30s} → {len(hits)} context chunks "
              f"({', '.join(s['source'] for s in _public_docs(hits)) or 'none'})")

    dst = Path(__file__).resolve().parent / "restaurant_prompts.json"
    dst.write_text(json.dumps({"model_hint": CFG.llm.vllm.served_model_name,
                               "prompts": out}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\nWrote {len(out)} grounded prompts → {dst}")


if __name__ == "__main__":
    main()
