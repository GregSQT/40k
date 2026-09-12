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
import { readManualAllocationPrompt, useEngineAPI } from "./useEngineAPI";

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

// ---------------------------------------------------------------------------
// changeRoster — le REFUS du moteur doit remonter à l'appelant
//
// Un refus revient en HTTP 200 avec `success: false` et la raison dans `result.error` :
// `executeAction` ne lève que sur un statut HTTP, donc un appelant qui ignore l'enveloppe
// avale le refus. Les deux appelants de `changeRoster` (sélecteur de roster, auto-application
// des rosters enregistrés) n'affichent leur message que dans un `catch`.
// ---------------------------------------------------------------------------

describe("useEngineAPI — changeRoster", () => {
  /** Partie en phase de déploiement ACTIF : le seul état où `change_roster` est acceptable. */
  const deploiementActif = () =>
    makeGameState({
      phase: "deployment",
      deployment_type: "active",
      move_activation_pool: [],
      deployment_state: {
        current_deployer: 1,
        deployable_units: { "1": ["1"], "2": ["2"] },
        deployed_units: [],
        deployment_complete: false,
      },
    });

  it("refus moteur (HTTP 200, success:false) → changeRoster rejette en nommant la raison", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: deploiementActif() })
      ),
      http.post("/api/game/action", () =>
        HttpResponse.json({
          success: false,
          result: { error: "change_roster_locked_after_first_deploy", current_deployer: 1 },
          game_state: deploiementActif(),
          action_logs: [],
          message: "Action failed",
        })
      )
    );

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    await expect(result.current.changeRoster("armageddon_space_marines.json", 1)).rejects.toThrow(
      "change_roster_locked_after_first_deploy"
    );
    // Le refus ne doit PAS dégénérer en panneau d'erreur fatal : le plateau reste jouable et le
    // message s'affiche à côté du bouton, dans le `catch` de l'appelant.
    expect(result.current.error).toBeNull();
  });

  it("succès → changeRoster résout, sans erreur posée", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: deploiementActif() })
      ),
      http.post("/api/game/action", () =>
        HttpResponse.json({
          success: true,
          result: { action: "change_roster", updated_player: 1 },
          game_state: deploiementActif(),
          action_logs: [],
          message: "Action executed successfully",
        })
      )
    );

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    await expect(
      result.current.changeRoster("armageddon_space_marines.json", 1)
    ).resolves.toBeUndefined();
    expect(result.current.error).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Canal de REFUS non fatal
//
// `error` est une PANNE : posé, il fait lever le hook (`API ERROR`) et, `BoardWithAPI` n'étant
// enveloppé d'aucun garde de rendu, la page devient blanche. Un refus de règle — « cible hors de
// portée », « unité pas dans le pool » — n'est pas une panne : il passe par `actionRefusal`, qui
// laisse le plateau jouable et s'efface au geste suivant.
// ---------------------------------------------------------------------------

describe("useEngineAPI — canal de refus", () => {
  /** Réponse de refus du moteur : HTTP 200, `success: false`, raison dans `result.error`. */
  const refus = (code: string, etat: Record<string, unknown>) =>
    HttpResponse.json({
      success: false,
      result: { error: code },
      game_state: etat,
      action_logs: [],
      message: "Action failed",
    });

  it("refus d'un geste → message posé, plateau VIVANT (aucune panne)", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: makeGameState() })
      ),
      http.post("/api/game/action", () => refus("unit_not_in_pool", makeGameState()))
    );

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    await act(async () => {
      await result.current.onSetAdvanceMode(10);
    });

    expect(result.current.actionRefusal).toContain("unit_not_in_pool");
    expect(result.current.actionRefusal).toContain("Advance");
    // LE PLATEAU RESTE JOUABLE : c'est tout l'objet du canal séparé.
    expect(result.current.error).toBeNull();
    // Et l'effet de bord du succès n'est PAS appliqué : le jet d'advance n'existe pas.
    expect(result.current.advanceRoll).toBeNull();
  });

  it("le geste suivant efface le message", async () => {
    let refuse = true;
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: makeGameState() })
      ),
      http.post("/api/game/action", () => {
        if (refuse) return refus("unit_not_in_pool", makeGameState());
        return HttpResponse.json({
          success: true,
          result: { advance_roll: 3 },
          game_state: makeGameState(),
          action_logs: [],
        });
      })
    );

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    await act(async () => {
      await result.current.onSetAdvanceMode(10);
    });
    expect(result.current.actionRefusal).not.toBeNull();

    refuse = false;
    await act(async () => {
      await result.current.onSetAdvanceMode(10);
    });

    expect(result.current.actionRefusal).toBeNull();
    expect(result.current.advanceRoll).toBe(3);
  });

  it("succès → aucun message, et l'effet de bord est appliqué", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: makeGameState() })
      ),
      http.post("/api/game/action", () =>
        HttpResponse.json({
          success: true,
          result: { advance_roll: 5 },
          game_state: makeGameState(),
          action_logs: [],
        })
      )
    );

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    await act(async () => {
      await result.current.onSetAdvanceMode(10);
    });

    expect(result.current.actionRefusal).toBeNull();
    expect(result.current.advanceRoll).toBe(5);
  });

  it("clearActionRefusal referme le message sans jouer", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: makeGameState() })
      ),
      http.post("/api/game/action", () => refus("unit_not_in_pool", makeGameState()))
    );

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    await act(async () => {
      await result.current.onSetAdvanceMode(10);
    });
    expect(result.current.actionRefusal).not.toBeNull();

    act(() => {
      result.current.clearActionRefusal();
    });

    expect(result.current.actionRefusal).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Desperate Escape (09.07) — un refus REPOSE l'avertissement
