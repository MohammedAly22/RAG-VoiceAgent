import { useEffect, useRef } from "react";

// Animated canvas voice orb (inspired by Sano). Reacts to the user's mic level
// and the agent's audio level — whoever is louder drives the pulse + glow.
// Re-palletted to a crisp monochrome (graphite ink + white sheen) so it fits the
// black/white brand; `speaking` tints it subtly (agent = cool, user = warm-neutral).
export default function VoiceOrb({ micLevel = 0, agentLevel = 0, speaking = "idle", size = 300 }) {
  const canvasRef = useRef(null);
  const raf = useRef(0);
  const state = useRef({ micLevel, agentLevel, speaking, t: 0, smooth: 0 });

  useEffect(() => { state.current.micLevel = micLevel; }, [micLevel]);
  useEffect(() => { state.current.agentLevel = agentLevel; }, [agentLevel]);
  useEffect(() => { state.current.speaking = speaking; }, [speaking]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size * dpr; canvas.height = size * dpr;
    ctx.scale(dpr, dpr);
    const cx = size / 2, cy = size / 2;
    const baseR = size * 0.27;

    const draw = () => {
      const s = state.current;
      s.t += 0.016;
      const target = Math.max(s.micLevel, s.agentLevel * 1.1);
      s.smooth += (target - s.smooth) * 0.18;
      const lvl = Math.min(1, s.smooth);

      const isAgent = s.speaking === "agent";
      const isUser = s.speaking === "user";
      // emerald-green gradients: agent = bright emerald, user = teal-green, idle = deep green
      const palette = isAgent
        ? [[52, 211, 153], [16, 185, 129], [34, 197, 94]]
        : isUser
        ? [[45, 212, 191], [20, 184, 166], [52, 211, 153]]
        : [[16, 185, 129], [6, 95, 70], [34, 197, 94]];

      ctx.clearRect(0, 0, size, size);

      // outer glow rings driven by level
      for (let i = 3; i >= 1; i--) {
        const rr = baseR * (1 + 0.18 * i) + lvl * 26 * i + Math.sin(s.t * 1.4 + i) * 3;
        const g = ctx.createRadialGradient(cx, cy, baseR * 0.6, cx, cy, rr);
        const [r, gc, b] = palette[i % palette.length];
        g.addColorStop(0, `rgba(${r},${gc},${b},${0.06 + lvl * 0.12})`);
        g.addColorStop(1, `rgba(${r},${gc},${b},0)`);
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(cx, cy, rr, 0, Math.PI * 2); ctx.fill();
      }

      // wobbling blob (the orb body)
      const R = baseR * (1 + lvl * 0.12) + Math.sin(s.t * 1.1) * 2;
      ctx.save();
      ctx.beginPath();
      const pts = 64;
      for (let i = 0; i <= pts; i++) {
        const a = (i / pts) * Math.PI * 2;
        const wob = 1
          + 0.045 * Math.sin(a * 3 + s.t * 1.7)
          + 0.03 * Math.sin(a * 5 - s.t * 1.2)
          + lvl * 0.10 * Math.sin(a * 2 + s.t * 3);
        const rr = R * wob;
        const x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.clip();

      // gradient fill inside the blob
      const rot = s.t * 0.4;
      const gx = cx + Math.cos(rot) * R, gy = cy + Math.sin(rot) * R;
      const grad = ctx.createLinearGradient(cx - R, cy - R, gx, gy);
      const [c0, c1, c2] = palette;
      grad.addColorStop(0, `rgb(${c0[0]},${c0[1]},${c0[2]})`);
      grad.addColorStop(0.5, `rgb(${c1[0]},${c1[1]},${c1[2]})`);
      grad.addColorStop(1, `rgb(${c2[0]},${c2[1]},${c2[2]})`);
      ctx.fillStyle = grad;
      ctx.fillRect(cx - R * 1.4, cy - R * 1.4, R * 2.8, R * 2.8);

      // moving light streaks (white sheen)
      for (let i = 0; i < 3; i++) {
        const a = s.t * (0.5 + i * 0.3) + i * 2;
        const lx = cx + Math.cos(a) * R * 0.5;
        const ly = cy + Math.sin(a * 1.3) * R * 0.5;
        const lg = ctx.createRadialGradient(lx, ly, 0, lx, ly, R * 0.8);
        lg.addColorStop(0, `rgba(255,255,255,${0.14 + lvl * 0.22})`);
        lg.addColorStop(1, "rgba(255,255,255,0)");
        ctx.fillStyle = lg;
        ctx.fillRect(cx - R * 1.4, cy - R * 1.4, R * 2.8, R * 2.8);
      }
      // top-left sheen
      const sheen = ctx.createRadialGradient(cx - R * 0.4, cy - R * 0.45, 0, cx - R * 0.4, cy - R * 0.45, R * 1.1);
      sheen.addColorStop(0, "rgba(255,255,255,0.35)");
      sheen.addColorStop(0.4, "rgba(255,255,255,0.05)");
      sheen.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = sheen;
      ctx.fillRect(cx - R * 1.4, cy - R * 1.4, R * 2.8, R * 2.8);
      ctx.restore();

      // crisp rim
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(255,255,255,${0.14 + lvl * 0.22})`;
      ctx.lineWidth = 1.5; ctx.stroke();

      raf.current = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf.current);
  }, [size]);

  return <canvas ref={canvasRef} style={{ width: size, height: size }} />;
}
