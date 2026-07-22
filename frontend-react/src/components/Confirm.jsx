import React, { createContext, useCallback, useContext, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, X } from "lucide-react";

// Promise-based confirmation dialog. `const ok = await confirm({...})`.
const Ctx = createContext(async () => false);
export const useConfirm = () => useContext(Ctx);

export function ConfirmProvider({ children }) {
  const [dlg, setDlg] = useState(null);
  const resolver = useRef(null);

  const confirm = useCallback((opts = {}) => new Promise((resolve) => {
    resolver.current = resolve;
    setDlg({
      title: opts.title || "تأكيد",
      message: opts.message || "هل أنت متأكد؟",
      confirmText: opts.confirmText || "حذف",
      cancelText: opts.cancelText || "إلغاء",
      danger: opts.danger !== false,
    });
  }), []);

  const close = (val) => { resolver.current?.(val); resolver.current = null; setDlg(null); };

  return (
    <Ctx.Provider value={confirm}>
      {children}
      <AnimatePresence>
        {dlg && (
          <motion.div className="modal-bg" onClick={() => close(false)}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <motion.div className="confirm" onClick={(e) => e.stopPropagation()}
              initial={{ scale: 0.94, opacity: 0, y: 10 }} animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.96, opacity: 0 }} transition={{ type: "spring", stiffness: 380, damping: 26 }}>
              <button className="confirm-x" onClick={() => close(false)}><X size={16} /></button>
              <div className={"confirm-ic" + (dlg.danger ? " danger" : "")}>
                <AlertTriangle size={24} />
              </div>
              <div className="confirm-title">{dlg.title}</div>
              <div className="confirm-msg">{dlg.message}</div>
              <div className="confirm-actions">
                <button className="btn ghost" onClick={() => close(false)}>{dlg.cancelText}</button>
                <button className={"btn" + (dlg.danger ? " danger" : "")} onClick={() => close(true)}>{dlg.confirmText}</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </Ctx.Provider>
  );
}
