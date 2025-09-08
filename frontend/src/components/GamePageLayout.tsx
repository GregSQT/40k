import { BoardWithAPI } from "../components/BoardWithAPI";
import { SharedLayout } from "../components/SharedLayout";
import { TurnPhaseTracker } from "../components/TurnPhaseTracker";
// import { UnitStatusTable } from "../components/UnitStatusTable";
// import { GameLog } from "../components/GameLog";
// import { ErrorBoundary } from "../components/ErrorBoundary";
import { useEngineAPI } from "../hooks/useEngineAPI";
import "../App.css";

export default function GamePageLayout() {
  const apiProps = useEngineAPI();
  
  if (apiProps.loading || apiProps.error) {
    return <BoardWithAPI />;
  }

  // Stub game log data (compliant - no hooks)
  // const gameLogEvents: Array<any> = [];
  // const getElapsedTime = () => "0s";

  const rightColumnContent = (
    <>
      <TurnPhaseTracker 
        currentTurn={apiProps.gameState?.currentTurn || 1} 
        currentPhase={apiProps.phase}
        phases={["move", "shoot", "charge", "combat"]}
        maxTurns={apiProps.maxTurns || 8}
        className="turn-phase-tracker-right"
      />
      
      <div style={{ padding: '16px', color: 'white', background: '#1f2937' }}>
        <h3>Game Status</h3>
        <p>Current Player: {apiProps.currentPlayer}</p>
        <p>Phase: {apiProps.phase}</p>
        <p>Episode Steps: {apiProps.gameState?.episode_steps || 0}</p>
        <p>Max Turns: {apiProps.maxTurns || 8}</p>
      </div>
    </>
  );

  return (
    <SharedLayout rightColumnContent={rightColumnContent}>
      <BoardWithAPI />
    </SharedLayout>
  );
}