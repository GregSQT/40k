// frontend/src/roster/tyranid/units/TyranidWarriorMelee.ts
//

import { getWeapons } from "../armory";
import { TroopMeleeTroop } from "../classes/TroopMeleeTroop";

export class TyranidWarriorMelee extends TroopMeleeTroop {
  static NAME = "TyranidWarriorMelee";
  static DISPLAY_NAME = "Tyranid Warrior (Melee)";
  // BASE
  static MOVE = 6; // Move distance
  static T = 5; // Toughness score
  static ARMOR_SAVE = 4; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 3; // Max hit points
  static LD = 7; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 32; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(TyranidWarriorMelee.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["bio_weapon_warrior"];
  static CC_WEAPONS = getWeapons(TyranidWarriorMelee.CC_WEAPON_CODES);

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 3 wounds, 4+ save
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Troop"; // RangedTroop specialist - anti-infantry

  // UNIT RULES
  static UNIT_RULES = [
    {
      ruleId: "adrenalised_onslaught",
      displayName: "Adrenalised Onslaught",
      grants_rule_ids: [
        "aggression_imperative",
        "preservation_imperative",
      ],
      usage: "or",
      choice_timing: {
        trigger: "phase_start",
        phase: "fight",
        active_player_scope: "both",
      },
    },
  ];
  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = {
    adrenalised_onslaught: 2,
    aggression_imperative: 2,
    preservation_imperative: 2,
  };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "great devourer"}, { keywordId: "synapse"}, { keywordId: "tyranids"}, { keywordId: "tyranid warrior with melee bio-weapon"}];

  // ICON
  static ICON = "/icons/TyranidWarriorMelee.webp"; // Path relative to public folder
  static ICON_SCALE = 2.2; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, TyranidWarriorMelee.HP_MAX, startPos);
  }
}