//
// Le clic du joueur ferme le popup AVANT l'appel. Si le moteur refuse, le danger n'est pas
// résolu, mais `ensureActivatedNoHazard` lit ce popup pour répondre « pas de danger en attente » :
// laisser le popup fermé faisait partir l'unité en mouvement avec son hazard en suspens.
// ---------------------------------------------------------------------------

describe("useEngineAPI — refus de la confirmation de danger", () => {
  /** Ouvre le popup hazard comme le moteur le fait : réponse `requires_hazard` à l'activation. */
  async function ouvrePopupHazard() {
    let premierAppel = true;
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: makeGameState() })
      ),
      http.post("/api/game/action", () => {
        if (premierAppel) {
          premierAppel = false;
          return HttpResponse.json({
            success: true,
            result: { action: "requires_hazard", requires_hazard: true, unitId: "10" },
            game_state: makeGameState(),
            action_logs: [],
          });
        }
        // Deuxième appel = la confirmation : REFUSÉE.
        return HttpResponse.json({
          success: false,
          result: { error: "hazard_already_resolved" },
          game_state: makeGameState(),
          action_logs: [],
          message: "Action failed",
        });
      })
    );

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });

    await act(async () => {
      await result.current.onSelectUnit(10);
    });
    await waitFor(() => expect(result.current.hazardWarningPopup).not.toBeNull(), {
      timeout: 5000,
    });
    return result;
  }

  it("confirmation refusée → l'avertissement est REPOSÉ, le message est lu", async () => {
    const result = await ouvrePopupHazard();

    await act(async () => {
      await result.current.onConfirmHazardWarning();
    });

    expect(result.current.actionRefusal).toContain("hazard_already_resolved");
    // REPOSÉ : sans lui, le prochain geste de mouvement croirait le danger réglé.
    expect(result.current.hazardWarningPopup).toEqual({ unitId: 10 });
    expect(result.current.error).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// PvE, phase fight : le bot a attaqué (`/game/ai-turn`), le DÉFENSEUR HUMAIN alloue ses pertes
// (05.03/05.04). Le prompt s'ouvre depuis la réponse du tour IA, sans attendre un geste humain.
// ---------------------------------------------------------------------------

describe("readManualAllocationPrompt", () => {
  const allocation = {
    attacker_unit_id: "2",
    target_unit_id: "1",
    defender_player: 1,
    choices: [{ model_id: "1#0", col: 0, row: 0, HP_CUR: 5, HP_MAX: 5 }],
    wounds_remaining: 1,
  };

  it("payload fight en attente → allocation de famille fight", () => {
    expect(
      readManualAllocationPrompt({
        action: "squad_fight_manual_alloc",
        waiting_for_player: true,
        allocation,
      })
    ).toEqual({ ...allocation, kind: "fight" });
  });

  it("familles shoot et hazard reconnues", () => {
    expect(
      readManualAllocationPrompt({
        action: "squad_shoot_manual_alloc",
        waiting_for_player: true,
        allocation,
      })?.kind
    ).toBe("shoot");
    expect(
      readManualAllocationPrompt({
        action: "squad_hazard_manual_alloc",
        waiting_for_player: true,
        allocation,
      })?.kind
    ).toBe("hazard");
  });

  it("pas une attente d'allocation → null (autre action, pas d'attente, sans allocation)", () => {
    expect(
      readManualAllocationPrompt({ action: "wait", waiting_for_player: true, allocation })
    ).toBeNull();
    expect(
      readManualAllocationPrompt({
        action: "squad_fight_manual_alloc",
        waiting_for_player: false,
        allocation,
      })
    ).toBeNull();
    expect(
      readManualAllocationPrompt({ action: "squad_fight_manual_alloc", waiting_for_player: true })
    ).toBeNull();
    expect(readManualAllocationPrompt(undefined)).toBeNull();
  });
});

describe("useEngineAPI — executeAITurn, allocation du défenseur humain en phase fight", () => {
  it("ROUGE sans la prise en charge : `/game/ai-turn` rend squad_fight_manual_alloc → prompt posé, boucle arrêtée", async () => {
    const fightState = makeGameState({
      phase: "fight",
      fight_subphase: "fight",
      current_player: 2,
      player_types: { "1": "human", "2": "ai" },
      fight_eligible_units: ["2"],
      move_activation_pool: [],
      units: [makeUnit(1, 1), makeUnit(2, 2)],
    });
    const allocation = {
      attacker_unit_id: "2",
      target_unit_id: "1",
      defender_player: 1,
      choices: [{ model_id: "1#0", col: 0, row: 0, HP_CUR: 5, HP_MAX: 5 }],
      wounds_remaining: 1,
    };
    let aiTurnCalls = 0;
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: fightState })
      ),
      http.post("/api/game/ai-turn", () => {
        aiTurnCalls += 1;
        return HttpResponse.json({
          success: true,
          result: { action: "squad_fight_manual_alloc", waiting_for_player: true, allocation },
          game_state: fightState,
          action_logs: [],
        });
      })
    );

    // Le mode vient de l'URL (`?mode=pve`) : c'est lui qui autorise un siège 2 de type "ai".
    window.history.replaceState({}, "", "/game?mode=pve");
    try {
      const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
      await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5000 });
      expect(result.current.manualAllocation).toBeNull();

      await act(async () => {
        await result.current.executeAITurn();
      });

      expect(result.current.manualAllocation).toEqual({ ...allocation, kind: "fight" });
      // La main est à l'humain : un seul appel, pas de relance tant qu'il n'a pas alloué.
      expect(aiTurnCalls).toBe(1);
    } finally {
      window.history.replaceState({}, "", "/game");
    }
  });
});

