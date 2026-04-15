import { getWeapons } from "../../armory";
import { TroopMeleeSwarm } from "../../classes/TroopMeleeSwarm";
import { AssaultIntercessor } from "../AssaultIntercessor";

export class MeleeIntercessor extends TroopMeleeSwarm {
  static NAME = "MeleeIntercessor";
  static DISPLAY_NAME = "Intercessor";
  static EVOLUTION_FILE = "melee_evolution.json";
  static PROFILE_NAME = "Intercessor";
  static STARTER_LOADOUT_ID = "melee_intercessor_starter";

  static MOVE = AssaultIntercessor.MOVE;
  static T = AssaultIntercessor.T;
  static ARMOR_SAVE = AssaultIntercessor.ARMOR_SAVE;
  static INVUL_SAVE = AssaultIntercessor.INVUL_SAVE;
  static HP_MAX = AssaultIntercessor.HP_MAX;
  static LD = AssaultIntercessor.LD;
  static OC = AssaultIntercessor.OC;
  static VALUE = AssaultIntercessor.VALUE;

  static RNG_WEAPON_CODES = ["heavy_bolt_pistol"];
  static RNG_WEAPONS = getWeapons(MeleeIntercessor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["assault_intercessor_chainsword"];
  static CC_WEAPONS = getWeapons(MeleeIntercessor.CC_WEAPON_CODES);

  static UNIT_RULES = [
    {
      ruleId: "targeted_intercession",
      displayName: "Targeted Intercession",
      grants_rule_ids: [
        "targeted_intercession_reroll_1_towound",
        "targeted_intercession_reroll_towound_target_on_objective",
      ],
      usage: "and",
    },
  ];
  static RULES_STATUS = {
    targeted_intercession: 2,
    targeted_intercession_reroll_1_towound: 2,
    targeted_intercession_reroll_towound_target_on_objective: 2,
  };
  static UNIT_KEYWORDS = [...AssaultIntercessor.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = AssaultIntercessor.ICON;
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = AssaultIntercessor.BASE_SIZE; // Size of the base
  static ICON_SCALE = AssaultIntercessor.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, MeleeIntercessor.HP_MAX, startPos);
  }
}
