export declare const REWARDS_RANGED: {
    move_close: number;
    move_away: number;
    move_to_safe: number;
    move_to_rng: number;
    move_to_charge: number;
    move_to_rng_charge: number;
    ranged_attack: number;
    enemy_killed_r: number;
    enemy_killed_lowests_hp_r: number;
    enemy_killed_no_overkill_r: number;
    charge_success: number;
    being_charged: number;
    attack: number;
    enemy_killed_m: number;
    enemy_killed_lowests_hp_m: number;
    enemy_killed_no_overkill_m: number;
    loose_hp: number;
    killed_in_melee: number;
    win: number;
    lose: number;
    atk_wasted_r: number;
    atk_wasted_m: number;
    wait: number;
};
export declare class SpaceMarineRangedUnit {
    static FACTION: string;
    static TEAM_COLOR: number;
    name: string;
    hp: number;
    pos: [number, number];
    alive: boolean;
    constructor(name: string, hpMax: number, startPos: [number, number]);
    move(dx: number, dy: number, boardHeight: number, boardWidth: number, takenPositions: [number, number][]): void;
    takeDamage(amount: number): void;
    reset(pos: [number, number], hpMax: number): void;
    isAlive(): boolean;
}
