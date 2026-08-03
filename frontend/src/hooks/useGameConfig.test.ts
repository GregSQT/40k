// @vitest-environment jsdom
// Verrou du contrôle « résolution servie = résolution demandée » (useGameConfig).
// Le défaut qu'il attrape ne se voyait qu'à l'œil : décor servi en x5 fusionné avec la grille x1
// du journal → terrain cinq fois trop grand, murs et unités justes, aucune erreur.
// cf. Documentation/Implémentation/Replay.md §2.4.

import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useGameConfig } from "./useGameConfig";

const { apiFetchMock } = vi.hoisted(() => ({ apiFetchMock: vi.fn() }));
vi.mock("../services/apiFetch", () => ({ apiFetch: apiFetchMock }));

const GAME_CONFIG = {
  game_rules: {
    max_turns: 5,
    turn_limit_penalty: -1,
    los_debug_show_ratio: false,
    los_debug_show_ratio_rule: "none",
    max_units_per_player: 10,
  },
  charge: { charge_max_distance: 12, select_target_before_roll: false },
  gameplay: { phase_order: ["move"], simultaneous_actions: false, auto_end_turn: true },
  ai_behavior: { timeout_ms: 1000, retries: 0, fallback_action: "skip" },
};

/** Plateau tel que l'API le renvoie : les dimensions SUIVENT la résolution (44×60 en x1). */
const boardConfigAt = (inchesToSubhex: number) => ({
  cols: 44 * inchesToSubhex,
  rows: 60 * inchesToSubhex,
  hex_radius: 13.9 / inchesToSubhex,
  margin: 5,
  inches_to_subhex: inchesToSubhex,
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
});

/** L'API sert un plateau à `servedInchesToSubhex`, quoi que la requête ait demandé. */
const mockServer = (servedInchesToSubhex: number) => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(GAME_CONFIG), { status: 200 }))
  );
  apiFetchMock.mockImplementation(
    async () =>
      new Response(JSON.stringify({ success: true, config: boardConfigAt(servedInchesToSubhex) }), {
        status: 200,
      })
  );
};

afterEach(() => {
  vi.unstubAllGlobals();
  apiFetchMock.mockReset();
});

describe("useGameConfig — résolution servie vs demandée", () => {
  it("refuse une config servie dans une AUTRE résolution que celle demandée", async () => {
    mockServer(5);

    const { result } = renderHook(() =>
      useGameConfig({ inchesToSubhexOverride: 1, scenarioFileOverride: "config/scenario_x1.json" })
    );

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error).toContain("inches_to_subhex=5");
    expect(result.current.error).toContain("1 was requested");
    // La config fautive ne doit pas rester consommable : c'est elle qui dessinait le décor hybride.
    expect(result.current.boardConfig).toBeNull();
  });

  it("accepte la config servie dans la résolution demandée", async () => {
    mockServer(1);

    const { result } = renderHook(() =>
      useGameConfig({ inchesToSubhexOverride: 1, scenarioFileOverride: "config/scenario_x1.json" })
    );

    await waitFor(() => expect(result.current.boardConfig).not.toBeNull());
    expect(result.current.error).toBeNull();
    expect(result.current.boardConfig?.cols).toBe(44);
  });
});
