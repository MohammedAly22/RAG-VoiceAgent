import React from "react";
import { motion } from "framer-motion";

// Shimmering placeholders shown while data loads, so the UI never "pops" in.
export const SkelLine = ({ w = "100%", h = 11, style }) => (
  <div className="sk sk-line" style={{ width: w, height: h, ...style }} />
);

export const SkelRows = ({ n = 4 }) => (
  <>
    {Array.from({ length: n }).map((_, i) => (
      <motion.div key={i} className="sk-row"
        initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}>
        <div className="sk sk-circle" style={{ width: 38, height: 38, flex: "none" }} />
        <div style={{ flex: 1 }}>
          <SkelLine w="55%" />
          <SkelLine w="80%" h={9} style={{ marginTop: 7 }} />
        </div>
        <SkelLine w={60} h={20} style={{ borderRadius: 20 }} />
      </motion.div>
    ))}
  </>
);

export const SkelStats = ({ n = 4 }) => (
  <div className="stat-grid" style={{ marginBottom: 20 }}>
    {Array.from({ length: n }).map((_, i) => (
      <motion.div key={i} className="stat"
        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}>
        <div className="sk" style={{ width: 40, height: 40, borderRadius: 12, marginBottom: 12 }} />
        <SkelLine w={70} h={26} />
        <SkelLine w={100} h={10} style={{ marginTop: 8 }} />
      </motion.div>
    ))}
  </div>
);

export const SkelCards = ({ n = 6 }) => (
  <div className="data-grid">
    {Array.from({ length: n }).map((_, i) => (
      <motion.div key={i} className="file-card"
        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
        <div className="sk" style={{ height: 148, borderRadius: 0 }} />
        <div className="fc-body">
          <SkelLine w="70%" />
          <SkelLine w="45%" h={9} style={{ marginTop: 8 }} />
          <SkelLine w="100%" h={30} style={{ marginTop: 14, borderRadius: 10 }} />
        </div>
      </motion.div>
    ))}
  </div>
);
