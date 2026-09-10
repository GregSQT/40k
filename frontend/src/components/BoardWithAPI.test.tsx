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
 *
 * T_BoardWithAPI_ReactiveMove — le panneau de mouvement réactif n'est POSÉ QU'À UN SIÈGE HUMAIN.
 * C'est la seule décision posée pendant le tour de l'adversaire, et en PvE le moteur tranche
 * celle du bot sur-le-champ (`_resolve_reactive_move_decision_for_ai_seats`) : sans le filtre de
 * `reactiveMoveDecision`, l'humain se verrait poser la question du bot le temps d'un aller-retour
 * d'état et y répondrait à sa place. Les deux cas sont testés ensemble — le cas humain est ce qui
 * empêche un panneau muet pour une autre raison de rendre le cas IA vert pour rien.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthSession } from "../auth/authStorage";
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
} satisfies AuthSession);

/** Session PvE : `useEngineAPI` REFUSE un `player_types["2"] === "ai"` sous un mode_code PvP
 *  (« Game mode mismatch »), et c'est le bon comportement — un siège IA n'existe qu'en PvE. Le
 *  cas IA du panneau réactif se joue donc en PvE, sinon le composant lève avant d'avoir rendu
 *  quoi que ce soit. */
const FAKE_SESSION_PVE = JSON.stringify({
  user: { id: 1, login: "test_user", profile: "player" },
  permissions: {
    game_modes: ["pvp", "pve"],
    options: { show_advance_warning: false, auto_weapon_selection: false },
  },
  default_redirect_mode: "pve",
} satisfies AuthSession);

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

function makeGameState(over: Record<string, unknown> = {}) {
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
    ...over,
  };
}

/** Forme rendue par `_arm_reactive_move_decision` (engine/phase_handlers/shared_utils.py) :
 *  deux intentions scorées puis le candidat qui DÉCLINE — refuser est un choix de la règle. */
const REACTIVE_MOVE_DECISION = {
  type: "reactive_move",
  player: 2,
  unit_id: "4",
  options: [
    { label: "Pression" },
    { label: "Distance" },
    { label: "Ne pas reagir (rester sur place)" },
  ],
};

// ---------------------------------------------------------------------------
// msw server
// ---------------------------------------------------------------------------

const server = setupServer(
  http.get("/config/game_config.json", () => HttpResponse.json({ game_rules: { max_turns: 5 } })),
  http.get("/api/config/terrain-list", () => HttpResponse.json({ terrains: TEST_TERRAIN_LIST })),
  http.get("/api/config/board", () => HttpResponse.json({ success: true, config: BOARD_CONFIG })),
  http.post("/api/game/start", () =>
    HttpResponse.json({ success: true, game_state: makeGameState() })
  )
);

beforeAll(() => server.listen({ onUnhandledRequest: "warn" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
  localStorage.clear();
  // `useEngineAPI` lit le mode dans `window.location.search`, hors du MemoryRouter : sans cette
  // remise à zéro, le mode PvE d'un test fuiterait dans les suivants.
  window.history.replaceState({}, "", "/");
});
afterAll(() => server.close());

beforeEach(() => {
  localStorage.setItem("w40k_auth_session_v2", FAKE_SESSION);
});

function renderBoard(initialEntry = "/") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <BoardWithAPI />
    </MemoryRouter>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("BoardWithAPI — écrans de garde", () => {
  it("terrain-list 500 → message d'erreur affiché, pas l'écran de chargement", async () => {
    server.use(http.get("/api/config/terrain-list", () => new HttpResponse(null, { status: 500 })));

    renderBoard();

    await waitFor(
      () => {
        expect(screen.getByText(/Impossible de charger la liste des terrains/)).toBeTruthy();
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

describe("BoardWithAPI — panneau de mouvement réactif", () => {
  /** Démarre une partie dont l'état porte la décision réactive du joueur 2.
   *
   *  Le mode est posé DEUX FOIS parce que deux lecteurs le résolvent séparément : le composant
   *  par `useLocation` (MemoryRouter), `useEngineAPI` par `window.location.search`. */
  function renderWithReactiveDecision(mode: "pvp" | "pve", seat2: "human" | "ai") {
    if (mode === "pve") {
      localStorage.setItem("w40k_auth_session_v2", FAKE_SESSION_PVE);
      window.history.replaceState({}, "", "/game?mode=pve");
    }
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({
          success: true,
          game_state: makeGameState({
            player_types: { "1": "human", "2": seat2 },
            pending_agent_decision: REACTIVE_MOVE_DECISION,
          }),
        })
      )
    );
    renderBoard(mode === "pve" ? "/game?mode=pve" : "/");
  }

  it("siège IA → le panneau n'est PAS rendu (le moteur a déjà tranché pour le bot)", async () => {
    renderWithReactiveDecision("pve", "ai");

    // On attend le plateau AVANT de conclure à l'absence : sans ce point d'ancrage, l'assertion
    // serait vraie simplement parce que rien n'est encore monté.
    await waitFor(
      () => {
        expect(screen.getByTestId("board-pvp")).toBeTruthy();
      },
      { timeout: 5000 }
    );

    expect(screen.queryByText(/Reactive move — unit 4/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Pression" })).toBeNull();
  });

  it("siège humain → le panneau est rendu, un bouton par candidat du moteur", async () => {
    renderWithReactiveDecision("pvp", "human");

    await waitFor(
      () => {
        expect(screen.getByText(/Reactive move — unit 4 — player 2/)).toBeTruthy();
      },
      { timeout: 5000 }
    );

    for (const option of REACTIVE_MOVE_DECISION.options) {
      expect(screen.getByRole("button", { name: option.label })).toBeTruthy();
    }
  });
});
