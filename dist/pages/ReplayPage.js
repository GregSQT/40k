import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// frontend/src/pages/ReplayPage.tsx
import { useState } from "react";
import ReplayViewer from "@components/ReplayViewer";
import LoadReplayButton from "@components/LoadReplayButton";
export default function ReplayPage() {
    const [eventLog, setEventLog] = useState(null);
    console.log("ReplayPage rendered, eventLog:", eventLog);
    return (_jsxs("div", { children: [_jsx("h2", { style: { color: "#aee6ff" }, children: "AI Game Replay Viewer" }), _jsx(LoadReplayButton, { onLoad: setEventLog }), eventLog && _jsx(ReplayViewer, { eventLog: eventLog })] }));
}
