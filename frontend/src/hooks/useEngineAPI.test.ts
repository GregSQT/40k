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
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import React from "react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthSession } from "../auth/authStorage";
import type { Unit, Weapon } from "../types/game";
import { setTerrainList, type TerrainEntry } from "../utils/terrainSelection";
import { TEST_TERRAIN_LIST } from "./__fixtures__/terrainFixtures";
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

function makeUnit(id: number, player: 1 | 2, overrides: Partial<Unit> = {}): Unit {
  return {
    id,
    player,
    col: 0,
    row: 0,
    HP_CUR: 5,
    HP_MAX: 5,
    MOVE: 60,
    RNG_WEAPONS: [],
    CC_WEAPONS: [],
    ICON: "",
    ICON_SCALE: 1,
    ILLUSTRATION_RATIO: 1,
    SHOOT_LEFT: 0,
    ATTACK_LEFT: 0,
    UNIT_RULES: [],
    UNIT_KEYWORDS: [],
    ...overrides,
  } as Unit;
}

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
  user: { id: 1, login: "test_user", profile: "player" },
  permissions: {
    game_modes: ["pvp"],
    options: { show_advance_warning: false, auto_weapon_selection: false },
  },
  default_redirect_mode: "pvp",
} satisfies AuthSession);

beforeEach(() => {
  localStorage.setItem("w40k_auth_session_v2", FAKE_SESSION);
  setTerrainList(TEST_TERRAIN_LIST);
});

// ---------------------------------------------------------------------------
// T8 — eligibleUnitIds = pool de la phase courante
// ---------------------------------------------------------------------------

describe("useEngineAPI — eligibleUnitIds", () => {
  it("phase move → eligibleUnitIds = move_activation_pool (en nombres)", async () => {
    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));

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

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
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

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
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

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
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

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
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
      React.createElement(ErrorBoundary, {
        onError: (msg) => {
          caughtError = msg;
        },
        children,
      });

    renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }), { wrapper });
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
      React.createElement(ErrorBoundary, {
        onError: (msg) => {
          caughtError = msg;
        },
        children,
      });

    renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }), { wrapper });
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
    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    // Synchronous: before any await, loading is true
    expect(result.current.loading).toBe(true);
    expect(result.current.eligibleUnitIds).toEqual([]);
    expect(result.current.phase).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// T8 — movePreview : active_movement_unit déjà activée → pas d'appel activate_unit
// ---------------------------------------------------------------------------

