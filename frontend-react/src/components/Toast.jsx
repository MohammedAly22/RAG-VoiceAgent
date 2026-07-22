import React, { createContext, useCallback, useContext, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, AlertTriangle, Info, X } from "lucide-react";

const Ctx = createContext(() => {});
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const push = useCallback((message, kind = "info") => {
    const id = Math.random().toString(36).slice(2);
    setItems((x) => [...x, { id, message, kind }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 3600);
  }, []);
  const icon = { ok: <CheckCircle2 size={17} />, bad: <AlertTriangle size={17} />, info: <Info size={17} /> };

  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="toast-wrap">
        <AnimatePresence>
          {items.map((t) => (
            <motion.div key={t.id} className={"toast " + t.kind}
              initial={{ opacity: 0, x: -30, scale: .95 }} animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: -20, scale: .95 }} transition={{ type: "spring", stiffness: 380, damping: 28 }}>
              <div className="ti">{icon[t.kind]}</div>
              <div className="tt">{t.message}</div>
              <X size={15} style={{ cursor: "pointer", color: "var(--muted)", marginInlineStart: "auto" }}
                onClick={() => setItems((x) => x.filter((i) => i.id !== t.id))} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </Ctx.Provider>
  );
}
