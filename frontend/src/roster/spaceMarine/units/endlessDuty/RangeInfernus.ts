import { getWeapons } from "../../armory";
import { TroopRangeSwarm } from "../../classes/TroopRangeSwarm";
import { Infernus } from "../Infernus";

export class RangeInfernus extends TroopRangeSwarm {
  static NAME = "RangeInfernus";
  static DISPLAY_NAME = "Infernus";
  static EVOLUTION_FILE = "range_evolution.json";
  static PROFILE_NAME = "Infernus";
  static STARTER_LOADOUT_ID = "range_infernus_starter";

  static MOVE = Infernus.MOVE;
  static T = Infernus.T;
  static ARMOR_SAVE = Infernus.ARMOR_SAVE;
  static INVUL_SAVE = Infernus.INVUL_SAVE;
  static HP_MAX = Infernus.HP_MAX;
  static LD = Infernus.LD;
  static OC = Infernus.OC;
  static VALUE = Infernus.VALUE;

  static RNG_WEAPON_CODES = ["pyreblast", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(RangeInfernus.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(RangeInfernus.CC_WEAPON_CODES);

  static UNIT_KEYWORDS = [...Infernus.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = Infernus.ICON;
  static ICON_SCALE = Infernus.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, RangeInfernus.HP_MAX, startPos);
  }
}
