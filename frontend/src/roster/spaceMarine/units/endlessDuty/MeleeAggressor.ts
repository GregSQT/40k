import { getWeapons } from "../../armory";
import { EliteMeleeElite } from "../../classes/EliteMeleeElite";
import { AggressorFlamestorm } from "../AggressorFlamestorm";

export class MeleeAggressor extends EliteMeleeElite {
  static NAME = "MeleeAggressor";
  static DISPLAY_NAME = "Aggressor";
  static EVOLUTION_FILE = "melee_evolution.json";
  static PROFILE_NAME = "Aggressor";
  static STARTER_LOADOUT_ID = "melee_aggressor_starter";

  static MOVE = AggressorFlamestorm.MOVE;
  static T = AggressorFlamestorm.T;
  static ARMOR_SAVE = AggressorFlamestorm.ARMOR_SAVE;
  static INVUL_SAVE = AggressorFlamestorm.INVUL_SAVE;
  static HP_MAX = AggressorFlamestorm.HP_MAX;
  static LD = AggressorFlamestorm.LD;
  static OC = AggressorFlamestorm.OC;
  static VALUE = AggressorFlamestorm.VALUE;

  static RNG_WEAPON_CODES = ["flamestorm_gauntlets"];
  static RNG_WEAPONS = getWeapons(MeleeAggressor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist"];
  static CC_WEAPONS = getWeapons(MeleeAggressor.CC_WEAPON_CODES);

  static UNIT_RULES = [{ ruleId: "closest_target_penetration", displayName: "Close-quarter firepower" }];
  static RULES_STATUS = { closest_target_penetration: 2 };
  static UNIT_KEYWORDS = [...AggressorFlamestorm.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = AggressorFlamestorm.ICON;
  static ICON_SCALE = AggressorFlamestorm.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, MeleeAggressor.HP_MAX, startPos);
  }
}
