// frontend/src/roster/tyranid/units/Psychophage .ts
//

import { getWeapons } from "../armory";
import { TroopMeleeTroop } from "../classes/TroopMeleeTroop";

export class Psychophage extends TroopMeleeTroop {
  static NAME = "Psychophage";
  static DISPLAY_NAME = "Psychophage";
  // BASE
  static MOVE = 8; // Move distance
  static T = 9; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 10; // Max hit points
  static LD = 8; // Leadership score
  static OC = 3; // Operative Control
  static VALUE = 125; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["psychoclastic_torrent"];
  static RNG_WEAPONS = getWeapons(Psychophage.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["talons_and_betencacled_maw"];
  static CC_WEAPONS = getWeapons(Psychophage.CC_WEAPON_CODES);

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [
    { keywordId: "monster" },
    { keywordId: "great devourer" },
    { keywordId: "harvester" },
    { keywordId: "psychophage" },
  ];

  // ICON
  static ICON = "/icons/Psychophage.webp"; // Path relative to public folder
  static BASE_SHAPE = "oval"; // Shape of the base
  /** Diamètres sur la grille micro-hex (engine/hex_utils ``compute_occupied_hexes``), pas des mm. */
  static BASE_SIZE = [47, 36];
  static ICON_SCALE = 2.2; // Size of the icon
  static ILLUSTRATION_RATIO = 120; // Illustration size ratio in percent

  constructor(name: string, startPos: [number, number]) {
    super(name, Psychophage.HP_MAX, startPos);
  }
}
