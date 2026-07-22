import React, { useEffect, useRef, useState } from "react";
import { ChevronDown, Check } from "lucide-react";

// Custom styled dropdown (replaces the native <select>). Keyboard-free but
// fully themed: green focus ring, animated menu, custom scrollbar.
export default function Select({ value, options, onChange, placeholder = "اختر…" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef();
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const cur = options.find((o) => o.value === value);
  return (
    <div className="sel" ref={ref}>
      <button type="button" className={"sel-btn" + (open ? " open" : "")} onClick={() => setOpen((v) => !v)}>
        {cur?.icon}
        <span>{cur ? cur.label : placeholder}</span>
        <ChevronDown size={17} className="chev" />
      </button>
      {open && (
        <div className="sel-menu">
          {options.map((o) => (
            <div key={o.value} className={"sel-opt" + (o.value === value ? " sel" : "")}
              onClick={() => { onChange(o.value); setOpen(false); }}>
              {o.icon}
              <span style={{ flex: 1 }}>{o.label}</span>
              {o.value === value && <Check size={15} />}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
