// frontend/src/roster/tyranid/units/Gargoyle.ts

import { getWeapons } from "../armory";
import { SwarmMeleeSwarm } from "../classes/SwarmMeleeSwarm";

export class Gargoyle extends SwarmMeleeSwarm {
  static NAME = "Gargoyle";
  static DISPLAY_NAME = "Gargoyle";
  // BASE
  static MOVE = 12; // Move distance
  static T = 3; // Toughness score
  static ARMOR_SAVE = 6; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 8; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 7; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["fleshborer"];
  static RNG_WEAPONS = getWeapons(Gargoyle.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["blinding_venom"];
  static CC_WEAPONS = getWeapons(Gargoyle.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [{ ruleId: "move_after_shouting", displayName: "Winged Swarm" }];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "fly"}, { keywordId: "great devourer"}, { keywordId: "endless multitude"}, { keywordId: "tyranids"}, { keywordId: "gargoyle"}];

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm"; // Swarm: 1 wound, fragile
  static MOVE_TYPE = "Infantry"; // Fast infantry movement
  static TARGET_TYPE = "Swarm"; // MeleeSwarm specialist - mob assault

  // ICON
  static ICON = "/icons/Gargoyle.webp"; // Path relative to public folder
  static ICON_SCALE = 1.2; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, Gargoyle.HP_MAX, startPos);
  }
}
