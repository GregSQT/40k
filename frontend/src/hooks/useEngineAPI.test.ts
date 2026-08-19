// @vitest-environment jsdom
/**
 * T8 — useEngineAPI : mapping donnée backend → état front.
 *
 * msw v2 mocke les endpoints réseau ; on vérifie :
 *   - eligibleUnitIds == le pool de la phase courante (move/shoot/charge/fight)
 *   - gestion d'erreur : success:false → setError, pas de mutation d'état de jeu
 *
 * Prérequis d'auth : `apiFetch` lit localStorage["w40k_auth_session_v2"] ; on le peuple
 * avant chaque test pour éviter le court-circuit 401.
 */
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import React from "react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { useEngineAPI } from "./useEngineAPI";

// ---------------------------------------------------------------------------
// ErrorBoundary pour tester les hooks qui lancent une exception sur erreur
// ---------------------------------------------------------------------------

interface EBState {
  errorMessage: string | null;
}
class ErrorBoundary extends React.Component<
  { children: React.ReactNode; onError: (msg: string) => void },
  EBState
> {
  constructor(props: ErrorBoundary["props"]) {
    super(props);
    this.state = { errorMessage: null };
  }
  static getDerivedStateFromError(error: Error): EBState {
    return { errorMessage: error.message };
  }
  componentDidCatch(error: Error) {
    this.props.onError(error.message);
  }
  render() {
    if (this.state.errorMessage) return null;
    return this.props.children;
  }
}

// ---------------------------------------------------------------------------
// Minimal game state factory
// ---------------------------------------------------------------------------

function makeGameState(overrides: Record<string, unknown> = {}) {
  return {
    phase: "move",
    current_player: 1,
    turn: 1,
    player_types: { "1": "human", "2": "human" },
    move_activation_pool: ["10", "20", "30"],
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
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// msw server
// ---------------------------------------------------------------------------

const server = setupServer(
  // Vite static asset: max_turns
  http.get("/config/game_config.json", () => HttpResponse.json({ game_rules: { max_turns: 5 } })),

  // Démarrage PvP par défaut : phase move, pool [10, 20, 30]
  http.post("/api/game/start", () =>
    HttpResponse.json({ success: true, game_state: makeGameState() })
  )
);

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
  localStorage.clear();
});
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Setup auth session (requis par apiFetch)
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

// ---------------------------------------------------------------------------
// T8 — eligibleUnitIds = pool de la phase courante
// ---------------------------------------------------------------------------

describe("useEngineAPI — eligibleUnitIds", () => {
  it("phase move → eligibleUnitIds = move_activation_pool (en nombres)", async () => {
    const { result } = renderHook(() => useEngineAPI());

    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    expect(result.current.error).toBeNull();
    expect(result.current.eligibleUnitIds).toEqual([10, 20, 30]);
    expect(result.current.phase).toBe("move");
  });

  it("phase shoot → eligibleUnitIds = shoot_activation_pool", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({
          success: true,
          game_state: makeGameState({
            phase: "shoot",
            shoot_activation_pool: ["5", "6"],
            move_activation_pool: [],
          }),
        })
      )
    );

    const { result } = renderHook(() => useEngineAPI());
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    expect(result.current.eligibleUnitIds).toEqual([5, 6]);
    expect(result.current.phase).toBe("shoot");
  });

  it("phase charge → eligibleUnitIds = charge_activation_pool", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({
          success: true,
          game_state: makeGameState({
            phase: "charge",
            charge_activation_pool: ["7", "8", "9"],
            move_activation_pool: [],
          }),
        })
      )
    );

    const { result } = renderHook(() => useEngineAPI());
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    expect(result.current.eligibleUnitIds).toEqual([7, 8, 9]);
    expect(result.current.phase).toBe("charge");
  });

  it("phase fight → eligibleUnitIds = fight_eligible_units", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({
          success: true,
          game_state: makeGameState({
            phase: "fight",
            fight_eligible_units: ["11", "12"],
            move_activation_pool: [],
          }),
        })
      )
    );

    const { result } = renderHook(() => useEngineAPI());
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    expect(result.current.eligibleUnitIds).toEqual([11, 12]);
    expect(result.current.phase).toBe("fight");
  });

  it("pool vide → eligibleUnitIds = []", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({
          success: true,
          game_state: makeGameState({ move_activation_pool: [] }),
        })
      )
    );

    const { result } = renderHook(() => useEngineAPI());
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    expect(result.current.eligibleUnitIds).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// T8 — gestion d'erreur : le hook lance un throw quand l'API échoue
//
// useEngineAPI lève `throw new Error("API ERROR: ...")` quand error est posé.
// On capture ce throw via un ErrorBoundary dans le wrapper renderHook.
// ---------------------------------------------------------------------------

describe("useEngineAPI — gestion d'erreur", () => {
  it("success:false → hook lance une erreur contenant le message backend", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: false, error: "scénario introuvable" })
      )
    );

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    let caughtError: string | null = null;
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(
        ErrorBoundary,
        {
          onError: (msg) => {
            caughtError = msg;
          },
        },
        children
      );

    renderHook(() => useEngineAPI(), { wrapper });
    await waitFor(() => expect(caughtError).not.toBeNull(), { timeout: 5000 });

    expect(caughtError).toContain("scénario introuvable");
    consoleSpy.mockRestore();
  });

  it("HTTP 500 → hook lance une erreur", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ error: "server crash" }, { status: 500 })
      )
    );

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    let caughtError: string | null = null;
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      React.createElement(
        ErrorBoundary,
        {
          onError: (msg) => {
            caughtError = msg;
          },
        },
        children
      );

    renderHook(() => useEngineAPI(), { wrapper });
    await waitFor(() => expect(caughtError).not.toBeNull(), { timeout: 5000 });

    expect(caughtError).toBeTruthy();
    consoleSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// T8 — état initial (pendant le chargement)
// ---------------------------------------------------------------------------

describe("useEngineAPI — état de chargement", () => {
  it("loading=true au premier render, eligibleUnitIds = [] pendant le chargement", () => {
    const { result } = renderHook(() => useEngineAPI());
    // Synchronous: before any await, loading is true
    expect(result.current.loading).toBe(true);
    expect(result.current.eligibleUnitIds).toEqual([]);
    expect(result.current.phase).toBeNull();
  });
});
