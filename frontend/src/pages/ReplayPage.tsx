// frontend/src/pages/ReplayPage.tsx

import React, { useState } from "react";
import ReplayViewer from "@components/ReplayViewer";
import LoadReplayButton from "@components/LoadReplayButton";

export default function ReplayPage() {
  const [eventLog, setEventLog] = useState(null);
  console.log("ReplayPage rendered, eventLog:", eventLog);

  return (
    <div>
      <h2 style={{ color: "#aee6ff" }}>AI Game Replay Viewer</h2>
      <LoadReplayButton onLoad={setEventLog} />
      {eventLog && <ReplayViewer eventLog={eventLog} />}
    </div>
  );
}