// ---------------------------------------------------------------------------
// Overrun fight 12.06 (PvP) — pile-in ADDITIONNEL par-figurine avant le combat.
//
// PDF 12 : « EFFECT: Your unit can make one additional pile-in move, then fights ». Le moteur
// expose ``overrun_eligible`` sur l'état d'attente FIGHT ; le bouton Overrun émet
// ``overrun_pile_in`` → réponse ``pile_in_model_move`` + ``overrun_pile_in`` (même mode que le
// pile-in 12.02) ; le commit ramène au COMBAT de la même unité (cibles recalculées), pas à la
// sélection. Avant ce lot, aucune action du front ne portait l'overrun : l'unité passait.
// ---------------------------------------------------------------------------

describe("useEngineAPI — overrun 12.06 (pile-in additionnel)", () => {
  function fightGameState(active: string | null) {
    const attacker = makeUnit(1, 1, { col: 20, row: 20, ATTACK_LEFT: 1 });
    const foe = makeUnit(2, 2, { col: 23, row: 20, ATTACK_LEFT: 1 });
    return makeGameState({
      phase: "fight",
      fight_subphase: "fight",
      fight_eligible_units: ["1"],
      active_fight_unit: active,
      move_activation_pool: [],
      units: [attacker, foe],
      units_cache: {
        "1": { occupied_hexes_by_model: { "1#0": [20, 20] } },
        "2": { occupied_hexes_by_model: { "2#0": [23, 20] } },
      },
    });
  }

  function fightWait(validTargets: string[], overrunEligible: boolean) {
    return {
      phase: "fight",
      fight_subphase: "fight",
      active_fight_unit: "1",
      unitId: "1",
      valid_targets: validTargets,
      overrun_eligible: overrunEligible,
      waiting_for_player: true,
      action: "wait",
    };
  }

  const overrunPlanState = {
    phase: "fight",
    fight_subphase: "fight",
    pile_in_model_move: true,
    overrun_pile_in: true,
    unitId: "1",
    active_fight_unit: "1",
    origin_models: { "1#0": [20, 20] },
    provisional: {},
    eligible_models: ["1#0"],
    selected_model: null,
    pool: [],
    footprint_mask_loops: [],
    unplaced: ["1#0"],
    can_validate: true,
    per_model_valid: { "1#0": true },
    coherency_ok: true,
    unit_engaged: true,
    kept_engagements: true,
    engaged_models: ["1#0"],
    pile_in_targets: ["2"],
    waiting_for_player: true,
    action: "wait",
  };

  /** Démarre en étape FIGHT, active l'unité 1 (sans cible, overrun possible), ouvre l'overrun. */
  async function ouvreOverrun(bodies: Array<Record<string, unknown>>) {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: fightGameState(null) })
      ),
      http.post("/api/game/action", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        bodies.push(body);
        if (body.action === "activate_unit") {
          return HttpResponse.json({
            success: true,
            game_state: fightGameState("1"),
            result: fightWait([], true),
          });
        }
        if (body.action === "overrun_pile_in") {
          return HttpResponse.json({
            success: true,
            game_state: fightGameState("1"),
            result: overrunPlanState,
          });
        }
        if (body.action === "commit_pile_in_plan") {
          // Le commit rend la main au combat : l'unité, toujours active, a maintenant une cible
          // et a épuisé son unique pile-in additionnel.
          return HttpResponse.json({
            success: true,
            game_state: fightGameState("1"),
            result: fightWait(["2"], false),
          });
        }
        if (body.action === "skip") {
          // Sous plan overrun, skip = renoncer au move : l'unité reste active, sans cible.
          return HttpResponse.json({
            success: true,
            game_state: fightGameState("1"),
            result: fightWait([], true),
          });
        }
        throw new Error(`action inattendue ${String(body.action)}`);
      })
    );

    const { result } = renderHook(() => useEngineAPI({ terrainList: TEST_TERRAIN_LIST }));
    await waitFor(
      () => {
        expect(result.current.loading).toBe(false);
        expect(result.current.maxTurns).not.toBeNull();
      },
      { timeout: 5000 }
    );

    await act(async () => {
      await result.current.onSelectUnit(1);
    });
    expect(result.current.mode).toBe("attackPreview");
    expect(result.current.fightOverrunEligible).toBe(true);
    expect(result.current.squadFightPlan?.unitId).toBe(1);

    await act(async () => {
      await result.current.onOverrunPileIn();
    });
    expect(bodies.at(-1)).toMatchObject({ action: "overrun_pile_in", unitId: "1" });
    expect(result.current.mode).toBe("pileInModelMove");
    expect(result.current.pileInMovePlan).toMatchObject({
      unitId: 1,
      overrun: true,
      canValidate: true,
      pileInTargets: ["2"],
    });
    // Le plan fight local est purgé le temps du move (sinon il intercepte les clics de pose).
    expect(result.current.squadFightPlan).toBeNull();
    return result;
  }

  it("commit du pile-in additionnel → retour au combat de la même unité, cibles recalculées", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    const result = await ouvreOverrun(bodies);

    await act(async () => {
      await result.current.onCommitPileInPlan();
    });
    expect(bodies.at(-1)).toMatchObject({ action: "commit_pile_in_plan", plan: [] });
    expect(result.current.mode).toBe("attackPreview");
    expect(result.current.selectedUnitId).toBe(1);
    expect(result.current.pileInMovePlan).toBeNull();
    expect(result.current.squadFightPlan?.unitId).toBe(1);
    expect(result.current.fightOverrunEligible).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("abandon du pile-in additionnel (skip) → l'unité reste active et peut encore l'ouvrir", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    const result = await ouvreOverrun(bodies);

    await act(async () => {
      await result.current.onCancelPileInModelMove();
    });
    expect(bodies.at(-1)).toMatchObject({ action: "skip" });
    expect(result.current.mode).toBe("attackPreview");
    expect(result.current.selectedUnitId).toBe(1);
    expect(result.current.pileInMovePlan).toBeNull();
    expect(result.current.squadFightPlan?.unitId).toBe(1);
    expect(result.current.fightOverrunEligible).toBe(true);
  });
});
