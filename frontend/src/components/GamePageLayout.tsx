//frontend/src/components/GamePageLayout.tsx

import { BoardWithAPI } from "../components/BoardWithAPI";
import "../App.css";

export default function GamePageLayout() {
  // Remove useEngineAPI - BoardWithAPI will handle all API communication
  return <BoardWithAPI />;
}