describe("useEngineAPI — movePreview", () => {
  it("phase move, unité déjà active → movePreview positionné et mode=movePreview", async () => {
    let actionCalls = 0;
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({
          success: true,
          game_state: makeGameState({
            active_movement_unit: "10",
            move_activation_pool: ["10"],
          }),
        })
      ),
      http.post("/api/game/action", () => {
        actionCalls++;
        return HttpResponse.json({ success: true, game_state: makeGameState() });
      })
    );

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    await act(async () => {
      await result.current.onStartMovePreview(10, 5, 8);
    });

    expect(result.current.movePreview?.unitId).toBe(10);
    expect(result.current.movePreview?.destCol).toBe(5);
    expect(result.current.movePreview?.destRow).toBe(8);
    expect(result.current.mode).toBe("movePreview");
    expect(actionCalls).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// T8 — targetPreview : onStartTargetPreview déclenche left_click et ne plante pas
//
// Note de conception : setTargetPreview(preview) est appelé en fin de handleStartTargetPreview,
// mais le useEffect([gameState?.phase, targetPreview?.blinkTimer, ...]) du hook
// remet immédiatement targetPreview à null dès que le blinkTimer change — act() flush les effets
// de façon synchrone en jsdom, alors qu'en production le navigateur laisse un rendu visible.
// On teste donc l'invariant testable : l'appel API left_click est émis sans erreur.
// ---------------------------------------------------------------------------

describe("useEngineAPI — targetPreview", () => {
  it("shoot phase → onStartTargetPreview émet left_click sans erreur", async () => {
    const BOLT_RIFLE: Weapon = {
      display_name: "Bolt Rifle",
      NB: 2,
      ATK: 3,
      STR: 4,
      AP: 1,
      DMG: 1,
      RNG: 240,
    };
    const shooter = makeUnit(1, 1, {
      RNG_WEAPONS: [BOLT_RIFLE],
      T: 4,
      ARMOR_SAVE: 5,
    });
    const target = makeUnit(2, 2, { T: 4, ARMOR_SAVE: 4 });
    const shootGameState = makeGameState({
      phase: "shoot",
      units: [shooter, target],
      units_cache: { "1": shooter as unknown as Record<string, unknown> },
      shoot_activation_pool: ["1"],
      move_activation_pool: [],
    });

    let capturedBody: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: shootGameState })
      ),
      http.post("/api/game/action", async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ success: true, game_state: shootGameState });
      })
    );

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    // Attendre que le hook soit ENTIÈREMENT prêt : loading=false ET maxTurns chargé.
    // maxTurnsFromConfig === null → chemin de chargement → onStartTargetPreview: () => {}
    await waitFor(
      () => {
        expect(result.current.loading).toBe(false);
        expect(result.current.maxTurns).not.toBeNull();
      },
      { timeout: 5000 }
    );

    await act(async () => {
      await result.current.onStartTargetPreview(1, 2);
    });

    // L'appel API left_click doit avoir été émis
    expect(capturedBody).not.toBeNull();
    const body = capturedBody!;
    expect(body.action).toBe("left_click");
    expect(body.unitId).toBe("1");
    expect(body.targetId).toBe("2");
    // Aucune erreur dans le hook
    expect(result.current.error).toBeNull();
  });

  it("onCancelTargetPreview : exposé dans le hook et ne plante pas si targetPreview est null", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: makeGameState() })
      )
    );
    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    await waitFor(
      () => {
        expect(result.current.loading).toBe(false);
        expect(result.current.maxTurns).not.toBeNull();
      },
      { timeout: 5000 }
    );
    expect(typeof result.current.onCancelTargetPreview).toBe("function");
    // targetPreview null au repos : l'appel doit être un no-op sans erreur.
    await act(async () => {
      result.current.onCancelTargetPreview();
    });
    expect(result.current.targetPreview).toBeNull();
    expect(result.current.error).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Le terrain choisi doit partir avec le démarrage de partie — en PvP aussi
// ---------------------------------------------------------------------------

describe("useEngineAPI — terrain_ref envoyé au démarrage", () => {
  const captureStartBody = () => {
    const captured: { value: Record<string, unknown> | null } = { value: null };
    server.use(
      http.post("/api/game/start", async ({ request }) => {
        captured.value = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ success: true, game_state: makeGameState() });
      })
    );
    return captured;
  };

  it("PvP avec ?terrain=pfm2 → terrain_ref transmis (sinon le serveur reste sur mc2)", async () => {
    const captured = captureStartBody();
    window.history.replaceState({}, "", "/game?terrain=pfm2");

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    expect(captured.value).not.toBeNull();
    expect(captured.value?.mode_code).toBe("pvp");
    expect(captured.value?.terrain_ref).toBe("pfm2");
  });

  it("PvP sans paramètre terrain → mc2, le terrain du scénario non suffixé", async () => {
    const captured = captureStartBody();
    window.history.replaceState({}, "", "/game");

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    expect(captured.value?.terrain_ref).toBe("mc2");
  });

  it("liste pas encore chargée → aucune partie démarrée, puis démarrage avec le terrain choisi", async () => {
    const captured = captureStartBody();
    window.history.replaceState({}, "", "/game?terrain=mc1");
    // Montage d'AVANT la réponse de /api/config/terrain-list : c'est l'état réel au mount, et
    // c'est là que `terrain_ref` se perdait. Démarrer ici enverrait une partie sans terrain choisi.
    const { result, rerender } = renderHook(
      ({ list }: { list?: TerrainEntry[] }) => useEngineAPI({ terrainList: list }),
      { initialProps: { list: undefined as TerrainEntry[] | undefined } }
    );

    // Rien ne part tant que la liste manque — et le hook reste en chargement.
    await waitFor(() => expect(result.current.loading).toBe(true), { timeout: 5000 });
    expect(captured.value).toBeNull();

    // La liste arrive : le démarrage se déclenche, avec le terrain demandé.
    rerender({ list: TEST_TERRAIN_LIST });
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });
    expect(captured.value?.terrain_ref).toBe("mc1");
  });
});
