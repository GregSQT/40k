import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// frontend/src/components/LoadReplayButton.tsx
import { useRef } from "react";
export default function LoadReplayButton({ onLoad }) {
    const fileInputRef = useRef(null);
    function handleFile(e) {
        const file = e.target.files?.[0];
        if (!file)
            return;
        const reader = new FileReader();
        reader.onload = (event) => {
            try {
                console.log("Loaded file content:", event.target?.result?.slice?.(0, 300));
                const log = JSON.parse(event.target?.result);
                onLoad(log);
            }
            catch (err) {
                console.error("Failed to parse file", err, event.target?.result);
                alert("Failed to parse replay file!");
            }
        };
        reader.readAsText(file);
    }
    function handleClick() {
        // This triggers the hidden file input
        fileInputRef.current?.click();
    }
    return (_jsxs("div", { children: [_jsx("input", { ref: fileInputRef, type: "file", accept: ".json", style: { display: "none" }, onChange: handleFile }), _jsx("button", { type: "button", style: { marginBottom: 16 }, onClick: handleClick, children: "Load Replay File" })] }));
}
