import { Link } from "react-router-dom";

export default function HomePage() {
  return (
    <div className="min-h-screen bg-gray-900 text-white" style={{ position: "relative" }}>
      {/* Navigation menu moved to top-right */}
      <div
        style={{ position: "absolute", top: "16px", right: "16px", display: "flex", gap: "16px" }}
      >
        <Link
          to="/game"
          className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-500 inline-block"
        >
          PvP Game
        </Link>
        <Link
          to="/game?mode=pve"
          className="px-6 py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 inline-block"
        >
          PvE Game
        </Link>
        <Link
          to="/game?mode=test"
          className="px-6 py-3 bg-amber-600 text-white rounded-lg hover:bg-amber-500 inline-block"
        >
          Test Game
        </Link>
        <Link
          to="/game?mode=debug"
          className="px-6 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-500 inline-block"
        >
          Debug Game
        </Link>
        <Link
          to="/replay"
          className="px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-500 inline-block"
        >
          Replay
        </Link>
      </div>

      {/* Centered content */}
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <h1 className="text-4xl font-bold mb-6">Warhammer 40K Tactics</h1>
          <p className="text-xl mb-8 text-gray-300">Tactical combat game with AI opponents</p>
        </div>
      </div>
    </div>
  );
}
