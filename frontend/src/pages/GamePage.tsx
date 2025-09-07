// frontend/src/pages/GamePage.tsx
import { BoardWithAPI } from "../components/BoardWithAPI";
import "../App.css";

export default function GamePage() {
  console.log('🚨 GAMEPAGE COMPONENT IS LOADING - NEW VERSION');
  console.log('🚨 About to render BoardWithAPI component');
  
  return (
    <div className="min-h-screen bg-gray-900">
      <div style={{ position: 'absolute', top: '10px', left: '10px', background: 'red', color: 'white', padding: '10px', zIndex: 9999 }}>
        NEW GAMEPAGE LOADED
      </div>
      <BoardWithAPI />
    </div>
  );
}
