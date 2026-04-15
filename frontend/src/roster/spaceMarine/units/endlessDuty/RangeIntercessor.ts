import { getWeapons } from "../../armory";
import { TroopRangeSwarm } from "../../classes/TroopRangeSwarm";
import { Intercessor } from "../Intercessor";

export class RangeIntercessor extends TroopRangeSwarm {
  static NAME = "RangeIntercessor";
  static DISPLAY_NAME = "Intercessor";
  static EVOLUTION_FILE = "range_evolution.json";
  static PROFILE_NAME = "Intercessor";
  static STARTER_LOADOUT_ID = "range_intercessor_starter";

  static MOVE = Intercessor.MOVE;
  static T = Intercessor.T;
  static ARMOR_SAVE = Intercessor.ARMOR_SAVE;
  static INVUL_SAVE = Intercessor.INVUL_SAVE;
  static HP_MAX = Intercessor.HP_MAX;
  static LD = Intercessor.LD;
  static OC = Intercessor.OC;
  static VALUE = Intercessor.VALUE;

  static RNG_WEAPON_CODES = ["bolt_rifle", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(RangeIntercessor.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(RangeIntercessor.CC_WEAPON_CODES);

  static UNIT_KEYWORDS = [...Intercessor.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = Intercessor.ICON;
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = Intercessor.BASE_SIZE; // Size of the base
  static ICON_SCALE = Intercessor.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, RangeIntercessor.HP_MAX, startPos);
  }
}
