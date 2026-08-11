import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@radix-ui/themes/styles.css";

import App from "./App";
import { ToastProvider } from "./components/Toast";
import { DesignSystemProvider } from "./components/ui/DesignSystemProvider";
import "./styles.css";
import { applyTheme, storedTheme } from "./lib/theme";

applyTheme(storedTheme());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DesignSystemProvider>
      <ToastProvider>
        <App />
      </ToastProvider>
    </DesignSystemProvider>
  </StrictMode>,
);
