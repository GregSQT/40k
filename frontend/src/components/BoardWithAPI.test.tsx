// @vitest-environment jsdom
/**
 * T_BoardWithAPI_Guards — ordre des écrans de garde de BoardWithAPI.
 *
 * terrainListError est testé AVANT apiProps.loading : un fetch /api/config/terrain-list
 * en échec laisse apiProps.loading à true pour toujours (le démarrage de partie attend
 * la liste). Sans ce guard en premier, l'erreur était inatteignable — l'écran restait
 * sur "Starting W40K Engine Game..." sans jamais expliquer pourquoi.
 *
 * Cas 1 — terrain-list 500 : "Impossible de charger..." affiché, pas l'écran de chargement.
 * Cas 2 — nominal : liste servie, partie démarrée, plateau rendu (BoardPvp mock visible).
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import React from "react";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { BoardWithAPI } from "./BoardWithAPI";

vi.mock("./BoardPvp", () => ({
  default: () => <div data-testid="board-pvp" />,
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const TEST_TERRAIN_LIST = [
  {
    id: "mc1",
    label: "Terrain 1",
    preview_image: "/icons/Terrain/terrain-mc1.jpg",
    modes: ["pvp", "pvp_test", "pve", "pve_test"],
    default_for: ["pve"],
  },
];

const FAKE_SESSION = JSON.stringify({
  user: { id: 1, login: "test_user", profile: "player" },
  permissions: {
    game_modes: ["pvp"],
    options: { show_advance_warning: false, auto_weapon_selection: false },
  },
  default_redirect_mode: "pvp",
});

const BOARD_CONFIG = {
  cols: 20,
  rows: 20,
  hex_radius: 10,
  margin: 1,
  inches_to_subhex: 5,
  wall_hexes: [] as [number, number][],
  colors: {
    background: "#000",
    cell_even: "#111",
    cell_odd: "#222",
    cell_border: "#333",
    player_1: "#00f",
    player_2: "#f00",
    hp_full: "#0f0",
    hp_damaged: "#f80",
    highlight: "#ff0",
    current_unit: "#fff",
    objective: "#f90",
  },
};

function makeGameState() {
  return {
    phase: "move",
    current_player: 1,
    turn: 1,
    episode_steps: 0,
    player_types: { "1": "human", "2": "human" },
    player_names: { "1": "Player 1", "2": "Player 2" },
    move_activation_pool: [],
    shoot_activation_pool: [],
    charge_activation_pool: [],
    fight_eligible_units: [],
    units: [],
    units_cache: {},
    models_cache: {},
    squad_models: {},
    victory_points: { "1": 0, "2": 0 },
    command_points: { "1": 0, "2": 0 },
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
    deployment_type: "fixed",
    active_movement_unit: null,
    fight_step: null,
    fight_selector: null,
    active_fight_unit: null,
  };
}

// ---------------------------------------------------------------------------
// msw server
// ---------------------------------------------------------------------------

const server = setupServer(
  http.get("/config/game_config.json", () =>
    HttpResponse.json({ game_rules: { max_turns: 5 } })
  ),
  http.get("/api/config/terrain-list", () =>
    HttpResponse.json({ terrains: TEST_TERRAIN_LIST })
  ),
  http.get("/api/config/board", () =>
    HttpResponse.json({ success: true, config: BOARD_CONFIG })
  ),
  http.post("/api/game/start", () =>
    HttpResponse.json({ success: true, game_state: makeGameState() })
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "warn" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
  localStorage.clear();
});
afterAll(() => server.close());

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
  it("terrain-list 500 → message d'erreur affiché, pas l'écran de chargement", async () => {
    server.use(
      http.get("/api/config/terrain-list", () => new HttpResponse(null, { status: 500 }))
    );

    renderBoard();

    await waitFor(
      () => {
        expect(
          screen.getByText(/Impossible de charger la liste des terrains/)
        ).toBeTruthy();
      },
      { timeout: 5000 }
    );

    expect(screen.queryByText(/Starting W40K Engine Game/)).toBeNull();
  });

  it("liste servie → plateau rendu, aucun écran de garde visible", async () => {
    renderBoard();

    await waitFor(
      () => {
        expect(screen.getByTestId("board-pvp")).toBeTruthy();
      },
      { timeout: 5000 }
    );

    expect(screen.queryByText(/Starting W40K Engine Game/)).toBeNull();
    expect(screen.queryByText(/Impossible de charger/)).toBeNull();
  });
});
