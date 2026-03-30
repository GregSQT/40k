import { getWeapons } from "../../armory";
import { EliteRangeTroop } from "../../classes/EliteRangeTroop";
import { Terminator } from "../Terminator";

export class RangeTerminator extends EliteRangeTroop {
  static NAME = "RangeTerminator";
  static DISPLAY_NAME = "Terminator";
  static EVOLUTION_FILE = "range_evolution.json";
  static PROFILE_NAME = "Terminator";
  static STARTER_LOADOUT_ID = "range_terminator_starter";

  static MOVE = Terminator.MOVE;
  static T = Terminator.T;
  static ARMOR_SAVE = Terminator.ARMOR_SAVE;
  static INVUL_SAVE = Terminator.INVUL_SAVE;
  static HP_MAX = Terminator.HP_MAX;
  static LD = Terminator.LD;
  static OC = Terminator.OC;
  static VALUE = Terminator.VALUE;

  static RNG_WEAPON_CODES = ["storm_bolter"];
  static RNG_WEAPONS = getWeapons(RangeTerminator.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["power_fist"];
  static CC_WEAPONS = getWeapons(RangeTerminator.CC_WEAPON_CODES);

  static UNIT_KEYWORDS = [...Terminator.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = Terminator.ICON;
  static ICON_SCALE = Terminator.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, RangeTerminator.HP_MAX, startPos);
  }
}
