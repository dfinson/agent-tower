import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";
import { App } from "./App";
import { useTowerStore } from "./store";
import "./index.css";

// Expose the store for e2e test assertions.
(window as unknown as Record<string, unknown>)["__tower__"] = { store: useTowerStore };

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
      <Toaster position="top-right" theme="dark" richColors />
    </BrowserRouter>
  </StrictMode>,
);
