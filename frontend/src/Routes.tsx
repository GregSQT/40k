// frontend/src/Routes.tsx

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { BoardWithAPI } from "./components/BoardWithAPI";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Route AUTORISÉE */}
        <Route path="/game" element={<BoardWithAPI />} />

        {/* Redirection racine */}
        <Route path="/" element={<Navigate to="/game" replace />} />

        {/* BLOCAGE TOTAL : tout le reste */}
        <Route path="*" element={<Navigate to="/game" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
