// frontend/src/roster/spaceMarine/units/VanguardVeteranSquadJumpPackPlasma.ts
//

import { getWeapons } from "../armory";
import { TroopRangeSwarm } from "../classes/TroopRangeSwarm";

export class VanguardVeteranSquadJumpPackPlasma extends TroopRangeSwarm {
  static NAME = "VanguardVeteranSquadJumpPackPlasma";
  static DISPLAY_NAME = "Vanguard Veteran Squad with Jump Packs (Plasma)";
  // BASE
  static MOVE = 12; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 1; // Operative Control
  static VALUE = 20; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["plasma_pistol_standard", "plasma_pistol_supercharge"];
  static RNG_WEAPONS = getWeapons(VanguardVeteranSquadJumpPackPlasma.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["master_crafted_power_weapon_A3"];
  static CC_WEAPONS = getWeapons(VanguardVeteranSquadJumpPackPlasma.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "INFANTRY" },
    { keywordId: "EXPLOSIVES" },
    { keywordId: "JUMP PACK" },
    { keywordId: "FLY" },
    { keywordId: "IMPERIUM" },
    { keywordId: "VANGUARD VETERAN SQUAD WITH JUMP PACKS" },
  ];

  // FACTION KEYWORDS
  static FACTION_KEYWORDS = [{ keywordId: "ADEPTUS ASTARTES" }];

  static ICON = "/icons/VanguardVeteranSquadJumpPackPlasma.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 13; // Size of the base
  static MODEL_HEIGHT = 2.5; // Height of the model (inches). IMPORTANT: temporary indicative value
  static ICON_SCALE = 1.7; // Scale of the icon
  static ILLUSTRATION_RATIO = 95; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, VanguardVeteranSquadJumpPackPlasma.HP_MAX, startPos);
  }
}
