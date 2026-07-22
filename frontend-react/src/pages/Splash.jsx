import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, Wand2 } from "lucide-react";
import VoiceOrb from "../components/VoiceOrb.jsx";

// Animated splash. Plays a tiny UI chime on the user's first gesture — but never
// synthesizes the agent's voice on startup (that added latency + unwanted audio).
// If the agent isn't configured yet, the button leads into the setup wizard.
export default function Splash({ cfg, onDone }) {
  const [entering, setEntering] = useState(false);
  const name = cfg?.agent?.name || cfg?.app_name || "Voice Agent";
  const configured = cfg?.agent?.configured;

  useEffect(() => { const t = setTimeout(() => enter(false), 5000); return () => clearTimeout(t); }, []);

  const chime = () => {
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      const ac = new AC(); const now = ac.currentTime;
      [[523.25, 0], [783.99, 0.14]].forEach(([f, dt]) => {
        const o = ac.createOscillator(), g = ac.createGain();
        o.type = "sine"; o.frequency.value = f;
        g.gain.setValueAtTime(0.0001, now + dt);
        g.gain.exponentialRampToValueAtTime(0.22, now + dt + 0.04);
        g.gain.exponentialRampToValueAtTime(0.0001, now + dt + 0.7);
        o.connect(g); g.connect(ac.destination); o.start(now + dt); o.stop(now + dt + 0.75);
      });
    } catch { /* ignore */ }
  };
  const enter = (withSound) => {
    if (entering) return;
    setEntering(true);
    if (withSound) chime();     // only the short UI chime — no voice synthesis on start
    setTimeout(onDone, 620);
  };

  return (
    <motion.div className="splash" initial={{ opacity: 0 }} animate={{ opacity: entering ? 0 : 1 }} transition={{ duration: .6 }}>
      <div className="splash-bg" />
      <motion.div className="splash-center" initial={{ scale: .9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: .8, ease: "easeOut" }}>
        <VoiceOrb speaking="agent" agentLevel={0.35} size={210} />
        <motion.h1 className="splash-title" initial={{ y: 14, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: .3 }}>
          {name}
        </motion.h1>
        <motion.p className="splash-sub" initial={{ y: 14, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: .45 }}>
          مساعد صوتي ذكي · {cfg?.brand || "Electro-Pi"}
        </motion.p>
        <motion.button className="splash-btn" onClick={() => enter(true)}
          initial={{ y: 14, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: .7 }}>
          {configured ? <>ابدأ التجربة <ArrowLeft size={18} /></> : <><Wand2 size={18} /> إعداد الوكيل</>}
        </motion.button>
      </motion.div>
      <div className="splash-dots">
        {[0, 1, 2].map((i) => (
          <motion.span key={i} animate={{ opacity: [0.2, 1, 0.2] }}
            transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.2 }} />
        ))}
      </div>
    </motion.div>
  );
}
