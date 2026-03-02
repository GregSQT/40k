// frontend/src/roster/spaceMarine/units/BloodClaw.ts

import { getWeapons } from "../armory";
import { SpaceMarineInfantryTroopMeleeTroop } from "../classes/SpaceMarineInfantryTroopMeleeTroop";

export class BloodClaw extends SpaceMarineInfantryTroopMeleeTroop {
  static NAME = "BloodClaw";
  static DISPLAY_NAME = "Blood Claw";
  // BASE
  static MOVE = 7; // Move distance
  static T = 4; // Toughness score
  static ARMOR_SAVE = 3; // Armor save score
  static INVUL_SAVE = 7; // Armor invulnerable save score (7+ = no invul)
  static HP_MAX = 2; // Max hit points
  static LD = 6; // Leadership score
  static OC = 2; // Operative Control
  static VALUE = 13; // Unit value (W40K points cost)

  // WEAPONS
  static RNG_WEAPON_CODES = ["bolt_pistol"];
  static RNG_WEAPONS = getWeapons(BloodClaw.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["assault_intercessor_chainsword"];
  static CC_WEAPONS = getWeapons(BloodClaw.CC_WEAPON_CODES);

  // UNIT RULES
  static UNIT_RULES = [
    {
      ruleId: "charge_after_advance",
      displayName: "Berserk Charge",
    },
  ];

  // UNIT KEYWORDS
  static UNIT_KEYWORDS = [{ keywordId: "infantry"}, { keywordId: "battleline"}, { keywordId: "grenades"}, { keywordId: "imperium"}, { keywordId: "tacticus"}, { keywordId: "bloodclaws"}];

  // AI CLASSIFICATION
  static TANKING_LEVEL = "Troop"; // Troop: 2 wounds, 3+ save
  static MOVE_TYPE = "Infantry"; // Standard infantry movement
  static TARGET_TYPE = "Swarm"; // MeleeSwarm specialist - backbone melee

  static ICON = "/icons/BloodClaw.webp"; // Path relative to public folder
  static ICON_SCALE = 1.7; // Size of the icon

  constructor(name: string, startPos: [number, number]) {
    super(name, BloodClaw.HP_MAX, startPos);
  }
}
