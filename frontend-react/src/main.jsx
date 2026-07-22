import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { ToastProvider } from "./components/Toast.jsx";
import { ConfirmProvider } from "./components/Confirm.jsx";
import "./styles/theme.css";

createRoot(document.getElementById("root")).render(
  <ToastProvider>
    <ConfirmProvider>
      <App />
    </ConfirmProvider>
  </ToastProvider>
);
