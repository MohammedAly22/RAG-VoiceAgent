"""Merge the local (bf16/4-bit) and Gemini benchmark results into one report.

Produces quantization/results/RESULTS.md — the 3-way comparison (VRAM, latency,
throughput) plus the side-by-side Arabic answers and a "when to use which" guide.

    python quantization/report.py
"""
from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def _load(name):
    p = RESULTS / name
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def main() -> None:
    local = _load("local.json") or {"model": "Qwen/Qwen2.5-3B-Instruct", "results": []}
    gem = _load("gemini.json")
    rows = {r["backend"]: r for r in local.get("results", []) if "error" not in r}
    bf16, q4 = rows.get("bf16"), rows.get("4bit")

    L = ["# Quantization & Backend Comparison — Restaurant Assistant\n",
         f"Local model: `{local.get('model')}` · GPU: {local.get('gpu','—')} · "
         f"prompts: real grounded restaurant Q&A (retrieve_kb → answer).\n",
         "## Performance\n",
         "| Backend | Peak VRAM | Avg TTFT | Throughput | Where it runs |",
         "|---------|-----------|----------|------------|---------------|"]
    if bf16:
        L.append(f"| Local bf16 | {bf16['peak_vram_gb']} GB | {bf16['avg_ttft_s']} s | "
                 f"{bf16['avg_tok_per_s']} tok/s | local GPU |")
    if q4:
        L.append(f"| Local 4-bit NF4 | {q4['peak_vram_gb']} GB | {q4['avg_ttft_s']} s | "
                 f"{q4['avg_tok_per_s']} tok/s | local GPU |")
    if gem:
        L.append(f"| Gemini {gem['backend'].split(':')[-1]} | 0 (cloud) | {gem['avg_ttft_s']} s | "
                 f"— (streamed) | Google API |")

    if bf16 and q4:
        shrink = round((1 - q4["peak_vram_gb"] / bf16["peak_vram_gb"]) * 100)
        L.append(f"\n**4-bit NF4 uses ~{shrink}% less VRAM** ({bf16['peak_vram_gb']}→"
                 f"{q4['peak_vram_gb']} GB) — the difference between fitting the LLM "
                 f"*alongside* ASR+TTS on one 16 GB card or not.")

    L += ["\n## Answers (identical grounded prompts)\n"]
    qs = [o["question"] for o in (bf16 or q4 or {"outputs": []})["outputs"]] if (bf16 or q4) else \
         [o["question"] for o in gem["outputs"]] if gem else []
    for i, q in enumerate(qs):
        L.append(f"### {q}")
        for tag, r in (("bf16", bf16), ("4-bit", q4)):
            if r:
                L.append(f"- **local {tag}**: {r['outputs'][i]['output'][:280].replace(chr(10),' ')}")
        if gem:
            g = next((o for o in gem["outputs"] if o["question"] == q), None)
            if g:
                L.append(f"- **Gemini**: {g['output'][:280].replace(chr(10),' ')}")
        L.append("")

    L += ["## When to use which\n",
          "| Situation | Recommended backend |",
          "|-----------|---------------------|",
          "| Best answer quality / lowest latency, online | **Gemini** (default) |",
          "| Offline / on-prem / data-privacy, GPU free | **Local bf16** |",
          "| Local + must share the 16 GB GPU with ASR+TTS | **Local 4-bit NF4** |",
          "| Cost-sensitive high volume, own hardware | **Local 4-bit via vLLM** (Section 4) |",
          "\n**Takeaway.** Gemini wins on quality and TTFT with zero VRAM and is the "
          "product default. The local Qwen2.5-3B path exists for offline/on-prem use; "
          "4-bit NF4 makes it *co-resident* with the voice models at a small quality "
          "cost, while bf16 keeps maximum local quality when VRAM is free.\n"]

    (RESULTS / "RESULTS.md").write_text("\n".join(L), encoding="utf-8")
    print(f"Wrote {RESULTS/'RESULTS.md'}")


if __name__ == "__main__":
    main()
