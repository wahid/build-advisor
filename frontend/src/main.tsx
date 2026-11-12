import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { HowItWorks } from "./HowItWorks";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {window.location.pathname.startsWith("/how-it-works") ? <HowItWorks /> : <App />}
  </StrictMode>,
);
