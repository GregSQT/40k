// frontend/src/components/LoadReplayButton.tsx

import React, { useRef } from "react";

export default function LoadReplayButton({ onLoad }: { onLoad: (log: any) => void }) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        console.log("Loaded file content:", event.target?.result?.slice?.(0, 300));
        const log = JSON.parse(event.target?.result as string);
        onLoad(log);
      } catch (err) {
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

  return (
    <div>
      <input
        ref={fileInputRef}
        type="file"
        accept=".json"
        style={{ display: "none" }}
        onChange={handleFile}
      />
      <button type="button" style={{ marginBottom: 16 }} onClick={handleClick}>
        Load Replay File
      </button>
    </div>
  );
}
