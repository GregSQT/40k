import { getWeapons } from "../../armory";
import { EliteMeleeElite } from "../../classes/EliteMeleeElite";
import { AssaultTerminator } from "../AssaultTerminator";

export class MeleeTerminator extends EliteMeleeElite {
  static NAME = "MeleeTerminator";
  static DISPLAY_NAME = "Terminator";
  static EVOLUTION_FILE = "melee_evolution.json";
  static PROFILE_NAME = "Terminator";
  static STARTER_LOADOUT_ID = "melee_terminator_starter";

  static MOVE = AssaultTerminator.MOVE;
  static T = AssaultTerminator.T;
  static ARMOR_SAVE = AssaultTerminator.ARMOR_SAVE;
  static INVUL_SAVE = AssaultTerminator.INVUL_SAVE;
  static HP_MAX = AssaultTerminator.HP_MAX;
  static LD = AssaultTerminator.LD;
  static OC = AssaultTerminator.OC;
  static VALUE = AssaultTerminator.VALUE;

  static RNG_WEAPON_CODES: string[] = [];
  static RNG_WEAPONS = getWeapons(MeleeTerminator.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["thunder_hammer_terminator"];
  static CC_WEAPONS = getWeapons(MeleeTerminator.CC_WEAPON_CODES);

  static UNIT_KEYWORDS = [...AssaultTerminator.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = AssaultTerminator.ICON;
  static ICON_SCALE = AssaultTerminator.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, MeleeTerminator.HP_MAX, startPos);
  }
}
