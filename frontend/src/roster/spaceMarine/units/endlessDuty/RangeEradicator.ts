import { getWeapons } from "../../armory";
import { EliteRangeTroop } from "../../classes/EliteRangeTroop";
import { EradicatorMeltaRifle } from "../EradicatorMeltaRifle";

export class RangeEradicator extends EliteRangeTroop {
  static NAME = "RangeEradicator";
  static DISPLAY_NAME = "Eradicator";
  static EVOLUTION_FILE = "range_evolution.json";
  static PROFILE_NAME = "Eradicator";
  static STARTER_LOADOUT_ID = "range_eradicator_starter";

  static MOVE = EradicatorMeltaRifle.MOVE;
  static T = EradicatorMeltaRifle.T;
  static ARMOR_SAVE = EradicatorMeltaRifle.ARMOR_SAVE;
  static INVUL_SAVE = EradicatorMeltaRifle.INVUL_SAVE;
  static HP_MAX = EradicatorMeltaRifle.HP_MAX;
  static LD = EradicatorMeltaRifle.LD;
  static OC = EradicatorMeltaRifle.OC;
  static VALUE = EradicatorMeltaRifle.VALUE;

  static RNG_WEAPON_CODES = ["melta_rifle"];
  static RNG_WEAPONS = getWeapons(RangeEradicator.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(RangeEradicator.CC_WEAPON_CODES);

  static UNIT_KEYWORDS = [...EradicatorMeltaRifle.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = EradicatorMeltaRifle.ICON;
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = EradicatorMeltaRifle.BASE_SIZE; // Size of the base
  static ICON_SCALE = EradicatorMeltaRifle.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, RangeEradicator.HP_MAX, startPos);
  }
}
