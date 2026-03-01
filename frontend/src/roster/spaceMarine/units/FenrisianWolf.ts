// frontend/src/roster/spaceMarine/units/FenrisianWolf.ts
//

import { getWeapons } from "../armory";
import { SpaceMarineInfantrySwarmMeleeSwarm } from "../classes/SpaceMarineInfantrySwarmMeleeSwarm.ts";

export class FenrisianWolf extends SpaceMarineInfantrySwarmMeleeSwarm {
  static NAME = "FenrisianWolf";
  static DISPLAY_NAME = "Fenrisian Wolf";
  // BASE
  static MOVE = 10; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 6; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 1; // Max hit points
  static LD = 8; // Leadership score
  static OC = 0; // Operative Control
  static VALUE = 8; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = [];
  static RNG_WEAPONS = getWeapons(FenrisianWolf.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["fenrisian_wolf_teeth_and_claws"];
  static CC_WEAPONS = getWeapons(FenrisianWolf.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    {
      ruleId: "reactive_move",
      displayName: "Predator Instinct",
    },
  ];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "beasts"}, { keywordId: "imperium"}, { keywordId: "fenrisian wolves"}];

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Swarm"; // Swarm: 1 wound, fragile
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Swarm"; // MeleeSwarm specialist - mob assault

  static ICON = "/icons/FenrisianWolf.webp"; // Path relative to public folder
  static ICON_SCALE = 1.4; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, FenrisianWolf.HP_MAX, startPos);
  }
}
