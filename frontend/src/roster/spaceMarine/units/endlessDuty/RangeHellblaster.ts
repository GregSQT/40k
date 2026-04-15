import { getWeapons } from "../../armory";
import { TroopRangeElite } from "../../classes/TroopRangeElite";
import { Hellblaster } from "../Hellblaster";

export class RangeHellblaster extends TroopRangeElite {
  static NAME = "RangeHellblaster";
  static DISPLAY_NAME = "Hellblaster";
  static EVOLUTION_FILE = "range_evolution.json";
  static PROFILE_NAME = "Hellblaster";
  static STARTER_LOADOUT_ID = "range_hellblaster_starter";

  static MOVE = Hellblaster.MOVE;
  static T = Hellblaster.T;
  static ARMOR_SAVE = Hellblaster.ARMOR_SAVE;
  static INVUL_SAVE = Hellblaster.INVUL_SAVE;
  static HP_MAX = Hellblaster.HP_MAX;
  static LD = Hellblaster.LD;
  static OC = Hellblaster.OC;
  static VALUE = Hellblaster.VALUE;

  static RNG_WEAPON_CODES = ["plasma_incinerator_standard", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(RangeHellblaster.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(RangeHellblaster.CC_WEAPON_CODES);

  static UNIT_RULES: [] = [];
  static UNIT_KEYWORDS = [...Hellblaster.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = Hellblaster.ICON;
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = Hellblaster.BASE_SIZE; // Size of the base
  static ICON_SCALE = Hellblaster.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, RangeHellblaster.HP_MAX, startPos);
  }
}
