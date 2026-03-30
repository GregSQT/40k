import { getWeapons } from "../../armory";
import { TroopRangeSwarm } from "../../classes/TroopRangeSwarm";
import { SternguardVeteranBoltRifle } from "../SternguardVeteranBoltRifle";

export class RangeSternguard extends TroopRangeSwarm {
  static NAME = "RangeSternguard";
  static DISPLAY_NAME = "Sternguard";
  static EVOLUTION_FILE = "range_evolution.json";
  static PROFILE_NAME = "Sternguard";
  static STARTER_LOADOUT_ID = "range_sternguard_starter";

  static MOVE = SternguardVeteranBoltRifle.MOVE;
  static T = SternguardVeteranBoltRifle.T;
  static ARMOR_SAVE = SternguardVeteranBoltRifle.ARMOR_SAVE;
  static INVUL_SAVE = SternguardVeteranBoltRifle.INVUL_SAVE;
  static HP_MAX = SternguardVeteranBoltRifle.HP_MAX;
  static LD = SternguardVeteranBoltRifle.LD;
  static OC = SternguardVeteranBoltRifle.OC;
  static VALUE = SternguardVeteranBoltRifle.VALUE;

  static RNG_WEAPON_CODES = ["sternguard_bolt_rifle", "sternguard_bolt_pistol"];
  static RNG_WEAPONS = getWeapons(RangeSternguard.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(RangeSternguard.CC_WEAPON_CODES);

  static UNIT_KEYWORDS = [...SternguardVeteranBoltRifle.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = SternguardVeteranBoltRifle.ICON;
  static ICON_SCALE = SternguardVeteranBoltRifle.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, RangeSternguard.HP_MAX, startPos);
  }
}
