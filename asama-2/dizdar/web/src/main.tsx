import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
// Roboto / Roboto Mono (Astro UXDS type) are bundled, so the offline demo renders the same fonts.
import "@fontsource/roboto/400.css";
import "@fontsource/roboto/500.css";
import "@fontsource/roboto/700.css";
import "@fontsource/roboto-mono/400.css";
import "@fontsource/roboto-mono/600.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
