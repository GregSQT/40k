import { getWeapons } from "../../armory";
import { LeaderEliteMeleeElite } from "../../classes/LeaderEliteMeleeElite";
import { CaptainGravisPowerWeaponBoltRifle } from "../CaptainGravisPowerWeaponBoltRifle";

export class LeaderCaptainGravis extends LeaderEliteMeleeElite {
  static NAME = "LeaderCaptainGravis";
  static DISPLAY_NAME = "Captain Gravis";
  static STARTER_LOADOUT_ID = "captain_gravis_starter";

  // BASE (combat profile)
  static MOVE = CaptainGravisPowerWeaponBoltRifle.MOVE;
  static T = CaptainGravisPowerWeaponBoltRifle.T;
  static ARMOR_SAVE = CaptainGravisPowerWeaponBoltRifle.ARMOR_SAVE;
  static INVUL_SAVE = CaptainGravisPowerWeaponBoltRifle.INVUL_SAVE;
  static HP_MAX = CaptainGravisPowerWeaponBoltRifle.HP_MAX;
  static LD = CaptainGravisPowerWeaponBoltRifle.LD;
  static OC = CaptainGravisPowerWeaponBoltRifle.OC;
  static VALUE = CaptainGravisPowerWeaponBoltRifle.VALUE;

  // Runtime default ED loadout; ED runtime can override with selected loadout.
  // Must match config/endless_duty/leader_evolution.json STARTER_LOADOUT_ID.
  static CC_WEAPON_CODES = ["master_crafted_power_weapon_captain"];
  static CC_WEAPONS = getWeapons(LeaderCaptainGravis.CC_WEAPON_CODES);
  static RNG_WEAPON_CODES = ["master_crafted_heavy_bolt_rifle_captain"];
  static RNG_WEAPONS = getWeapons(LeaderCaptainGravis.RNG_WEAPON_CODES);

  static UNIT_KEYWORDS = [...CaptainGravisPowerWeaponBoltRifle.UNIT_KEYWORDS, { keywordId: "endless_duty" }];

  static ICON = "/icons/CaptainGravisPowerWeaponBoltRifle.webp";
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = CaptainGravisPowerWeaponBoltRifle.BASE_SIZE; // Size of the base
  static ICON_SCALE = CaptainGravisPowerWeaponBoltRifle.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, LeaderCaptainGravis.HP_MAX, startPos);
  }
}
