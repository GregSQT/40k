// frontend/src/Routes.tsx

import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import HomePage from "./pages/HomePage";
import GamePage from "./pages/GamePage";
import PlayerVsAIPage from "./pages/PlayerVsAIPage";
import ReplayPage from "./pages/ReplayPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Redirect root path directly to game mode */}
        <Route path="/" element={<Navigate to="/game" replace />} />
        <Route path="/home" element={<HomePage />} />
        <Route path="/game" element={<GamePage />} />
        <Route path="/pve" element={<PlayerVsAIPage />} />
        <Route path="/replay" element={<ReplayPage />} />
      </Routes>
    </BrowserRouter>
  );
}