// frontend/src/roster/spaceMarine/units/AssaultIntercessor.ts

import { getWeapons } from "../armory";
import { TroopMeleeTroop } from "../classes/TroopMeleeTroop";

export class AssaultIntercessorJumpPackPlasmaPistol extends TroopMeleeTroop {
  static NAME = "AssaultIntercessorJumpPackPlasmaPistol";
  static DISPLAY_NAME = "Assault Intercessor Jump Pack (Plasma Pistol)";
  // BASE
  static MOVE = 12; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 19; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["plasma_pistol_standard", "plasma_pistol_supercharge"];
  static RNG_WEAPONS = getWeapons(AssaultIntercessorJumpPackPlasmaPistol.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["assault_intercessor_chainsword"];
  static CC_WEAPONS = getWeapons(AssaultIntercessorJumpPackPlasmaPistol.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "charge_impact", displayName: "Hammer of wrath" }];
  // RULE IMPLEMENTATION STATUS (0=NOT_IMPLEMENTED, 1=NOT_IMPLEMENTABLE_YET, 2=IMPLEMENTED)
  static RULES_STATUS = { charge_impact: 2 };

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "grenades"}, { keywordId: "jump_pack"}, { keywordId: "fly"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "assault intercessors with jump packs"}];


  static ICON = "/icons/AssaultIntercessorJumpPackPlasmaPistol.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 13; // Size of the base
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, AssaultIntercessorJumpPackPlasmaPistol.HP_MAX, startPos);
  }
}
