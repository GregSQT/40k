import { getWeapons } from "../../armory";
import { TroopMeleeTroop } from "../../classes/TroopMeleeTroop";
import { BladeguardVeteran } from "../BladeguardVeteran";

export class MeleeBladeguard extends TroopMeleeTroop {
  static NAME = "MeleeBladeguard";
  static DISPLAY_NAME = "Bladeguard";
  static EVOLUTION_FILE = "melee_evolution.json";
  static PROFILE_NAME = "Bladeguard";
  static STARTER_LOADOUT_ID = "melee_bladeguard_starter";

  static MOVE = BladeguardVeteran.MOVE;
  static T = BladeguardVeteran.T;
  static ARMOR_SAVE = BladeguardVeteran.ARMOR_SAVE;
  static INVUL_SAVE = BladeguardVeteran.INVUL_SAVE;
  static HP_MAX = BladeguardVeteran.HP_MAX;
  static LD = BladeguardVeteran.LD;
  static OC = BladeguardVeteran.OC;
  static VALUE = BladeguardVeteran.VALUE;

  static RNG_WEAPON_CODES = ["heavy_bolt_pistol"];
  static RNG_WEAPONS = getWeapons(MeleeBladeguard.RNG_WEAPON_CODES);
  static CC_WEAPON_CODES = ["master_crafted_power_weapon"];
  static CC_WEAPONS = getWeapons(MeleeBladeguard.CC_WEAPON_CODES);

  static UNIT_KEYWORDS = [...BladeguardVeteran.UNIT_KEYWORDS, { keywordId: "endless_duty" }];
  static ICON = BladeguardVeteran.ICON;
  static BASE_SHAPE = "round"; // Shape of the base
  static BASE_SIZE = BladeguardVeteran.BASE_SIZE; // Size of the base
  static ICON_SCALE = BladeguardVeteran.ICON_SCALE;

  constructor(name: string, startPos: [number, number]) {
    super(name, MeleeBladeguard.HP_MAX, startPos);
  }
}
