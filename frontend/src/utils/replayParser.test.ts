import { describe, expect, it } from "vitest";
import { parse_log_file_from_text } from "./replayParser";

const VALID_RULES_JSON =
  '{"primary_objective":{"id":"po","scoring":{"start_turn":1,"max_points_per_turn":5,"rules":[{"id":"r1","points":5,"condition":"control_at_least_one"}]},"timing":{"default_phase":"command","round5_second_player_phase":"command"},"control":{"method":"sticky","control_method":"oc","tie_behavior":"keep"}}}';

describe("replayParser", () => {
  it("parse un episode minimal avec deployment/move", () => {
    const text = [
      "=== EPISODE 1 START ===",
      "Scenario: demo",
      "Bot: RandomBot",
      `Rules: ${VALID_RULES_JSON}`,
      "[12:00:00] Board: cols=10 rows=10 inches_to_subhex=1 hex_radius=2.78 margin=1",
      "Unit 1 (Intercessor) P1: Starting position (0, 0), HP_MAX=5",
      "Unit 2 (Termagant) P2: Starting position (2, 0), HP_MAX=4",
      "[12:00:00] T1 P1 DEPLOYMENT : Unit 1(-1,-1) DEPLOYED from (-1,-1) to (0,0)",
      "[12:00:01] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const parsed = parse_log_file_from_text(text);
    expect(parsed.total_episodes).toBe(1);
    expect(parsed.episodes[0].scenario).toBe("demo");
    expect(parsed.episodes[0].actions.length).toBeGreaterThan(0);
    expect(parsed.episodes[0].states.length).toBeGreaterThan(0);
  });

  it("classe pile_in/consolidation en phase fight avec l'unite qui bouge comme active", () => {
    const text = [
      "=== EPISODE 1 START ===",
      "Scenario: demo",
      "Bot: RandomBot",
      `Rules: ${VALID_RULES_JSON}`,
      "[12:00:00] Board: cols=10 rows=10 inches_to_subhex=1 hex_radius=2.78 margin=1",
      "Unit 1 (Intercessor) P1: Starting position (0, 0), HP_MAX=5",
      "Unit 2 (Termagant) P2: Starting position (2, 0), HP_MAX=4",
      "[12:00:00] T1 P1 DEPLOYMENT : Unit 1(-1,-1) DEPLOYED from (-1,-1) to (0,0)",
      "[12:00:01] T1 P2 DEPLOYMENT : Unit 2(-1,-1) DEPLOYED from (-1,-1) to (1,0)",
      "[12:00:02] T1 P1 FIGHT : Unit 1(0,0) PILED IN from (0,0) to (1,1)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const parsed = parse_log_file_from_text(text);
    const pileState = parsed.episodes[0].states.find(
      (s) => (s as { fight_subphase?: string }).fight_subphase === "pile_in"
    ) as
      | { phase?: string; fight_subphase?: string; fight_eligible_units?: number[] }
      | undefined;
    expect(pileState).toBeDefined();
    expect(pileState!.phase).toBe("fight");
    expect(pileState!.fight_eligible_units).toEqual([1]);
  });

  it("leve une erreur si Rules manque alors que des actions existent", () => {
    const text = [
      "=== EPISODE 1 START ===",
      "Unit 1 (Intercessor) P1: Starting position (0, 0), HP_MAX=5",
      "[12:00:01] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");
    expect(() => parse_log_file_from_text(text)).toThrow(/Missing Rules block/);
  });

  it("expose UNIQUEMENT l'attaquant comme unite eligible dans l'etat fight", () => {
    const text = [
      "=== EPISODE 1 START ===",
      "Scenario: demo",
      "Bot: RandomBot",
      `Rules: ${VALID_RULES_JSON}`,
      "[12:00:00] Board: cols=10 rows=10 inches_to_subhex=1 hex_radius=2.78 margin=1",
      "Unit 1 (Intercessor) P1: Starting position (0, 0), HP_MAX=5",
      "Unit 2 (Termagant) P2: Starting position (2, 0), HP_MAX=4",
      "[12:00:00] T1 P1 DEPLOYMENT : Unit 1(-1,-1) DEPLOYED from (-1,-1) to (0,0)",
      "[12:00:01] T1 P2 DEPLOYMENT : Unit 2(-1,-1) DEPLOYED from (-1,-1) to (1,0)",
      "[12:00:02] T1 P1 FIGHT : Unit 1(0,0) FOUGHT Unit 2(1,0) with [Close Combat Weapon] - Hit 4(3+) - Wound 4(4+) - Save 2(3+) - Dmg:1HP [R:+0.0] [FIGHT_SUBPHASE:fight] [SUCCESS]",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const parsed = parse_log_file_from_text(text);
    const fightState = parsed.episodes[0].states.find(
      (s) => (s as { phase?: string }).phase === "fight"
    ) as { fight_eligible_units?: number[]; fight_subphase?: string } | undefined;
    expect(fightState).toBeDefined();
    expect(fightState!.fight_subphase).toBe("fight");
    // Seule l'unite qui frappe (attaquant = 1), pas la cible ni un pool.
    expect(fightState!.fight_eligible_units).toEqual([1]);
  });

  it("leve une erreur si control_method est absent dans Rules", () => {
    const badRules =
      '{"primary_objective":{"id":"po","scoring":{"start_turn":1,"max_points_per_turn":5,"rules":[{"id":"r1","points":5,"condition":"control_at_least_one"}]},"timing":{"default_phase":"command","round5_second_player_phase":"command"},"control":{"method":"sticky","tie_behavior":"keep"}}}';
    const text = [
      "=== EPISODE 1 START ===",
      `Rules: ${badRules}`,
      "Unit 1 (Intercessor) P1: Starting position (0, 0), HP_MAX=5",
      "[12:00:01] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");
    expect(() => parse_log_file_from_text(text)).toThrow(/control_method is missing/);
  });
});
