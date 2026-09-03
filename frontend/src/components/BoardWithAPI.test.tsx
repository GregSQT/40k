// @vitest-environment jsdom
/**
 * Ordre des écrans de garde de BoardWithAPI (terrainListError → loading → plateau).
 *
 * La partie attend la liste des terrains avant de démarrer : si /api/config/terrain-list
 * échoue, apiProps.loading reste true indéfiniment. Tester loading en premier rendait
 * l'écran d'erreur inatteignable. Ce test verrouille l'ordre : l'erreur terrain-list
 * doit s'afficher AVANT le spinner « Starting… », et le cas nominal (liste servie puis
 * plateau rendu) doit dépasser les deux gardes.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { BoardWithAPI } from "./BoardWithAPI";

// BoardPvp importe pixi.js-legacy, incompatible avec jsdom.
vi.mock("./BoardPvp", () => ({ default: () => null }));

// ---------------------------------------------------------------------------
// Données de test
// ---------------------------------------------------------------------------

const TERRAIN_LIST = [
  {
    id: "mc2",
    label: "Terrain 2",
    preview_image: "/icons/Terrain/terrain-mc2.jpg",
    modes: ["pvp", "pvp_test", "pve", "pve_test"],
    default_for: ["pvp", "pvp_test", "pve_test"],
  },
];

const GAME_STATE = {
  phase: "move",
  current_player: 1,
  turn: 1,
  player_types: { "1": "human", "2": "human" },
  move_activation_pool: [],
  shoot_activation_pool: [],
  charge_activation_pool: [],
  fight_eligible_units: [],
  units: [],
  units_cache: {},
  models_cache: {},
  squad_models: {},
  victory_points: { "1": 0, "2": 0 },
  game_over: false,
  winner: null,
  board_cols: 20,
  board_rows: 20,
  board_levels: 1,
  objectives: [],
  units_moved: [],
  units_charged: [],
  units_shot: [],
  units_fled: [],
  units_advanced: [],
  command_points: { "1": 0, "2": 0 },
};

// Doit passer isGameConfig() : game_rules + gameplay + ai_behavior obligatoires.
const GAME_CONFIG = {
  game_rules: {
    max_turns: 5,
    turn_limit_penalty: -1,
    los_debug_show_ratio: false,
    los_debug_show_ratio_rule: "none",
  },
  charge: { charge_max_distance: 12, select_target_before_roll: false },
  gameplay: { phase_order: ["move"], simultaneous_actions: false, auto_end_turn: true },
  ai_behavior: { timeout_ms: 1000, retries: 0, fallback_action: "skip" },
};

// Doit passer isBoardConfig() : cols, rows, hex_radius, margin, inches_to_subhex, wall_hexes, colors.
const BOARD_CONFIG = {
  cols: 44,
  rows: 60,
  hex_radius: 13.9,
  margin: 5,
  inches_to_subhex: 1,
  wall_hexes: [],
  colors: {
    background: "#000",
    cell_even: "#111",
    cell_odd: "#222",
    cell_border: "#333",
    player_1: "#00f",
    player_2: "#f00",
    hp_full: "#0f0",
    hp_damaged: "#ff0",
    highlight: "#fff",
    current_unit: "#fff",
    objective: "#ff0",
  },
};

// ---------------------------------------------------------------------------
// MSW server — handlers par défaut (cas nominal)
// ---------------------------------------------------------------------------

const server = setupServer(
  // Statique Vite : useStaticGameConfig le charge via fetch() brut (pas apiFetch).
  http.get("/config/game_config.json", () => HttpResponse.json(GAME_CONFIG)),
  // Démarrage de partie PvP : player_types["2"] doit être "human" pour valider le mode.
  http.post("/api/game/start", () =>
    HttpResponse.json({ success: true, game_state: GAME_STATE })
  ),
  // useGameConfig l'appelle après que la liste des terrains est connue ; sans handler,
  // bypass envoie la requête sur le réseau réel et laisse boardConfig à null.
  // Format attendu : { success: true, config: {...} } (voir useGameConfig.ts:355).
  http.get("/api/config/board", () => HttpResponse.json({ success: true, config: BOARD_CONFIG }))
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
  localStorage.clear();
});
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Auth session — requis par apiFetch (court-circuit 401 si absent)
// ---------------------------------------------------------------------------

const FAKE_SESSION = JSON.stringify({
  user: { id: 1, email: "test@example.com" },
  permissions: {
    game_modes: ["pvp"],
    options: { show_advance_warning: false, auto_weapon_selection: false },
  },
});

beforeEach(() => {
  localStorage.setItem("w40k_auth_session_v2", FAKE_SESSION);
});

function renderBoard() {
  return render(
    <MemoryRouter>
      <BoardWithAPI />
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("BoardWithAPI — écrans de garde", () => {
  it("affiche l'erreur terrain-list et non le spinner quand /api/config/terrain-list échoue", async () => {
    server.use(
      http.get("/api/config/terrain-list", () => new HttpResponse(null, { status: 500 }))
    );
    renderBoard();

    await waitFor(() =>
      expect(screen.getByText(/Impossible de charger la liste des terrains/)).toBeTruthy()
    );
    // apiProps.loading reste true → sans l'ordre correct (terrainListError avant loading),
    // ce message serait masqué par le spinner.
    expect(screen.queryByText("Starting W40K Engine Game...")).toBeNull();
  });

  it("dépasse le spinner et rend le plateau quand la liste des terrains est servie", async () => {
    server.use(
      http.get("/api/config/terrain-list", () =>
        HttpResponse.json({ terrains: TERRAIN_LIST })
      )
    );
    renderBoard();

    // Avant que /api/game/start réponde : loading = true, spinner visible.
    expect(screen.getByText("Starting W40K Engine Game...")).toBeTruthy();

    // Après game/start : loading = false, spinner disparu.
    await waitFor(
      () => expect(screen.queryByText("Starting W40K Engine Game...")).toBeNull(),
      { timeout: 5000 }
    );

    // Ni l'écran d'erreur terrain.
    expect(screen.queryByText(/Impossible de charger la liste des terrains/)).toBeNull();

    // La nav de SharedLayout prouve que les deux gardes sont franchies.
    expect(screen.getByRole("button", { name: "PvP" })).toBeTruthy();
  });
});
