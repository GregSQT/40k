// src/routes.tsx

import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import HomePage from "./pages/HomePage";
import GamePage from "./pages/GamePage";
import ReplayPage from "./pages/ReplayPage";

export default function App() {
  return (
    <BrowserRouter>
      <nav style={{ margin: 16 }}>
        <Link to="/">Home</Link> | <Link to="/game">Game</Link> | <Link to="/replay">Replay</Link>
      </nav>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/game" element={<GamePage />} />
        <Route path="/replay" element={<ReplayPage />} />
      </Routes>
    </BrowserRouter>
  );
}


