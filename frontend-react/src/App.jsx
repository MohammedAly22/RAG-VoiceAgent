import React, { useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { LayoutDashboard, MessageSquare, Database, ScrollText, Phone,
         Settings as Cog, Bot, Wand2, Sun, Moon, PanelRightClose, PanelRightOpen } from "lucide-react";
import { api } from "./lib/api.js";
import Splash from "./pages/Splash.jsx";
import Setup from "./pages/Setup.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Chat from "./pages/Chat.jsx";
import DataTab from "./pages/Data.jsx";
import Logs from "./pages/Logs.jsx";
import VoiceCall from "./pages/VoiceCall.jsx";
import SettingsTab from "./pages/Settings.jsx";
import { SessionPage, CallPage, LogPage } from "./pages/Details.jsx";

const TABS = [
  { id: "dashboard", label: "لوحة التحكم", icon: LayoutDashboard, group: "الرئيسية" },
  { id: "chat", label: "الدردشة", icon: MessageSquare, group: "الرئيسية" },
  { id: "data", label: "قاعدة المعرفة", icon: Database, group: "الإدارة" },
  { id: "logs", label: "السجلات", icon: ScrollText, group: "الإدارة" },
  { id: "settings", label: "الإعدادات", icon: Cog, group: "الإدارة" },
];
const TITLES = { session: "تفاصيل المحادثة", call: "تفاصيل المكالمة", log: "تفاصيل السجل" };

export default function App() {
  const [cfg, setCfg] = useState(null);
  const [route, setRoute] = useState({ name: "dashboard" });
  const [forceSetup, setForceSetup] = useState(false);
  const [splash, setSplash] = useState(true);
  const [inCall, setInCall] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(() => localStorage.getItem("va-nav") === "1");
  const [theme, setTheme] = useState(() => localStorage.getItem("va-theme") || "dark");

  useEffect(() => { localStorage.setItem("va-nav", navCollapsed ? "1" : "0"); }, [navCollapsed]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("va-theme", theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    document.documentElement.classList.add("theming");
    setTheme((t) => (t === "dark" ? "light" : "dark"));
    setTimeout(() => document.documentElement.classList.remove("theming"), 500);
  }, []);

  const load = () => api.config().then(setCfg).catch(() => setCfg({ error: true }));
  useEffect(() => { load(); }, []);

  const go = useCallback((name, id) => setRoute({ name, id }), []);

  if (splash) return <Splash cfg={cfg} theme={theme} onDone={() => setSplash(false)} />;
  if (!cfg) return <div className="empty" style={{ marginTop: 120 }}>جاري التحميل…</div>;
  if (!(cfg.agent?.configured) || forceSetup)
    return <Setup cfg={cfg} onDone={() => { setForceSetup(false); load().then(() => go("dashboard")); }} />;

  const PAGES = { dashboard: Dashboard, chat: Chat, data: DataTab, logs: Logs, settings: SettingsTab,
                  session: SessionPage, call: CallPage, log: LogPage };
  const Active = PAGES[route.name] || Dashboard;
  const title = TITLES[route.name] || TABS.find((t) => t.id === route.name)?.label;
  const groups = [...new Set(TABS.map((t) => t.group))];
  const isChat = route.name === "chat";

  return (
    <div className={"app" + (navCollapsed ? " nav-collapsed" : "")}>
      {inCall && <VoiceCall cfg={cfg} onClose={() => setInCall(false)} />}

      <aside className="sidebar">
        <div className="brand">
          <div className="logo"><Bot size={22} /></div>
          <div style={{ minWidth: 0 }} className="brand-txt">
            <h1>{cfg.agent?.name || cfg.app_name}</h1>
            <small>{cfg.brand}</small>
          </div>
          <button className="nav-toggle" onClick={() => setNavCollapsed((v) => !v)}
            title={navCollapsed ? "توسيع" : "طي القائمة"}>
            {navCollapsed ? <PanelRightOpen size={18} /> : <PanelRightClose size={18} />}
          </button>
        </div>
        {groups.map((g) => (
          <React.Fragment key={g}>
            <div className="nav-sep">{g}</div>
            {TABS.filter((t) => t.group === g).map((t) => (
              <button key={t.id} className={"nav-item" + (route.name === t.id ? " active" : "")}
                onClick={() => go(t.id)} title={t.label}>
                <t.icon size={18} /> <span>{t.label}</span>
              </button>
            ))}
          </React.Fragment>
        ))}
        <div className="spacer" />
        <button className="nav-item" onClick={() => setForceSetup(true)} title="إعداد الوكيل">
          <Wand2 size={18} /> <span>إعداد الوكيل</span>
        </button>
        <div className="llm-info" style={{ padding: "8px 12px", fontSize: 11, color: "var(--faint)" }}>
          LLM: {cfg.llm?.backend} · {cfg.llm?.backend === "gemini" ? cfg.llm?.gemini_model : cfg.llm?.vllm_model}
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <h2>{title}</h2>
          <div className="sub">— {cfg.agent?.name}</div>
          <div className="spacer" />
          <Health services={cfg.services} />
          <button className="theme-toggle" onClick={toggleTheme} title={theme === "dark" ? "الوضع الفاتح" : "الوضع الداكن"}>
            <AnimatePresence mode="wait" initial={false}>
              <motion.span key={theme} initial={{ rotate: -90, opacity: 0, scale: .6 }}
                animate={{ rotate: 0, opacity: 1, scale: 1 }} exit={{ rotate: 90, opacity: 0, scale: .6 }}
                transition={{ duration: .25 }} style={{ display: "grid" }}>
                {theme === "dark" ? <Sun size={19} /> : <Moon size={19} />}
              </motion.span>
            </AnimatePresence>
          </button>
          <button className="call-cta" onClick={() => setInCall(true)}>
            <span className="dot" /> <Phone size={16} /> <span>مكالمة صوتية</span>
          </button>
        </header>

        <section className="content" style={isChat ? { padding: 0, display: "flex" } : {}}>
          <AnimatePresence mode="wait">
            <motion.div key={route.name + (route.id || "")}
              style={{ width: "100%", display: "flex", flex: 1, minHeight: 0 }}
              initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22 }}>
              <Active cfg={cfg} reloadCfg={load} go={go} id={route.id} goCall={() => setInCall(true)} />
            </motion.div>
          </AnimatePresence>
        </section>
      </main>
    </div>
  );
}

function Health({ services = {} }) {
  const items = [["ASR", services.asr], ["TTS", services.tts], ["EoU", services.eou]];
  return (
    <div style={{ display: "flex", gap: 6 }}>
      {items.map(([n, ok]) => (
        <span key={n} className={"pill" + (ok ? " ok" : "")} title={n} style={{ opacity: ok ? 1 : .55 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", display: "inline-block",
            background: ok ? "var(--ok)" : "var(--faint)" }} /> {n}
        </span>
      ))}
    </div>
  );
}
