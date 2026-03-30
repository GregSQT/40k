import { getWeapons } from "../../armory";
import { LeaderEliteMeleeElite } from "../../classes/LeaderEliteMeleeElite";
import { LieutenantPowerFistPlasmaPistol } from "../LieutenantPowerFistPlasmaPistol";

export class LeaderLieutenant extends LeaderEliteMeleeElite {
  static NAME = "LeaderLieutenant";
  static DISPLAY_NAME = "Lieutenant";
  static STARTER_LOADOUT_ID = "lieutenant_starter";

  // BASE (combat profile)
  static MOVE = LieutenantPowerFistPlasmaPistol.MOVE;
  static T = LieutenantPowerFistPlasmaPistol.T;
  static ARMOR_SAVE = LieutenantPowerFistPlasmaPistol.ARMOR_SAVE;
  static INVUL_SAVE = LieutenantPowerFistPlasmaPistol.INVUL_SAVE;
  static HP_MAX = LieutenantPowerFistPlasmaPistol.HP_MAX;
  static LD = LieutenantPowerFistPlasmaPistol.LD;
  static OC = LieutenantPowerFistPlasmaPistol.OC;
  static VALUE = LieutenantPowerFistPlasmaPistol.VALUE;

  // Runtime default ED loadout; ED runtime can override with selected loadout.
  // Must match config/endless_duty/leader_evolution.json STARTER_LOADOUT_ID.
  static CC_WEAPON_CODES = ["close_combat_weapon_lieutenant"];
  static CC_WEAPONS = getWeapons(LeaderLieutenant.CC_WEAPON_CODES);
  static RNG_WEAPON_CODES = ["master_crafted_bolter_lieutenant", "heavy_bolt_pistol_lieutenant"];
  static RNG_WEAPONS = getWeapons(LeaderLieutenant.RNG_WEAPON_CODES);

  static UNIT_RULES = [
    {
      ruleId: "target_priority",
      displayName: "Target Priority",
      grants_rule_ids: ["shoot_after_flee", "charge_after_flee"],
      usage: "and",
    },
  ];
  static RULES_STATUS = {
    target_priority: 2,
    shoot_after_flee: 2,
    charge_after_flee: 2,
  };
  static UNIT_KEYWORDS = [...LieutenantPowerFistPlasmaPistol.UNIT_KEYWORDS, { keywordId: "endless_duty" }];

  static ICON = "/icons/LieutenantPowerFistPlasmaPistol.webp";
  static ICON_SCALE = LieutenantPowerFistPlasmaPistol.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, LeaderLieutenant.HP_MAX, startPos);
  }
}
