"""Section 3 — Quantization trade-off benchmark on the RESTAURANT use case.

Loads the local LLM (default Qwen2.5-3B-Instruct) twice — full precision (bf16)
and 4-bit NF4 (bitsandbytes) — and runs the SAME grounded restaurant prompts the
app uses at run time (built by `build_prompts.py`: retrieve_kb → grounded answer).

Measures, per precision:
  • peak VRAM (GB)                 → does it fit the 16 GB card alongside ASR+TTS?
  • time-to-first-token (s)        → perceived latency
  • decode throughput (tok/s)      → speaking speed once streaming
  • the actual Arabic answers      → quality comparison (saved verbatim)

Writes quantization/results/local.json. Run `report.py` afterwards to merge with
`gemini.json` into the final RESULTS.md comparison.

    conda activate test-qwen     # torch + transformers + bitsandbytes
    python quantization/quantize_benchmark.py [--model Qwen/Qwen2.5-3B-Instruct] [--modes bf16,4bit]
"""
from __future__ import annotations

import argparse
import gc
import json
import time
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

# Grounded restaurant prompts (built by build_prompts.py). Fallback to a couple of
# generic ones only if the fixture is missing, so the script still runs standalone.
_fix = HERE / "restaurant_prompts.json"
if _fix.exists():
    PROMPTS = json.loads(_fix.read_text("utf-8"))["prompts"]
else:
    PROMPTS = [{"question": q, "system": "أنت مساعد مطعم مصري. رد بالعامية باختصار.", "user": q}
               for q in ("مواعيد عمل المطعم إيه؟", "أسعار المشويات كام؟", "بكام الكشري؟")]

MAX_NEW = 160


def load(model_id: str, mode: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_id)
    if mode == "4bit":
        from transformers import BitsAndBytesConfig
        kw = dict(device_map="cuda", quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True))
    else:
        kw = dict(device_map="cuda", torch_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(model_id, **kw).eval()
    return model, tok


@torch.inference_mode()
def bench(model, tok, mode: str) -> dict:
    torch.cuda.reset_peak_memory_stats()
    outs, ttfts, tps = [], [], []
    for p in PROMPTS:
        msgs = [{"role": "system", "content": p["system"]},
                {"role": "user", "content": p["user"]}]
        inputs = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                         return_tensors="pt").to("cuda")
        torch.cuda.synchronize(); t0 = time.time()
        _ = model.generate(inputs, max_new_tokens=1, do_sample=False, pad_token_id=tok.eos_token_id)
        torch.cuda.synchronize(); ttft = time.time() - t0

        torch.cuda.synchronize(); t1 = time.time()
        out = model.generate(inputs, max_new_tokens=MAX_NEW, do_sample=False, pad_token_id=tok.eos_token_id)
        torch.cuda.synchronize(); dt = time.time() - t1
        n_new = out.shape[1] - inputs.shape[1]
        text = tok.decode(out[0, inputs.shape[1]:], skip_special_tokens=True).strip()
        outs.append({"question": p["question"], "output": text})
        ttfts.append(ttft); tps.append(n_new / dt if dt > 0 else 0)
        print(f"    {p['question']:26s} ttft={ttft:.2f}s {n_new/dt:.1f} tok/s")
    peak = torch.cuda.max_memory_allocated() / 1e9
    return {"backend": mode, "peak_vram_gb": round(peak, 2),
            "avg_ttft_s": round(sum(ttfts) / len(ttfts), 3),
            "avg_tok_per_s": round(sum(tps) / len(tps), 1), "outputs": outs}


def run(model_id: str, modes: list[str]) -> None:
    results = []
    for mode in modes:
        print(f"\n=== {model_id} [{mode}] ===")
        try:
            model, tok = load(model_id, mode)
            r = bench(model, tok, mode)
            print(f"  peak VRAM={r['peak_vram_gb']}GB  TTFT={r['avg_ttft_s']}s  {r['avg_tok_per_s']} tok/s")
            results.append(r)
            del model, tok
        except Exception as e:  # noqa: BLE001
            print(f"  ! {mode} failed: {e}")
            results.append({"backend": mode, "error": str(e)})
        gc.collect(); torch.cuda.empty_cache()

    (RESULTS / "local.json").write_text(
        json.dumps({"model": model_id, "gpu": torch.cuda.get_device_name(0),
                    "max_new_tokens": MAX_NEW, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\nSaved → {RESULTS/'local.json'}   (now run: python quantization/report.py)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-3B-Instruct")
    ap.add_argument("--modes", default="bf16,4bit")
    a = ap.parse_args()
    run(a.model, [m.strip() for m in a.modes.split(",") if m.strip()])
