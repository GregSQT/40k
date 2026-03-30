import { getWeapons } from "../../armory";
import { LeaderEliteMeleeElite } from "../../classes/LeaderEliteMeleeElite";
import { IntercessorSergeant } from "../IntercessorSergeant";

/**
 * Endless Duty leader chassis.
 *
 * This class keeps combat stats aligned with IntercessorSergeant.
 * Loadout options and requisition costs are centralized in
 * config/endless_duty/leader_evolution.json.
 */
export class LeaderSergeant extends LeaderEliteMeleeElite {
  static NAME = "LeaderSergeant";
  static DISPLAY_NAME = "Sergeant";
  static STARTER_LOADOUT_ID = "sergeant_starter";

  // BASE (combat profile)
  static MOVE = IntercessorSergeant.MOVE;
  static T = IntercessorSergeant.T;
  static ARMOR_SAVE = IntercessorSergeant.ARMOR_SAVE;
  static INVUL_SAVE = IntercessorSergeant.INVUL_SAVE;
  static HP_MAX = IntercessorSergeant.HP_MAX;
  static LD = IntercessorSergeant.LD;
  static OC = IntercessorSergeant.OC;
  static VALUE = 18; // Combat value target for ED starting leader

  // Runtime default ED loadout; ED runtime can override with selected loadout.
  // Chosen default is distinct from IntercessorSergeant baseline:
  // close combat weapon + bolt rifle + bolt pistol.
  // Must match config/endless_duty/leader_evolution.json starter_loadout_id.
  static CC_WEAPON_CODES = ["close_combat_weapon"];
  static CC_WEAPONS = getWeapons(LeaderSergeant.CC_WEAPON_CODES);
  static RNG_WEAPON_CODES = ["bolt_rifle", "bolt_pistol"];
  static RNG_WEAPONS = getWeapons(LeaderSergeant.RNG_WEAPON_CODES);

  static UNIT_KEYWORDS = [
    { keywordId: "infantry" },
    { keywordId: "battleline" },
    { keywordId: "grenades" },
    { keywordId: "imperium" },
    { keywordId: "tacticus" },
    { keywordId: "intercessor squad" },
    { keywordId: "character" },
    { keywordId: "leader" },
    { keywordId: "endless_duty" },
  ];

  static ICON = "/icons/IntercessorSergeant.webp";
  static ICON_SCALE = IntercessorSergeant.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, LeaderSergeant.HP_MAX, startPos);
  }
}
