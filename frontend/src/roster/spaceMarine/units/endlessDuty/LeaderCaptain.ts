import { getWeapons } from "../../armory";
import { LeaderEliteMeleeElite } from "../../classes/LeaderEliteMeleeElite";
import { CaptainPowerFistPlasmaPistol } from "../CaptainPowerFistPlasmaPistol";

export class LeaderCaptain extends LeaderEliteMeleeElite {
  static NAME = "LeaderCaptain";
  static DISPLAY_NAME = "Captain";
  static STARTER_LOADOUT_ID = "captain_starter";

  // BASE (combat profile)
  static MOVE = CaptainPowerFistPlasmaPistol.MOVE;
  static T = CaptainPowerFistPlasmaPistol.T;
  static ARMOR_SAVE = CaptainPowerFistPlasmaPistol.ARMOR_SAVE;
  static INVUL_SAVE = CaptainPowerFistPlasmaPistol.INVUL_SAVE;
  static HP_MAX = CaptainPowerFistPlasmaPistol.HP_MAX;
  static LD = CaptainPowerFistPlasmaPistol.LD;
  static OC = CaptainPowerFistPlasmaPistol.OC;
  static VALUE = CaptainPowerFistPlasmaPistol.VALUE;

  // Runtime default ED loadout; ED runtime can override with selected loadout.
  // Must match config/endless_duty/leader_evolution.json STARTER_LOADOUT_ID.
  static CC_WEAPON_CODES = ["close_combat_weapon_captain"];
  static CC_WEAPONS = getWeapons(LeaderCaptain.CC_WEAPON_CODES);
  static RNG_WEAPON_CODES = ["master_crafted_bolter_captain", "bolt_pistol_captain"];
  static RNG_WEAPONS = getWeapons(LeaderCaptain.RNG_WEAPON_CODES);

  static UNIT_KEYWORDS = [...CaptainPowerFistPlasmaPistol.UNIT_KEYWORDS, { keywordId: "endless_duty" }];

  static ICON = "/icons/CaptainPowerFistPlasmaPistol.webp";
  static ICON_SCALE = CaptainPowerFistPlasmaPistol.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, LeaderCaptain.HP_MAX, startPos);
  }
}
