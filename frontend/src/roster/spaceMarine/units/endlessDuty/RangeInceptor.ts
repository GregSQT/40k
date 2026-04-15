import { getWeapons } from "../../armory";
import { EliteRangeTroop } from "../../classes/EliteRangeTroop";
import { InceptorBolter } from "../InceptorBolter";

export class RangeInceptor extends EliteRangeTroop {
  static NAME = "RangeInceptor";
  static DISPLAY_NAME = "Inceptor";
  static EVOLUTION_FILE = "range_evolution.json";
  static PROFILE_NAME = "Inceptor";
  static STARTER_LOADOUT_ID = "range_inceptor_starter";

  static MOVE = InceptorBolter.MOVE;
  static T = InceptorBolter.T;
  static ARMOR_SAVE = InceptorBolter.ARMOR_SAVE;
  static INVUL_SAVE = InceptorBolter.INVUL_SAVE;
  static HP_MAX = InceptorBolter.HP_MAX;
  static LD = InceptorBolter.LD;
  static OC = InceptorBolter.OC;
  static VALUE = InceptorBolter.VALUE;

  static RNG_WEAPON_CODES = ["assault_bolters"];
  static RNG_WEAPONS = getWeapons(RangeInceptor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(RangeInceptor.CC_WEAPON_CODES);

  static UNIT_KEYWORDS = [...InceptorBolter.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = InceptorBolter.ICON;
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = InceptorBolter.BASE_SIZE; // Size of the base
  static ICON_SCALE = InceptorBolter.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, RangeInceptor.HP_MAX, startPos);
  }
}
