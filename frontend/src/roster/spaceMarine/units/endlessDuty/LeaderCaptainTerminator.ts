import { getWeapons } from "../../armory";
import { LeaderEliteMeleeElite } from "../../classes/LeaderEliteMeleeElite";
import { CaptainTerminatorRelicFistCombi } from "../CaptainTerminatorRelicFistCombi";

export class LeaderCaptainTerminator extends LeaderEliteMeleeElite {
  static NAME = "LeaderCaptainTerminator";
  static DISPLAY_NAME = "Captain Terminator";
  static STARTER_LOADOUT_ID = "captain_terminator_starter";

  // BASE (combat profile)
  static MOVE = CaptainTerminatorRelicFistCombi.MOVE;
  static T = CaptainTerminatorRelicFistCombi.T;
  static ARMOR_SAVE = CaptainTerminatorRelicFistCombi.ARMOR_SAVE;
  static INVUL_SAVE = CaptainTerminatorRelicFistCombi.INVUL_SAVE;
  static HP_MAX = CaptainTerminatorRelicFistCombi.HP_MAX;
  static LD = CaptainTerminatorRelicFistCombi.LD;
  static OC = CaptainTerminatorRelicFistCombi.OC;
  static VALUE = CaptainTerminatorRelicFistCombi.VALUE;

  // Runtime default ED loadout; ED runtime can override with selected loadout.
  // Must match config/endless_duty/leader_evolution.json STARTER_LOADOUT_ID.
  static CC_WEAPON_CODES = ["relic_weapon_captain"];
  static CC_WEAPONS = getWeapons(LeaderCaptainTerminator.CC_WEAPON_CODES);
  static RNG_WEAPON_CODES = ["storm_bolter_captain"];
  static RNG_WEAPONS = getWeapons(LeaderCaptainTerminator.RNG_WEAPON_CODES);

  static UNIT_RULES = [{ ruleId: "reroll_charge", displayName: "Unstoppable Valour" }];
  static RULES_STATUS = { reroll_charge: 2 };
  static UNIT_KEYWORDS = [...CaptainTerminatorRelicFistCombi.UNIT_KEYWORDS, { keywordId: "endless_duty" }];

  static ICON = "/icons/CaptainTerminatorRelicFistCombi.webp";
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = CaptainTerminatorRelicFistCombi.BASE_SIZE; // Size of the base
  static ICON_SCALE = CaptainTerminatorRelicFistCombi.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, LeaderCaptainTerminator.HP_MAX, startPos);
  }
}
