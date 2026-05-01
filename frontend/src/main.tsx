import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./Routes.tsx";
import { logClientDebugConsoleNotifyIfEnabled } from "./utils/actionLogClient";

logClientDebugConsoleNotifyIfEnabled();

createRoot(document.getElementById("root")!).render(<App />);
