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
    ) as { phase?: string; fight_subphase?: string; fight_eligible_units?: number[] } | undefined;
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

  it("attache [SHOOTER_MODELS:] a l'action de tir (figs ayant reellement tire)", () => {
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
      "[12:00:02] T1 P1 SHOOT : Unit 1(0,0) SHOT [Kombi Rokkit] Unit 2(1,0) - Hit 4(3+) - Dmg:1HP [SHOOTER_MODELS: 1#3]",
      "[12:00:03] T1 P1 SHOOT : Unit 1(0,0) SHOT [Slugga] Unit 2(1,0) - Hit 4(3+) - Dmg:0HP",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const parsed = parse_log_file_from_text(text);
    const shoots = parsed.episodes[0].actions.filter(
      (a) => (a as { type?: string }).type === "shoot"
    ) as Array<{ shooter_models?: string[] }>;
    expect(shoots.length).toBe(2);
    // 1er tir : segment present -> restreint a la fig 1#3.
    expect(shoots[0].shooter_models).toEqual(["1#3"]);
    // 2e tir : pas de segment -> undefined (aucune restriction, comportement escouade complete).
    expect(shoots[1].shooter_models).toBeUndefined();
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

  // ── Instantanés OBJECTIVE CONTROL : état 14.02 produit par le moteur ──
  // Le replay n'a plus le droit de resommer l'OC lui-même (ni empreinte de socle, ni
  // battle-shock côté navigateur) : il transporte l'état moteur tel quel.

  const CONTROL_LOG_HEAD = [
    "=== EPISODE 1 START ===",
    "Scenario: demo",
    "Bot: RandomBot",
    `Rules: ${VALID_RULES_JSON}`,
    "[12:00:00] Board: cols=10 rows=10 inches_to_subhex=1 hex_radius=2.78 margin=1",
    "[12:00:00] Objectives: West:(1,1);(1,2)|North:(5,5)",
    "Unit 1 (Intercessor) P1: Starting position (0, 0), HP_MAX=5",
  ];

  it("attache l'instantané moteur de contrôle/VP à l'état de la timeline", () => {
    const text = [
      ...CONTROL_LOG_HEAD,
      "[12:00:00] T1 OBJECTIVE CONTROL: VP1=0 VP2=0 ZONES=West:Ctrl=none|North:Ctrl=none",
      "[12:00:01] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "[12:00:02] T2 OBJECTIVE CONTROL: VP1=4 VP2=1 ZONES=West:Ctrl=1|North:Ctrl=2",
      "[12:00:03] T2 P1 MOVE : Unit 1(2,0) MOVED from (1,0) to (2,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const episode = parse_log_file_from_text(text).episodes[0];
    // Instantané écrit avant toute action -> porté par l'état initial.
    expect(episode.initial_state.objective_control).toEqual({
      controllers: { West: null, North: null },
      victory_points: { 1: 0, 2: 0 },
    });
    // L'instantané T2 est écrit APRÈS la 1re action : il décrit donc l'état d'après cette
    // action, et c'est bien elle qu'il horodate (after_actions = 1).
    expect(episode.states[0].objective_control).toEqual({
      controllers: { West: 1, North: 2 },
      victory_points: { 1: 4, 2: 1 },
    });
    // La 2e action n'est suivie d'aucun nouvel instantané : le dernier connu reste en vigueur
    // (14.02 — le contrôle est figé jusqu'à la prochaine fin de phase).
    expect(episode.states[1].objective_control).toEqual({
      controllers: { West: 1, North: 2 },
      victory_points: { 1: 4, 2: 1 },
    });
  });

  it("rejette un journal qui déclare des objectifs sans instantané de contrôle", () => {
    // Contrat strict (Replay.md §2) : un ancien step.log n'est plus rejouable. Afficher des VP
    // vides sans rien dire masquerait le vrai problème — le contrôle n'est plus recalculable ici.
    const text = [
      ...CONTROL_LOG_HEAD,
      "[12:00:01] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");
    expect(() => parse_log_file_from_text(text)).toThrow(
      /without OBJECTIVE CONTROL snapshot.*Regenerate step\.log/s
    );
  });

  it("accepte un journal sans objectif déclaré (scénario sans zone)", () => {
    // Le moteur n'écrit aucun instantané quand il n'y a rien à contrôler : ce n'est pas un
    // journal périmé, et l'exiger casserait un scénario légitime.
    const text = [
      "=== EPISODE 1 START ===",
      "Scenario: demo",
      "Bot: RandomBot",
      `Rules: ${VALID_RULES_JSON}`,
      "[12:00:00] Board: cols=10 rows=10 inches_to_subhex=1 hex_radius=2.78 margin=1",
      "[12:00:00] Objectives: none",
      "Unit 1 (Intercessor) P1: Starting position (0, 0), HP_MAX=5",
      "[12:00:01] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");
    const episode = parse_log_file_from_text(text).episodes[0];
    expect(episode.states[0].objective_control).toBeUndefined();
  });

  it("ignore le récapitulatif OBJECTIVE CONTROL de fin d'épisode", () => {
    // Format différent (ni T{tour} ni VP1=) : le confondre avec un instantané écraserait
    // l'état affiché par un récapitulatif dépourvu de contrôleurs par nom.
    const text = [
      ...CONTROL_LOG_HEAD,
      "[12:00:01] T1 OBJECTIVE CONTROL: VP1=3 VP2=0 ZONES=West:Ctrl=1|North:Ctrl=none",
      "[12:00:02] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "[12:00:03] OBJECTIVE CONTROL: Obj1:P1_OC=6,P2_OC=0,Ctrl=1 | Obj2:P1_OC=0,P2_OC=0,Ctrl=None",
      "[12:00:04] T1 P1 MOVE : Unit 1(2,0) MOVED from (1,0) to (2,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");
    const episode = parse_log_file_from_text(text).episodes[0];
    // L'état qui SUIT le récapitulatif doit garder l'instantané T1 intact : un motif laxiste y
    // aurait injecté des zones fantômes tirées du récapitulatif.
    expect(episode.states[1].objective_control).toEqual({
      controllers: { West: 1, North: null },
      victory_points: { 1: 3, 2: 0 },
    });
  });

  it("lève sur une zone OBJECTIVE CONTROL malformée", () => {
    const text = [
      ...CONTROL_LOG_HEAD,
      "[12:00:01] T1 OBJECTIVE CONTROL: VP1=0 VP2=0 ZONES=West:Ctrl=3",
      "[12:00:02] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");
    expect(() => parse_log_file_from_text(text)).toThrow(/Malformed OBJECTIVE CONTROL zone/);
  });
});
