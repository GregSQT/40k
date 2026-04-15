// frontend/src/roster/tyranid/units/RipperSwarm.ts

import { getWeapons } from "../armory";
import { SwarmMeleeSwarm } from "../classes/SwarmMeleeSwarm";

export class RipperSwarm extends SwarmMeleeSwarm {
  static NAME = "RipperSwarm";
  static DISPLAY_NAME = "Ripper Swarm";
  // BASE
  static MOVE = 6; // Move distance
  static T = 2; // Toughness score
  static ARMOR_SAVE = 6; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 4; // Max hit points
  static LD = 8; // Leadership score
  static OC = 0; // Operative Control
  static VALUE = 15; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["spinemaws"];
  static RNG_WEAPONS = getWeapons(RipperSwarm.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["chitinous_claws_and_teeth_ripper_swarm"];
  static CC_WEAPONS = getWeapons(RipperSwarm.CC_WEAPON_CODES);

   // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "swarm"}, { keywordId: "great devourer"}, { keywordId: "harverster"}, { keywordId: "ripper swarm"}];


  // ICON
  static ICON = "/icons/RipperSwarm.webp"; // Path relative to public folder
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = 16; // Size of the base
  static ICON_SCALE = 1.2; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, RipperSwarm.HP_MAX, startPos);
  }
}
