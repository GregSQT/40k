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
 *
 * T_BoardWithAPI_MortalWoundsTarget — Exhortation of Rage (Chaplain JP). Le moteur arrête le combat
 * à l'activation de l'unité sur le choix de la cible (`mortal_wounds_target`, plusieurs ennemis
 * engagés) et REFUSE toute autre action tant qu'il n'est pas fait : sans panneau, la partie PvP se
 * figerait. Un bouton par unité ennemie rendue par le moteur, libellée par son nom (le moteur
 * n'envoie que son id), et c'est l'INDEX qui est joué (`agent_decision` + `option_index`).
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

/** Forme posée par `_check_and_trigger_exhortation_de_rage` (engine/w40k_core.py) : un candidat
 *  par unité ennemie ENGAGÉE, `label` = son id, aucun candidat `declines`. */
const MORTAL_WOUNDS_TARGET_DECISION = {
  type: "mortal_wounds_target",
  player: 1,
  unit_id: "1",
  options: [{ label: "2" }, { label: "3" }],
};

/** Les deux cibles, pour que le panneau puisse les NOMMER. `makeUnit` (déclaré plus bas, hissé)
 *  porte tout ce que `convertUnits` exige d'une unité. */
const MORTAL_WOUNDS_TARGET_UNITS = [
  { ...makeUnit(1, 1), DISPLAY_NAME: "Chaplain", col: 5, row: 5 },
  { ...makeUnit(2, 2), DISPLAY_NAME: "Boyz", col: 6, row: 5 },
  { ...makeUnit(3, 2), col: 5, row: 6 },
];

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

describe("BoardWithAPI — panneau de cible d'Exhortation of Rage", () => {
  function renderWithMortalWoundsDecision(mode: "pvp" | "pve", seat1: "human" | "ai") {
    if (mode === "pve") {
      localStorage.setItem("w40k_auth_session_v2", FAKE_SESSION_PVE);
      window.history.replaceState({}, "", "/game?mode=pve");
    }
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({
          success: true,
          game_state: makeGameState({
            phase: "fight",
            // En PvE le siège IA est le joueur 2 (`useEngineAPI` refuse l'inverse) : la décision
            // du bot est donc posée au joueur 2 dans ce cas.
            player_types: { "1": "human", "2": seat1 },
            units: MORTAL_WOUNDS_TARGET_UNITS,
            pending_agent_decision: {
              ...MORTAL_WOUNDS_TARGET_DECISION,
              player: seat1 === "ai" ? 2 : 1,
            },
          }),
        })
      )
    );
    renderBoard(mode === "pve" ? "/game?mode=pve" : "/");
  }

  it("siège humain → un bouton par ennemi engagé, nommé, et le clic joue l'INDEX du candidat", async () => {
    const posted: unknown[] = [];
    server.use(
      http.post("/api/game/action", async ({ request }) => {
        posted.push(await request.json());
        return HttpResponse.json({
          success: true,
          result: { action: "wait" },
          game_state: makeGameState({ phase: "fight", units: MORTAL_WOUNDS_TARGET_UNITS }),
        });
      })
    );
    renderWithMortalWoundsDecision("pvp", "human");

    await waitFor(
      () => {
        expect(screen.getByText(/Exhortation of Rage — unit 1 — player 1/)).toBeTruthy();
      },
      { timeout: 5000 }
    );
    expect(screen.getByRole("button", { name: "Boyz #2" })).toBeTruthy();
    const second = screen.getByRole("button", { name: "Squad 3 #3" });
    expect(second).toBeTruthy();

    fireEvent.click(second);
    await waitFor(() => {
      expect(posted.length).toBeGreaterThan(0);
    });
    expect(posted[0]).toMatchObject({ action: "agent_decision", option_index: 1 });
  });

  it("siège IA → le panneau n'est PAS rendu (la politique du bot répond, pas l'humain)", async () => {
    renderWithMortalWoundsDecision("pve", "ai");

    await waitFor(
      () => {
        expect(screen.getByTestId("board-pvp")).toBeTruthy();
      },
      { timeout: 5000 }
    );

    expect(screen.queryByText(/Exhortation of Rage — unit 1/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Boyz #2" })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// T_BoardWithAPI_AutoRoster — l'échec d'application d'un roster enregistré DIT POURQUOI
//
// L'écran de préparation applique les rosters mémorisés dans localStorage. Son message d'échec
// était écrit en dur (« Roster enregistré introuvable ») : depuis que `changeRoster` fait
// remonter les refus du moteur, ce libellé aurait accusé le fichier alors que le moteur refuse
// le GESTE (`change_roster_locked_after_first_deploy` après une première pose, par exemple —
// atteignable, l'écran de préparation se rouvrant à chaque rechargement de page en déploiement).
// ---------------------------------------------------------------------------

describe("BoardWithAPI — auto-application des rosters enregistrés", () => {
  /** Déploiement ACTIF : le seul état où l'écran de préparation s'ouvre. */
  const deploiementActif = (over: Record<string, unknown> = {}) =>
    makeGameState({
      phase: "deployment",
      deployment_type: "active",
      deployment_state: {
        current_deployer: 1,
        deployable_units: { "1": [], "2": [] },
        deployed_units: [],
        deployment_complete: false,
      },
      ...over,
    });

  it("refus du moteur → le message nomme le fichier ET la raison", async () => {
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
    localStorage.setItem("gameprep_roster_p1", "armageddon_space_marines.json");

    renderBoard();

    await waitFor(
      () => {
        expect(screen.getByText(/Game preparation/)).toBeTruthy();
      },
      { timeout: 5000 }
    );
    await waitFor(
      () => {
        expect(
          screen.getByText(
            /armageddon_space_marines\.json.*change_roster_locked_after_first_deploy/
          )
        ).toBeTruthy();
      },
      { timeout: 5000 }
    );
  });

  it("un roster accepté, l'autre refusé → seul le refusé porte un message", async () => {
    // CONTRE-ÉPREUVE NON VACANTE. Asserter « aucun message » juste après l'ouverture de l'écran
    // laissait passer un refus : l'assertion négative s'exécutait avant que le POST ait résolu
    // (mesuré — le test restait vert en refusant tout). Ici les deux rosters sont appliqués
    // SÉQUENTIELLEMENT par l'écran (p1 attendu, puis p2) : voir le message de p2 prouve donc que
    // l'application de p1 est terminée, et c'est ce qui rend son absence de message concluante.
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: deploiementActif() })
      ),
      http.post("/api/game/action", async ({ request }) => {
        const body = (await request.json()) as { player?: number };
        if (body.player === 2) {
          return HttpResponse.json({
            success: false,
            result: { error: "change_roster_locked_after_first_deploy", current_deployer: 2 },
            game_state: deploiementActif(),
            action_logs: [],
            message: "Action failed",
          });
        }
        return HttpResponse.json({
          success: true,
          result: { action: "change_roster", updated_player: 1 },
          game_state: deploiementActif(),
          action_logs: [],
          message: "Action executed successfully",
        });
      })
    );
    localStorage.setItem("gameprep_roster_p1", "armageddon_space_marines.json");
    localStorage.setItem("gameprep_roster_p2", "armageddon_orks.json");

    renderBoard();

    await waitFor(
      () => {
        expect(
          screen.getByText(/armageddon_orks\.json.*change_roster_locked_after_first_deploy/)
        ).toBeTruthy();
      },
      { timeout: 5000 }
    );
    expect(screen.queryByText(/armageddon_space_marines\.json/)).toBeNull();
  });

  it("non-action → l'armée n'est PAS annoncée comme appliquée", async () => {
    // TROISIÈME ISSUE d'`executeAction` : il n'envoie rien et rend `undefined`, SANS poser
    // d'erreur — ici parce que la partie est terminée (mêmes portes : aperçu d'un point de
    // sauvegarde actif, partie non démarrée). La traiter comme un succès ferait mémoriser un
    // roster que le moteur n'a jamais appliqué. Le cas de l'échec réseau, lui, n'a pas besoin de
    // ce garde-fou : `executeAction` y appelle `setError`, et le hook lève alors `API ERROR`,
    // donc l'écran entier est remplacé — rien à afficher à côté d'un bouton qui n'existe plus.
    let actionAppelee = false;
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({ success: true, game_state: deploiementActif({ game_over: true }) })
      ),
      http.post("/api/game/action", () => {
        actionAppelee = true;
        return HttpResponse.json({ success: true, game_state: deploiementActif() });
      })
    );
    localStorage.setItem("gameprep_roster_p1", "armageddon_space_marines.json");

    renderBoard();

    await waitFor(
      () => {
        expect(
          screen.getByText(/armageddon_space_marines\.json.*aucune action exécutée/)
        ).toBeTruthy();
      },
      { timeout: 5000 }
    );
    // VERT NON VACANT dans l'autre sens : le message vient bien d'une NON-ACTION, pas d'un appel
    // parti puis refusé — aucune requête n'a quitté le client.
    expect(actionAppelee).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// T_BoardWithAPI_ReservesDeclaration — 20.01, la question et le siège
// ---------------------------------------------------------------------------

/** Unité au format que `useEngineAPI.convertUnits` EXIGE — il lève sur chaque champ manquant. */
function makeUnit(id: number, player: 1 | 2) {
  return {
    id,
    player,
    unitType: `Squad${id}`,
    DISPLAY_NAME: `Squad ${id}`,
    col: -1,
    row: -1,
    MOVE: 6,
    HP_MAX: 10,
    HP_CUR: 10,
    T: 4,
    ARMOR_SAVE: 3,
    VALUE: 100,
    ICON: "/icons/test-unit.webp",
    BASE_SIZE: 32,
    BASE_SHAPE: "circular",
    ICON_SCALE: 1,
    ILLUSTRATION_RATIO: 1,
    SHOOT_LEFT: 0,
    ATTACK_LEFT: 0,
    RNG_WEAPONS: [],
    CC_WEAPONS: [],
    UNIT_RULES: [],
    UNIT_KEYWORDS: [],
  };
}

/** État de déploiement ACTIF où le camp `pendingPlayer` compose sa déclaration 20.01 ; sa seule
 *  escouade (`pendingUnitId`) est déclarable. */
function makeDeclarationState(o: {
  pendingPlayer: 1 | 2;
  pendingUnitId: string;
  seat2: "human" | "ai";
  /** Escouades déjà en réserves et annulables par le camp déclarant (défaut : aucune). */
  cancellable?: string[];
}) {
  const cancellable = o.cancellable ?? [];
  const units = [makeUnit(7, 1), makeUnit(11, 2)].map((u) =>
    cancellable.includes(String(u.id)) ? { ...u, in_strategic_reserves: true } : u
  );
  return makeGameState({
    phase: "deployment",
    deployment_type: "active",
    player_types: { "1": "human", "2": o.seat2 },
    units,
    units_cache: { "7": {}, "11": {} },
    // `current_player` ET `current_deployer` : le moteur écrit TOUJOURS les deux ensemble pendant
    // 20.01 (`move_seat_to_pending_reserves_declaration`), et un état qui n'en porterait qu'un
    // n'existe dans aucune partie. Le poser seul rendait l'orchestration du tour IA inatteignable
    // depuis ce fichier — elle lit `current_player` —, donc verte par-dessus n'importe quoi.
    current_player: o.pendingPlayer,
    deployment_state: {
      current_deployer: o.pendingPlayer,
      deployable_units: {
        "1": cancellable.includes("7") ? [] : ["7"],
        "2": cancellable.includes("11") ? [] : ["11"],
      },
      deployed_units: [],
      deployment_complete: false,
    },
    strategic_reserves: {
      last_round: 3,
      declaring_player: o.pendingPlayer,
      declarable: cancellable.includes(o.pendingUnitId) ? [] : [o.pendingUnitId],
      cancellable,
      "1": { used_points: 0, cap_points: 500 },
      "2": { used_points: 0, cap_points: 500 },
    },
  });
}

describe("BoardWithAPI — question 20.01 (Declare Battle Formations)", () => {
  /** Délai du `setTimeout` qui lance le tour IA dans BoardWithAPI, plus une marge. */
  const AI_TURN_DELAY_MS = 1500;
  const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

  /** Rend une partie arrêtée sur la question 20.01, écran de préparation encore ouvert.
   *
   *  Rend le compteur d'appels à `/api/game/ai-turn` : c'est le seul canal par lequel le bot peut
   *  répondre à 20.01, donc la mesure directe de « le bot a-t-il joué ? ». */
  async function renderDeclaration(o: {
    mode: "pvp" | "pve";
    pendingPlayer: 1 | 2;
    pendingUnitId: string;
    seat2: "human" | "ai";
    /** Escouades déjà en réserves et annulables par le camp déclarant (défaut : aucune). */
    cancellable?: string[];
  }): Promise<{ aiTurnCalls: () => number }> {
    if (o.mode === "pve") {
      localStorage.setItem("w40k_auth_session_v2", FAKE_SESSION_PVE);
      window.history.replaceState({}, "", "/game?mode=pve");
    }
    let aiTurnCalls = 0;
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({
          success: true,
          game_state: makeDeclarationState(o),
        })
      ),
      http.post("/api/game/ai-turn", () => {
        aiTurnCalls += 1;
        // `ai_turn_skipped` arrête la boucle d'activation du hook après UN appel : ce fichier
        // compte les départs de tour IA, il ne rejoue pas une phase de déploiement.
        return HttpResponse.json({
          success: true,
          result: { action: "ai_turn_skipped", reason: "test" },
          game_state: makeDeclarationState(o),
          action_logs: [],
        });
      })
    );
    renderBoard(o.mode === "pve" ? "/game?mode=pve" : "/");
    // Point d'ancrage : la LIGNE de l'escouade interrogée est montée. Sans elle, toute assertion
    // d'absence ci-dessous serait vraie parce que rien n'est rendu, pas parce que la question
    // n'est pas posée.
    await waitFor(
      () => {
        expect(screen.getByTestId(`roster-row-select-${o.pendingUnitId}`)).toBeTruthy();
      },
      { timeout: 5000 }
    );
    return { aiTurnCalls: () => aiTurnCalls };
  }

  it("écran de préparation : la déclaration n'est pas ouverte, elle l'est au démarrage", async () => {
    // `deploymentStarted` est CÂBLÉ ici, pas seulement testé dans le prédicat : l'écran de
    // préparation est la seule fenêtre où le joueur peut encore changer d'armée, et le moteur
    // refuse ce changement dès le premier geste 20.01.
    await renderDeclaration({
      mode: "pvp",
      pendingPlayer: 1,
      pendingUnitId: "7",
      seat2: "human",
    });

    expect(screen.queryByTestId("strategic-reserves-declaration-banner")).toBeNull();
    expect(screen.queryByTestId("strategic-reserves-validate")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Start Deployment" }));

    await waitFor(
      () => {
        expect(screen.getByTestId("strategic-reserves-declaration-banner")).toBeTruthy();
      },
      { timeout: 5000 }
    );
    expect(screen.getByTestId("strategic-reserves-validate")).toBeTruthy();
  });

  it("`Reserve` n'apparaît qu'à la SÉLECTION d'une escouade déclarable, jamais `Deploy`", async () => {
    // 20.01 : « select one or more friendly units to place in strategic reserves. Instead of
    // setting up these units on the battlefield » — ne pas réserver, c'est déployer ; il n'y a
    // rien à déclarer pour ça, donc pas de bouton. La version précédente posait une question
    // fermée à deux boutons sur l'escouade que le moteur désignait ; la règle ne porte ni la
    // question, ni l'ordre.
    await renderDeclaration({
      mode: "pvp",
      pendingPlayer: 1,
      pendingUnitId: "7",
      seat2: "human",
    });
    fireEvent.click(screen.getByRole("button", { name: "Start Deployment" }));
    await waitFor(
      () => {
        expect(screen.getByTestId("strategic-reserves-declaration-banner")).toBeTruthy();
      },
      { timeout: 5000 }
    );
    // Sans sélection : rien sur la ligne. C'est la sélection qui porte le geste.
    expect(screen.queryByTestId("strategic-reserves-declare")).toBeNull();

    fireEvent.click(screen.getByTestId("roster-row-select-7"));

    await waitFor(
      () => {
        expect(screen.getByTestId("strategic-reserves-declare")).toBeTruthy();
      },
      { timeout: 5000 }
    );
    expect(screen.queryByTestId("strategic-reserves-keep")).toBeNull();
  });

  it("`Cancel` n'apparaît que sur une escouade que le moteur dit annulable", async () => {
    // Le conteneur de réserves porte `Cancel` sur les escouades de `strategic_reserves.cancellable`
    // — celles du camp déclarant, tant qu'il n'a pas validé. Ni éligibilité ni règle rejouée ici.
    await renderDeclaration({
      mode: "pvp",
      pendingPlayer: 1,
      pendingUnitId: "7",
      seat2: "human",
      cancellable: ["7"],
    });
    fireEvent.click(screen.getByRole("button", { name: "Start Deployment" }));

    await waitFor(
      () => {
        expect(screen.getByTestId("strategic-reserves-cancel")).toBeTruthy();
      },
      { timeout: 5000 }
    );
    // VERT VACANT : la même escouade, dans le conteneur, n'est PAS proposée à la réserve — elle y
    // est déjà. Sans cette assertion, un bouton `Reserve` égaré dans le conteneur passerait.
    expect(screen.queryByTestId("strategic-reserves-declare")).toBeNull();
  });

  it("siège piloté par le modèle : la déclaration du bot n'est jamais offerte à l'humain", async () => {
    // 20.01 : « you can select one or more friendly units » — c'est le camp qui déclare qui
    // décide. Le moteur refuse d'ailleurs cette route pour un siège non humain
    // (`reserves_declaration_seat_is_not_human`) : les boutons ne pourraient que revenir en
    // erreur.
    await renderDeclaration({
      mode: "pve",
      pendingPlayer: 2,
      pendingUnitId: "11",
      seat2: "ai",
    });

    fireEvent.click(screen.getByRole("button", { name: "Start Deployment" }));

    await waitFor(
      () => {
        expect(screen.getByTestId("roster-row-select-11")).toBeTruthy();
      },
      { timeout: 5000 }
    );
    expect(screen.queryByTestId("strategic-reserves-declaration-banner")).toBeNull();
    expect(screen.queryByTestId("strategic-reserves-validate")).toBeNull();
    expect(screen.queryByTestId("strategic-reserves-declare")).toBeNull();
  });

  it("siège humain sur le même camp : la déclaration EST ouverte", async () => {
    // VERT VACANT du test précédent : sans ce cas, un panneau muet pour une tout autre raison
    // rendrait l'absence verte pour rien. Même camp, même escouade, seul le siège change.
    await renderDeclaration({
      mode: "pvp",
      pendingPlayer: 2,
      pendingUnitId: "11",
      seat2: "human",
    });

    fireEvent.click(screen.getByRole("button", { name: "Start Deployment" }));

    await waitFor(
      () => {
        expect(screen.getByTestId("strategic-reserves-declaration-banner")).toBeTruthy();
      },
      { timeout: 5000 }
    );
  });

  it("écran de préparation, siège du bot : aucun tour IA ne part avant Start Deployment", async () => {
    // Le siège suit la question 20.01 dès le reset : `current_player` vaut 2 avant même que
    // l'humain ait démarré, dès que la première question due est celle du bot (file amputée des
    // unités du joueur 1 inéligibles). Sans garde, le bot répond à 20.01 pendant que l'écran de
    // préparation est encore affiché — le moteur refuse alors `change_roster`
    // (`change_roster_locked_after_reserves_declaration`) sur le SEUL écran où l'humain peut
    // encore choisir son armée.
    const { aiTurnCalls } = await renderDeclaration({
      mode: "pve",
      pendingPlayer: 2,
      pendingUnitId: "11",
      seat2: "ai",
    });

    await wait(AI_TURN_DELAY_MS + 500);
    expect(aiTurnCalls()).toBe(0);

    // VERT VACANT : le MÊME état, écran fermé, doit faire partir le tour IA. Sans ce second
    // temps, un tour IA cassé pour toute autre raison rendrait l'assertion ci-dessus verte.
    fireEvent.click(screen.getByRole("button", { name: "Start Deployment" }));
    await waitFor(
      () => {
        expect(aiTurnCalls()).toBeGreaterThan(0);
      },
      { timeout: 5000 }
    );
  }, 15000);
});

// ---------------------------------------------------------------------------
// T_BoardWithAPI_Refus — le refus du moteur s'affiche SANS fermer la partie
//
// Le canal fatal du hook (`error`) fait lever `API ERROR` au rendu suivant, et ce composant
// n'est enveloppé d'aucun garde de rendu : un refus de règle qui y passerait ferait disparaître
// l'écran. Le bandeau ci-dessous est la contre-mesure, et ce test vérifie les deux moitiés : le
// message EST lu, et l'écran EST encore là.
// ---------------------------------------------------------------------------

describe("BoardWithAPI — bandeau de refus", () => {
  it("réponse 20.01 refusée → message affiché, écran toujours vivant", async () => {
    server.use(
      http.post("/api/game/start", () =>
        HttpResponse.json({
          success: true,
          game_state: makeDeclarationState({
            pendingPlayer: 1,
            pendingUnitId: "7",
            seat2: "human",
          }),
        })
      ),
      http.post("/api/game/action", () =>
        HttpResponse.json({
          success: false,
          result: { error: "reserves_cap_exceeded" },
          game_state: makeDeclarationState({
            pendingPlayer: 1,
            pendingUnitId: "7",
            seat2: "human",
          }),
          action_logs: [],
          message: "Action failed",
        })
      )
    );

    renderBoard();
    await waitFor(
      () => {
        expect(screen.getByTestId("roster-row-select-7")).toBeTruthy();
      },
      { timeout: 5000 }
    );
    fireEvent.click(screen.getByRole("button", { name: "Start Deployment" }));
    await waitFor(
      () => {
        expect(screen.getByTestId("strategic-reserves-declaration-banner")).toBeTruthy();
      },
      { timeout: 5000 }
    );
    fireEvent.click(screen.getByTestId("roster-row-select-7"));
    await waitFor(
      () => {
        expect(screen.getByTestId("strategic-reserves-declare")).toBeTruthy();
      },
      { timeout: 5000 }
    );

    fireEvent.click(screen.getByTestId("strategic-reserves-declare"));

    await waitFor(
      () => {
        expect(screen.getByText(/reserves_cap_exceeded/)).toBeTruthy();
      },
      { timeout: 5000 }
    );
    // LA PARTIE EST TOUJOURS LÀ : c'est ce que le canal séparé achète. Le panneau fatal aurait
    // démonté jusqu'à la ligne de roster.
    expect(screen.getByTestId("roster-row-select-7")).toBeTruthy();
  });
});
