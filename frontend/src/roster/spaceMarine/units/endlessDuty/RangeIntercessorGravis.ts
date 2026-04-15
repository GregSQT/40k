import { getWeapons } from "../../armory";
import { EliteRangeTroop } from "../../classes/EliteRangeTroop";
import { HeavyIntercessor } from "../HeavyIntercessor";

export class RangeIntercessorGravis extends EliteRangeTroop {
  static NAME = "RangeIntercessorGravis";
  static DISPLAY_NAME = "Intercessor Gravis";
  static EVOLUTION_FILE = "range_evolution.json";
  static PROFILE_NAME = "IntercessorGravis";
  static STARTER_LOADOUT_ID = "range_intercessor_gravis_starter";

  static MOVE = HeavyIntercessor.MOVE;
  static T = HeavyIntercessor.T;
  static ARMOR_SAVE = HeavyIntercessor.ARMOR_SAVE;
  static INVUL_SAVE = HeavyIntercessor.INVUL_SAVE;
  static HP_MAX = HeavyIntercessor.HP_MAX;
  static LD = HeavyIntercessor.LD;
  static OC = HeavyIntercessor.OC;
  static VALUE = HeavyIntercessor.VALUE;

  static RNG_WEAPON_CODES = ["heavy_bolt_rifle", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(RangeIntercessorGravis.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(RangeIntercessorGravis.CC_WEAPON_CODES);

  static UNIT_KEYWORDS = [...HeavyIntercessor.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = HeavyIntercessor.ICON;
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = HeavyIntercessor.BASE_SIZE; // Size of the base
  static ICON_SCALE = HeavyIntercessor.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, RangeIntercessorGravis.HP_MAX, startPos);
  }
}
