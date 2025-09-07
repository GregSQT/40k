import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import HomePage from "./pages/HomePage";
import GamePage from "./pages/GamePage";
import './App.css'

alert('APP.TSX IS LOADING!');

function App() {
  console.log('🔍 APP.TSX IS LOADING');
  console.log('🔍 Current URL on load:', window.location.href);
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/game" replace />} />
        <Route path="/home" element={<HomePage />} />
        <Route path="/game" element={<GamePage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App
