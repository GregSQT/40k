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

  it("leve une erreur si Rules manque alors que des actions existent", () => {
    const text = [
      "=== EPISODE 1 START ===",
      "Unit 1 (Intercessor) P1: Starting position (0, 0), HP_MAX=5",
      "[12:00:01] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");
    expect(() => parse_log_file_from_text(text)).toThrow(/Missing Rules block/);
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
