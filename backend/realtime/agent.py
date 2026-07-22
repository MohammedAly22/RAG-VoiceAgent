"""Real-time voice agent worker (LiveKit Agents 1.6).

Runs the STT → LLM → TTS pipeline inside a LiveKit room:

  • STT  : QwenCleoSTT — wraps our ASR service (/transcribe), made streaming via
           stt.StreamAdapter + Silero VAD.
  • LLM  : Gemini (livekit google plugin) with @function_tool tools — the SAME
           persona + RAG retrieval + mock order lookup as the text agent.
  • TTS  : OmniVoiceTTS — wraps our TTS service (/synthesize).
  • VAD  : Silero (voice activity → endpointing + barge-in).
  • EoU  : MultilingualModel turn detector (Arabic-capable end-of-utterance).

Barge-in is handled natively by AgentSession (`allow_interruptions=True`,
`min_interruption_duration`). Tool calls + transcripts are logged to
data/logs/livekit_agent.log and streamed to the browser as transcriptions.

Run:  scripts/start_livekit.sh   (server)  then  scripts/start_livekit_agent.sh
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CFG  # noqa: E402
from agent.personas import build_system_prompt  # noqa: E402
from agent.tools import NO_CONTEXT  # noqa: E402
from rag.store import get_store  # noqa: E402

from livekit import agents, rtc  # noqa: E402
from livekit.agents import (Agent, AgentSession, function_tool, RunContext,  # noqa: E402
                            JobContext, WorkerOptions, cli, stt, tts, APIConnectOptions)
from livekit.plugins import silero  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | LK-AGENT | %(levelname)s | %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("lk.agent")

ASR_URL = f"http://{CFG.asr.host}:{CFG.asr.port}"
TTS_URL = f"http://{CFG.tts.host}:{CFG.tts.port}"


# ---------------------------------------------------------------------------
# STT adapter — our QwenCleo ASR service
# ---------------------------------------------------------------------------
class QwenCleoSTT(stt.STT):
    def __init__(self) -> None:
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))

    async def _recognize_impl(self, buffer, *, language=None,
                              conn_options: APIConnectOptions = None) -> stt.SpeechEvent:
        frame = rtc.combine_audio_frames(buffer)
        pcm = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32) / 32768.0
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, pcm, frame.sample_rate, format="WAV")
        import base64
        text = ""
        try:
            r = await asyncio.to_thread(
                requests.post, f"{ASR_URL}/transcribe",
                json={"audio_b64": base64.b64encode(buf.getvalue()).decode()}, timeout=30)
            text = (r.json() or {}).get("text", "").strip()
        except Exception as e:  # noqa: BLE001
            log.warning("ASR call failed: %s", e)
        return stt.SpeechEvent(
            type=stt.SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[stt.SpeechData(language=CFG.asr.language, text=text)])


# ---------------------------------------------------------------------------
# TTS adapter — our OmniVoice TTS service
# ---------------------------------------------------------------------------
class OmniVoiceTTS(tts.TTS):
    def __init__(self) -> None:
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False),
                         sample_rate=CFG.tts.sample_rate, num_channels=1)

    def synthesize(self, text: str, *, conn_options=None) -> "OmniVoiceStream":
        return OmniVoiceStream(tts=self, input_text=text,
                               conn_options=conn_options or APIConnectOptions())


class OmniVoiceStream(tts.ChunkedStream):
    async def _run(self, output_emitter) -> None:
        text = self.input_text
        pcm = b""
        try:
            r = await asyncio.to_thread(
                requests.post, f"{TTS_URL}/synthesize",
                json={"text": text, "voice": CFG.tts.active_voice}, timeout=120)
            import soundfile as sf
            data, sr = sf.read(io.BytesIO(r.content), dtype="int16")
            pcm = data.tobytes()
        except Exception as e:  # noqa: BLE001
            log.warning("TTS call failed: %s", e)
            sr = CFG.tts.sample_rate
        output_emitter.initialize(
            request_id="va-tts", sample_rate=int(sr), num_channels=1,
            mime_type="audio/pcm")
        if pcm:
            output_emitter.push(pcm)
        output_emitter.flush()


# ---------------------------------------------------------------------------
# The Agent (persona + tools)
# ---------------------------------------------------------------------------
class VoiceAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=build_system_prompt())

    @function_tool
    async def retrieve_kb(self, context: RunContext, query: str) -> str:
        """ابحث في قاعدة المعرفة عن معلومات تخص سؤال المستخدم قبل الإجابة."""
        store = get_store()
        hits = store.search(query, top_k=CFG.rag.top_k)
        log.info("tool retrieve_kb(%r) → %d hits (top=%.3f)", query, len(hits),
                 hits[0]["score"] if hits else 0.0)
        if not hits or hits[0]["score"] < CFG.rag.score_threshold:
            return NO_CONTEXT
        blocks = []
        for i, h in enumerate(hits, 1):
            cite = h["source"] + (f" ص{h['page']}" if h.get("page") else "")
            blocks.append(f"[{i}] (المصدر: {cite})\n{h['text']}")
        return "معلومات من قاعدة المعرفة:\n\n" + "\n\n---\n\n".join(blocks)

    @function_tool
    async def get_order_status(self, context: RunContext, order_id: str) -> str:
        """اعرف حالة طلب دليفري بواسطة رقم الطلب."""
        log.info("tool get_order_status(%r)", order_id)
        demo = {"1001": "الطلب في المطبخ، هيوصل خلال ٤٠ دقيقة.",
                "1002": "الطلب خرج مع الدليفري، هيوصل خلال ١٠ دقايق.",
                "1003": "الطلب اتسلّم بنجاح."}
        return demo.get(order_id.strip(), f"مفيش طلب بالرقم {order_id}.")


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    log.info("agent joined room=%s", ctx.room.name)

    # Turn detection (EoU). Prefer the multilingual model; fall back to VAD-only.
    turn_detection = None
    try:
        from livekit.plugins.turn_detector.multilingual import MultilingualModel
        turn_detection = MultilingualModel()
        log.info("EoU: multilingual turn-detector loaded")
    except Exception as e:  # noqa: BLE001
        log.warning("EoU model unavailable, using VAD endpointing: %s", e)

    from livekit.plugins import google
    llm = google.LLM(model=CFG.llm.gemini.model,
                     api_key=os.environ.get("GEMINI_API_KEY"))

    vad = silero.VAD.load()
    session = AgentSession(
        stt=stt.StreamAdapter(stt=QwenCleoSTT(), vad=vad),
        llm=llm,
        tts=OmniVoiceTTS(),
        vad=vad,
        turn_detection=turn_detection,
        allow_interruptions=CFG.livekit.allow_interruptions,          # barge-in
        min_interruption_duration=CFG.livekit.min_interruption_duration,
        min_endpointing_delay=CFG.eou.min_silence_ms / 1000.0,
    )
    await session.start(agent=VoiceAgent(), room=ctx.room)
    await session.generate_reply(instructions=f"رحّب بالعميل بإيجاز بهذه الجملة: {CFG.agent.greeting}")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
