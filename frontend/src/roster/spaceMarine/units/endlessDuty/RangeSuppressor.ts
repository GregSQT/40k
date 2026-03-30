import { getWeapons } from "../../armory";
import { EliteRangeTroop } from "../../classes/EliteRangeTroop";
import { Suppressor } from "../Suppressor";

export class RangeSuppressor extends EliteRangeTroop {
  static NAME = "RangeSuppressor";
  static DISPLAY_NAME = "Suppressor";
  static EVOLUTION_FILE = "range_evolution.json";
  static PROFILE_NAME = "Suppressor";
  static STARTER_LOADOUT_ID = "range_suppressor_starter";

  static MOVE = Suppressor.MOVE;
  static T = Suppressor.T;
  static ARMOR_SAVE = Suppressor.ARMOR_SAVE;
  static INVUL_SAVE = Suppressor.INVUL_SAVE;
  static HP_MAX = Suppressor.HP_MAX;
  static LD = Suppressor.LD;
  static OC = Suppressor.OC;
  static VALUE = Suppressor.VALUE;

  static RNG_WEAPON_CODES = ["accelerator_autocannon", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(RangeSuppressor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(RangeSuppressor.CC_WEAPON_CODES);

  static UNIT_KEYWORDS = [...Suppressor.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = Suppressor.ICON;
  static ICON_SCALE = Suppressor.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, RangeSuppressor.HP_MAX, startPos);
  }
}
