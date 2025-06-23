import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
// src/routes.tsx
import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import HomePage from "./pages/HomePage";
import GamePage from "./pages/GamePage";
import ReplayPage from "./pages/ReplayPage";
export default function App() {
    return (_jsxs(BrowserRouter, { children: [_jsxs("nav", { style: { margin: 16 }, children: [_jsx(Link, { to: "/", children: "Home" }), " | ", _jsx(Link, { to: "/game", children: "Game" }), " | ", _jsx(Link, { to: "/replay", children: "Replay" })] }), _jsxs(Routes, { children: [_jsx(Route, { path: "/", element: _jsx(HomePage, {}) }), _jsx(Route, { path: "/game", element: _jsx(GamePage, {}) }), _jsx(Route, { path: "/replay", element: _jsx(ReplayPage, {}) })] })] }));
}
