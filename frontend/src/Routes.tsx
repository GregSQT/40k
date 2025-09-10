// frontend/src/Routes.tsx

import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import HomePage from "./pages/HomePage";
//import PlayerVsAIPage from "./pages/PlayerVsAIPage";
//import ReplayPage from "./pages/ReplayPage";
import { BoardWithAPI } from "./components/BoardWithAPI";

export default function App() {
  console.log('🔍 ROUTES.TSX IS LOADING');
  console.log('🔍 Current URL on load:', window.location.href);
  
  React.useEffect(() => {
    console.log('🔍 Routes.tsx current path:', window.location.pathname);
    console.log('🔍 Should render BoardWithAPI for /game route');
  }, []);
  
  return (
    <BrowserRouter>
      <Routes>
        {/* Redirect root path directly to game mode */}
        <Route path="/" element={<Navigate to="/game" replace />} />
        <Route path="/home" element={<HomePage />} />
        <Route path="/game" element={<BoardWithAPI />} />
        {/* <Route path="/pve" element={<PlayerVsAIPage />} /> */}
        {/* <Route path="/replay" element={<ReplayPage />} /> */}
      </Routes>
    </BrowserRouter>
  );
}