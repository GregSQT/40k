"use strict";
// src/routes.tsx
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.default = App;
const react_router_dom_1 = require("react-router-dom");
const HomePage_1 = __importDefault(require("@pages/HomePage"));
const GamePage_1 = __importDefault(require("@pages/GamePage"));
const ReplayPage_1 = __importDefault(require("@pages/ReplayPage"));
function App() {
    return (<react_router_dom_1.BrowserRouter>
      <nav>
        <react_router_dom_1.Link to="/">Home</react_router_dom_1.Link> | <react_router_dom_1.Link to="/game">Game</react_router_dom_1.Link> | <react_router_dom_1.Link to="/replay">Replay</react_router_dom_1.Link>
      </nav>
      <react_router_dom_1.Routes>
        <react_router_dom_1.Route path="/" element={<HomePage_1.default />}/>
        <react_router_dom_1.Route path="/game" element={<GamePage_1.default />}/>
        <react_router_dom_1.Route path="/replay" element={<ReplayPage_1.default />}/>
      </react_router_dom_1.Routes>
    </react_router_dom_1.BrowserRouter>);
}
