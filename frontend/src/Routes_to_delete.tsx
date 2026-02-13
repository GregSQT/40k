// frontend/src/Routes.tsx

import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { BoardWithAPI } from "./components/BoardWithAPI";
import HomePage from "./pages/HomePage";
//import PlayerVsAIPage from "./pages/PlayerVsAIPage";
import ReplayPage from "./pages/ReplayPage";

export default function App() {
  React.useEffect(() => {}, []);

  return (
    <BrowserRouter>
      <Routes>
        {/* Redirect root path directly to game mode */}
        <Route path="/" element={<Navigate to="/game" replace />} />
        <Route path="/home" element={<HomePage />} />
        <Route path="/game" element={<BoardWithAPI />} />
        {/* <Route path="/pve" element={<PlayerVsAIPage />} /> */}
        <Route path="/replay" element={<ReplayPage />} />
      </Routes>
    </BrowserRouter>
  );
}
