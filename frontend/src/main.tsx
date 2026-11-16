import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { HowItWorks } from "./HowItWorks";
import { SharedChatPage } from "./SharedChatPage";
import "./styles.css";

const path = window.location.pathname;
const shared = path.match(/^\/c\/([\w-]+)\/?$/);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {shared ? <SharedChatPage slug={shared[1]} /> : path.startsWith("/how-it-works") ? <HowItWorks /> : <App />}
  </StrictMode>,
);
