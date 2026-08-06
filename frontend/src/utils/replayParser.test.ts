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

  // Le journal ne porte ni terrain, ni icones, ni zones de deploiement : le replay les relit dans
  // la config du scenario JOUE, qu'il ne connait que par cette ligne. Sans elle il affiche le
  // terrain du scenario par defaut, alors qu'un entrainement en tire un different par episode.
  it("extrait le chemin du scenario joue, sans le confondre avec le nom de scenario", () => {
    const text = [
      "=== EPISODE 1 START ===",
      "[12:00:00] Scenario: Random from 3 scenarios",
      "[12:00:00] Scenario file: config/agents/ArmageddonAgent/scenarios/training/scenario_bot-02.json",
      "Bot: RandomBot",
      `Rules: ${VALID_RULES_JSON}`,
      "[12:00:00] Board: cols=10 rows=10 inches_to_subhex=1 hex_radius=2.78 margin=1",
      "Unit 1 (Intercessor) P1: Starting position (0, 0), HP_MAX=5",
      "[12:00:01] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const parsed = parse_log_file_from_text(text);
    expect(parsed.episodes[0].scenario_file).toBe(
      "config/agents/ArmageddonAgent/scenarios/training/scenario_bot-02.json"
    );
    expect(parsed.episodes[0].scenario).toBe("Random from 3 scenarios");
  });

  it("laisse scenario_file absent sur un journal ecrit avant cette ligne", () => {
    const text = [
      "=== EPISODE 1 START ===",
      "[12:00:00] Scenario: demo",
      `Rules: ${VALID_RULES_JSON}`,
      "[12:00:00] Board: cols=10 rows=10 inches_to_subhex=1 hex_radius=2.78 margin=1",
      "Unit 1 (Intercessor) P1: Starting position (0, 0), HP_MAX=5",
      "[12:00:01] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    expect(parse_log_file_from_text(text).episodes[0].scenario_file).toBeUndefined();
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

  it("lit les CP quand le journal les porte", () => {
    const text = [
      ...CONTROL_LOG_HEAD,
      "[12:00:00] T1 OBJECTIVE CONTROL: VP1=2 VP2=1 CP1=5 CP2=4 ZONES=West:Ctrl=1|North:Ctrl=none",
      "[12:00:01] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const episode = parse_log_file_from_text(text).episodes[0];
    expect(episode.initial_state.objective_control).toEqual({
      controllers: { West: 1, North: null },
      victory_points: { 1: 2, 2: 1 },
      command_points: { 1: 5, 2: 4 },
    });
  });

  it("reste lisible sur un journal enregistré AVANT les CP", () => {
    // RETROCOMPATIBILITE : `CP1=/CP2=` est apparu le 2026-08-04 entre les VP et `ZONES=`. Un
    // motif non optionnel cesserait de matcher tous les step.log anterieurs, et le replay les
    // declarerait « sans instantane » — il refuse alors de les rejouer. Le champ doit rester
    // ABSENT (pas 0) : un 0 mentirait sur le stock de CP de la partie rejouee.
    const text = [
      ...CONTROL_LOG_HEAD,
      "[12:00:00] T1 OBJECTIVE CONTROL: VP1=2 VP2=1 ZONES=West:Ctrl=1|North:Ctrl=none",
      "[12:00:01] T1 P1 MOVE : Unit 1(1,0) MOVED from (0,0) to (1,0)",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const control = parse_log_file_from_text(text).episodes[0].initial_state.objective_control;
    expect(control).toEqual({
      controllers: { West: 1, North: null },
      victory_points: { 1: 2, 2: 1 },
    });
    expect(control?.command_points).toBeUndefined();
  });

  // Les capacités nommées vivaient UNIQUEMENT dans le texte de la ligne : le replay affichait le
  // message brut mais son détail déplié ne pouvait rien en dire, alors que le PvP les reçoit du
  // moteur dans `shootDetails`. Le parseur les extrait donc des tokens accolés à chaque jet.
  it("extrait les capacités de relance et le +1 d'Oath d'une ligne de TIR", () => {
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
      "[12:00:02] T1 P1 SHOOT : Unit 1(0,0) SHOT [Bolt Rifle] Unit 2(1,0)" +
        " - Hit 4(3+) [COVER] [OATH OF MOMENT]" +
        " - Wound 6(3+) [TARGETED INTERCESSION] [OATH OF MOMENT]" +
        " - Save 2(3+) - Dmg:1HP",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const shoot = parse_log_file_from_text(text).episodes[0].actions.find(
      (a) => (a as { type?: string }).type === "shoot"
    ) as { hit_ability?: string; wound_ability?: string; wound_bonus_ability?: string };
    // [COVER] est un modificateur de seuil, pas une capacité : il ne doit pas être pris pour un nom.
    expect(shoot.hit_ability).toBe("OATH OF MOMENT");
    // Côté blessure les deux coexistent : la relance, puis le +1 (qui n'est PAS une relance).
    expect(shoot.wound_ability).toBe("TARGETED INTERCESSION");
    expect(shoot.wound_bonus_ability).toBe("OATH OF MOMENT");
  });

  it("extrait les capacités d'une ligne de MÊLÉE (jumeau du tir)", () => {
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
      "[12:00:02] T1 P1 FIGHT : Unit 1(0,0) FOUGHT Unit 2(1,0) with [Chainsword]" +
        " - Hit 4(3+) [SUSTAINED HITS] [OATH OF MOMENT]" +
        " - Wound 4(4+) [TARGETED INTERCESSION]" +
        " - Save 2(3+) - Dmg:1HP [FIGHT_SUBPHASE:fight] [SUCCESS]",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const fight = parse_log_file_from_text(text).episodes[0].actions.find(
      (a) => (a as { type?: string }).type === "fight"
    ) as { hit_ability?: string; wound_ability?: string; wound_bonus_ability?: string };
    expect(fight.hit_ability).toBe("OATH OF MOMENT");
    expect(fight.wound_ability).toBe("TARGETED INTERCESSION");
    expect(fight.wound_bonus_ability).toBeUndefined();
  });

  // `[REROLLED:n]` porte le dé d'AVANT relance : sans lui le replay ne montrait que le second
  // dé, là où le combat log PvP affiche « 1->6 » pour la même attaque.
  it("extrait le dé d'origine d'un jet relancé, sans le prendre pour une capacité", () => {
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
      "[12:00:02] T1 P1 SHOOT : Unit 1(0,0) SHOT [Bolt Rifle] Unit 2(1,0)" +
        " - Hit 3(3+) [OATH OF MOMENT] [REROLLED:1]" +
        " - Wound 6(4+) [TARGETED INTERCESSION] [REROLLED:2]" +
        " - Save 4(3+) [REROLLED:1] - Dmg:1HP",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const shoot = parse_log_file_from_text(text).episodes[0].actions.find(
      (a) => (a as { type?: string }).type === "shoot"
    ) as {
      hit_roll?: number;
      hit_roll_initial?: number;
      wound_roll_initial?: number;
      save_roll_initial?: number;
      hit_ability?: string;
      wound_ability?: string;
    };
    expect(shoot.hit_roll).toBe(3);
    expect(shoot.hit_roll_initial).toBe(1);
    expect(shoot.wound_roll_initial).toBe(2);
    expect(shoot.save_roll_initial).toBe(1);
    // `[REROLLED:n]` n'est pas un nom de capacité : il ne doit pas en chasser un vrai.
    expect(shoot.hit_ability).toBe("OATH OF MOMENT");
    expect(shoot.wound_ability).toBe("TARGETED INTERCESSION");
  });

  // VERROU du discriminateur PAR NOM. Le segment Wound porte deux capacités possibles écrites
  // avec la MÊME syntaxe : la relance (`woundAbility`) puis le modificateur (`woundBonusAbility`).
  // Séparer par la POSITION est tentant — l'émetteur écrit toujours relance puis bonus — mais
  // c'est faux dès qu'il n'y a qu'un token, et c'est le cas le PLUS FRÉQUENT : Oath ne pose que
  // `hit_any_fail`, il ne relance jamais la blessure. Un token unique `[OATH OF MOMENT]` est donc
  // toujours un bonus, jamais une relance.
  it("classe un token de blessure SEUL par son nom, pas par sa position", () => {
    const shootLine = (woundTokens: string) =>
      [
        "=== EPISODE 1 START ===",
        "Scenario: demo",
        "Bot: RandomBot",
        `Rules: ${VALID_RULES_JSON}`,
        "[12:00:00] Board: cols=10 rows=10 inches_to_subhex=1 hex_radius=2.78 margin=1",
        "Unit 1 (Intercessor) P1: Starting position (0, 0), HP_MAX=5",
        "Unit 2 (Termagant) P2: Starting position (2, 0), HP_MAX=4",
        "[12:00:00] T1 P1 DEPLOYMENT : Unit 1(-1,-1) DEPLOYED from (-1,-1) to (0,0)",
        "[12:00:01] T1 P2 DEPLOYMENT : Unit 2(-1,-1) DEPLOYED from (-1,-1) to (1,0)",
        "[12:00:02] T1 P1 SHOOT : Unit 1(0,0) SHOT [Bolt Rifle] Unit 2(1,0)" +
          ` - Hit 4(3+) - Wound 5(3+)${woundTokens} - Save 2(3+) - Dmg:1HP`,
        "EPISODE END: Winner=1, Method=elimination",
      ].join("\n");
    const parse = (line: string) =>
      parse_log_file_from_text(line).episodes[0].actions.find(
        (a) => (a as { type?: string }).type === "shoot"
      ) as { wound_ability?: string; wound_bonus_ability?: string };

    // Le +1 d'Oath SEUL : c'est un modificateur. La position (1er token) dirait « relance ».
    const bonusSeul = parse(shootLine(" [OATH OF MOMENT]"));
    expect(bonusSeul.wound_bonus_ability).toBe("OATH OF MOMENT");
    expect(bonusSeul.wound_ability).toBeUndefined();

    // Une relance SEULE, au même rang : c'est bien une relance.
    const relanceSeule = parse(shootLine(" [TARGETED INTERCESSION]"));
    expect(relanceSeule.wound_ability).toBe("TARGETED INTERCESSION");
    expect(relanceSeule.wound_bonus_ability).toBeUndefined();
  });

  it("ne prend aucun token de règle d'arme pour une capacité", () => {
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
      "[12:00:02] T1 P1 SHOOT : Unit 1(0,0) SHOT [RAPID FIRE:2] [Bolt Rifle] Unit 2(1,0)" +
        " - Hit 4(4+->3+) [HEAVY] - Wound 5(4+) - Save 2(3+) - Dmg:1HP",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const shoot = parse_log_file_from_text(text).episodes[0].actions.find(
      (a) => (a as { type?: string }).type === "shoot"
    ) as { hit_ability?: string; wound_ability?: string };
    expect(shoot.hit_ability).toBeUndefined();
    expect(shoot.wound_ability).toBeUndefined();
  });

  // VERROU borne DROITE. Les fixtures ci-dessus finissent toutes par `Dmg:1HP`, qui protège le
  // dernier jet de la queue de ligne. Un jet RATÉ termine la ligne : la métadonnée (récompense,
  // figurines, sous-phase, issue) lui est alors collée sans séparateur ` - `, et se retrouvait
  // dans son segment. Mesuré sur un vrai `step.log` : `wound_ability = "R:+0.0"` en tir, et
  // `hit_ability = "FIGHT_SUBPHASE:fight"` sur CHAQUE attaque de mêlée ratée.
  it("ne prend pas la métadonnée de fin de ligne pour une capacité", () => {
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
      // Blessure ratée : la ligne s'arrête là, la métadonnée suit (forme réelle du step.log).
      "[12:00:02] T1 P1 SHOOT : Unit 1(0,0) SHOT [Bolt Rifle] Unit 2(1,0)" +
        " - Hit 5(3+) - Wound 1(4+) [R:+0.0] [MODELS: 1#0@(0,0)] [SHOOTER_MODELS: 1#0] [SUCCESS]",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const shoot = parse_log_file_from_text(text).episodes[0].actions.find(
      (a) => (a as { type?: string }).type === "shoot"
    ) as { hit_ability?: string; wound_ability?: string; wound_bonus_ability?: string };

    expect(shoot.wound_ability).toBeUndefined();
    expect(shoot.wound_bonus_ability).toBeUndefined();
    expect(shoot.hit_ability).toBeUndefined();
  });

  it("ne prend pas [FIGHT_SUBPHASE] pour une capacité sur une attaque de mêlée ratée", () => {
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
      // Touche ratée en mêlée : `[FIGHT_SUBPHASE:...]` est OBLIGATOIRE (le parser lève sans lui),
      // donc ce cas est celui de toutes les attaques ratées de tous les replays de combat.
      "[12:00:02] T1 P1 FIGHT : Unit 1(0,0) FOUGHT Unit 2(1,0) with [Chainsword]" +
        " - Hit 2(3+) [R:+0.0] [FIGHT_SUBPHASE:fight]",
      "EPISODE END: Winner=1, Method=elimination",
    ].join("\n");

    const fight = parse_log_file_from_text(text).episodes[0].actions.find(
      (a) => (a as { type?: string }).type === "fight"
    ) as { hit_ability?: string; hit_roll_initial?: number };

    expect(fight.hit_ability).toBeUndefined();
    expect(fight.hit_roll_initial).toBeUndefined();
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
