// Voice engine — streaming ASR in, streaming TTS out, barge-in, mixed recording.
//
//  • VAD-gated ASR: audio is only sent to the recognizer while the user is
//    actually speaking. Streaming silence into the model made it hallucinate
//    ("انا بحبك انت بتحبني"), so silence is simply never transmitted.
//  • The server sends the CUMULATIVE transcript of the current utterance on every
//    message (`cumulative: true`), so each new message REPLACES the current
//    utterance's text (no client-side appending → no duplication/stutter). On a
//    final we commit that utterance and start a fresh one; the full transcript is
//    `committed + current`. (This unifies Gemini + QwenCleo, which used to differ.)
//  • TTS plays chunk-by-chunk as it arrives, and every scheduled node is tracked
//    so `stopSpeaking()` can cut the agent off mid-sentence (barge-in).
//  • Mic + agent audio are mixed into one MediaStreamDestination and recorded,
//    so a saved call replays both sides.

const ASR_SR = 16000;

const joinTurns = (a, b) => (a && b ? a + " " + b : a || b);

export function createVoiceSession(opts = {}) {
  const CFG = {
    speechRms: 0.020,        // above this = speech
    releaseRms: 0.012,       // below this = silence (hysteresis)
    startFrames: 3,          // ~0.28s of speech before we open an utterance
    endFrames: 9,            // ~0.85s of silence closes it
    bargeFrames: 5,          // ~0.45s of speech interrupts the agent
    preRollFrames: 4,        // frames kept before speech onset
    ...opts,
  };

  const S = {
    ctx: null, stream: null, proc: null, src: null, analyser: null,
    mixDest: null, recorder: null, recChunks: [],
    asrWS: null, ttsWS: null, nodes: new Set(),
    muted: false, speaking: false, speakLatch: false, playHead: 0,
    committed: "", current: "",     // finalized utterances + the in-progress one
  };

  async function init() {
    S.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    S.ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (S.ctx.state === "suspended") await S.ctx.resume();
    S.src = S.ctx.createMediaStreamSource(S.stream);
    S.analyser = S.ctx.createAnalyser(); S.analyser.fftSize = 256;
    S.mixDest = S.ctx.createMediaStreamDestination();
    S.src.connect(S.mixDest);                       // user side of the recording
    try {
      S.recorder = new MediaRecorder(S.mixDest.stream);
      S.recorder.ondataavailable = (e) => e.data.size && S.recChunks.push(e.data);
      S.recorder.start(1000);
    } catch { /* recording optional */ }
    return S.ctx;
  }

  // ---- VAD-gated streaming ASR ---------------------------------------------
  function startASR({ onPartial, onFinal, onLevel, onSpeechStart, onBargeIn, oneshot } = {}) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/asr/stream`);
    ws.binaryType = "arraybuffer";
    S.asrWS = ws;

    // One-shot: the whole clip is transcribed once on flush (Gemini) — no live
    // partials. Tell the server to suppress streaming transcription.
    if (oneshot) ws.onopen = () => { try { ws.send("oneshot"); } catch {} };

    ws.onmessage = (e) => {
      let m; try { m = JSON.parse(e.data); } catch { return; }
      if (m.text == null) return;
      // Server sends the cumulative transcript of the current utterance → replace.
      S.current = m.text;
      const full = joinTurns(S.committed, S.current).trim();
      if (m.is_final) { S.committed = joinTurns(S.committed, S.current); S.current = ""; }
      (m.is_final ? onFinal : onPartial)?.(full, m.text);
    };

    const inRate = S.ctx.sampleRate;
    const ratio = ASR_SR / inRate;
    const proc = S.ctx.createScriptProcessor(4096, 1, 1);
    S.proc = proc;

    let voiced = 0, silent = 0, inUtt = false, bargeRun = 0;
    const preRoll = [];

    const resample = (b) => {
      const n = Math.max(1, Math.round(b.length * ratio));
      const out = new Float32Array(n);
      for (let i = 0; i < n; i++) out[i] = b[Math.min(b.length - 1, Math.floor(i / ratio))];
      return out;
    };
    const send = (f32) => { if (ws.readyState === 1) ws.send(f32.buffer); };

    proc.onaudioprocess = (e) => {
      const b = e.inputBuffer.getChannelData(0);
      let sum = 0; for (let i = 0; i < b.length; i++) sum += b[i] * b[i];
      const rms = Math.sqrt(sum / b.length);
      onLevel?.(Math.min(1, rms * 6), rms);

      if (S.muted) { voiced = 0; silent = 0; inUtt = false; preRoll.length = 0; return; }

      // While the agent is talking, listen only for a barge-in (and never feed
      // the recognizer, so it can't transcribe the agent's own voice).
      if (S.speaking) {
        bargeRun = rms > CFG.speechRms ? bargeRun + 1 : 0;
        if (bargeRun >= CFG.bargeFrames) { bargeRun = 0; onBargeIn?.(); }
        return;
      }
      bargeRun = 0;

      const isSpeech = rms > (inUtt ? CFG.releaseRms : CFG.speechRms);
      if (!inUtt) {
        preRoll.push(resample(b));
        if (preRoll.length > CFG.preRollFrames) preRoll.shift();
        voiced = isSpeech ? voiced + 1 : 0;
        if (voiced >= CFG.startFrames) {           // utterance opens
          inUtt = true; silent = 0;
          onSpeechStart?.();
          preRoll.forEach(send); preRoll.length = 0;
        }
        return;
      }
      send(resample(b));                            // only speech is transmitted
      silent = isSpeech ? 0 : silent + 1;
      if (silent >= CFG.endFrames) {                // utterance closes → finalize
        inUtt = false; voiced = 0; silent = 0;
        try { ws.readyState === 1 && ws.send("flush"); } catch {}
      }
    };

    S.src.connect(proc);
    const mute = S.ctx.createGain(); mute.gain.value = 0;   // keep node alive, no echo
    proc.connect(mute); mute.connect(S.ctx.destination);
  }

  function flushASR() { try { S.asrWS?.readyState === 1 && S.asrWS.send("flush"); } catch {} }
  function resetTranscript() { S.committed = ""; S.current = ""; }
  function getTranscript() { return joinTurns(S.committed, S.current).trim(); }
  function stopASR() {
    try { S.asrWS?.readyState === 1 && S.asrWS.send("close"); S.asrWS?.close(); } catch {}
    try { S.proc?.disconnect(); } catch {}
    S.asrWS = null; S.proc = null;
  }

  // ---- streaming TTS (interruptible) ---------------------------------------
  function speak(text, voice, { onStart } = {}) {
    return new Promise((resolve) => {
      if (!text?.trim()) return resolve();
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/api/tts/stream`);
      ws.binaryType = "arraybuffer";
      S.ttsWS = ws;
      let sr = 24000, started = false, pending = 0, ended = false, cancelled = false;
      S.playHead = Math.max(S.playHead, S.ctx.currentTime);
      S.speaking = true;

      const done = () => {
        if (cancelled || (ended && pending === 0)) {
          if (!S.speakLatch) S.speaking = false;   // latch holds it across a streamed turn
          S.ttsWS = null; resolve();
        }
      };
      ws._cancel = () => { cancelled = true; try { ws.close(); } catch {} done(); };

      ws.onopen = () => ws.send(JSON.stringify({ text, voice }));
      ws.onmessage = (e) => {
        if (cancelled) return;
        if (typeof e.data === "string") {
          let ev; try { ev = JSON.parse(e.data); } catch { return; }
          if (ev.sample_rate) sr = ev.sample_rate;
          if (ev.event === "end") { ended = true; try { ws.close(); } catch {} done(); }
          return;
        }
        const i16 = new Int16Array(e.data);
        if (!i16.length) return;
        const buf = S.ctx.createBuffer(1, i16.length, sr);
        const ch = buf.getChannelData(0);
        for (let i = 0; i < i16.length; i++) ch[i] = i16[i] / 32768;
        const node = S.ctx.createBufferSource();
        node.buffer = buf;
        node.connect(S.analyser); S.analyser.connect(S.ctx.destination);
        node.connect(S.mixDest);                    // agent side of the recording
        const t = Math.max(S.ctx.currentTime + 0.02, S.playHead);
        node.start(t);
        S.playHead = t + buf.duration;
        S.nodes.add(node); pending++;
        node.onended = () => { S.nodes.delete(node); pending--; done(); };
        if (!started) { started = true; onStart?.(); }
      };
      ws.onerror = () => { ended = true; done(); };
      ws.onclose = () => { ended = true; done(); };
    });
  }

  // Cut the agent off immediately (barge-in).
  function stopSpeaking() {
    S.speakLatch = false;
    try { S.ttsWS?._cancel?.(); } catch {}
    for (const n of S.nodes) { try { n.stop(); } catch {} }
    S.nodes.clear();
    S.playHead = S.ctx ? S.ctx.currentTime : 0;
    S.speaking = false;
  }

  // Hold the "agent speaking" state across a turn whose sentences are streamed to
  // TTS one by one (so the mic keeps gating for barge-in between sentences).
  function beginSpeaking() { S.speakLatch = true; S.speaking = true; }
  function endSpeaking() { S.speakLatch = false; if (S.nodes.size === 0) S.speaking = false; }

  function agentLevel() {
    if (!S.analyser) return 0;
    const d = new Uint8Array(S.analyser.frequencyBinCount);
    S.analyser.getByteFrequencyData(d);
    let s = 0; for (let i = 0; i < d.length; i++) s += d[i];
    return Math.min(1, (s / d.length / 255) * 2.4);
  }

  async function stopRecording() {
    return new Promise((res) => {
      if (!S.recorder || S.recorder.state === "inactive") return res(null);
      S.recorder.onstop = () => res(new Blob(S.recChunks, { type: "audio/webm" }));
      try { S.recorder.stop(); } catch { res(null); }
    });
  }

  function close() {
    stopSpeaking(); stopASR();
    try { S.stream?.getTracks().forEach((t) => t.stop()); } catch {}
    try { S.ctx?.close(); } catch {}
  }

  return {
    init, startASR, flushASR, stopASR, resetTranscript, getTranscript,
    speak, stopSpeaking, beginSpeaking, endSpeaking, agentLevel, stopRecording, close,
    setMuted: (m) => { S.muted = m; },
    isSpeaking: () => S.speaking,
  };
}
