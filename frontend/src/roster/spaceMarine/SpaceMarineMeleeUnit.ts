// frontend/src/roster/spaceMarine/SpaceMarineMeleeUnit.ts

export const REWARDS_MELEE = {
  // Phase : Movement
  move_close: 0.2, // for moving closer to an enemy unit
  move_away: -0.6, // for moving away from an enemy unit
  move_to_safe: 0.2, // for moving to a position where the unit is not in range of any enemy unit
  move_to_rng: 0.4, // for moving to a position where the unit can attack an enemy at its maximum RNG_RNG distance
  move_to_charge: 0.6, // for moving to a position where the unit can charge an enemy at its maximum MOVE distance
  move_to_rng_charge: 0.8, // for moving to a position where the unit can shoot and charge an enemy at its maximum RNG_RNG or MOVE distance (taking the lowest)

  // Phase : Shooting
  ranged_attack: 0.2, //for each point of damage to any enemy
  enemy_killed_r: 0.4, //for each enemy killed
  enemy_killed_lowests_hp_r: 0.6, //for killing the lowest-HP enemy on the board.
  enemy_killed_no_overkill_r: 0.8, //for Killing an enemy unit having its HP >= RNG_DMG at the activation

  // Phase : Charge
  charge_success: 0.8, //for successfully charging an enemy unit
  being_charged: -0.4, // for being charged by any enemy

  // Phase : Melee
  attack: 0.4, //for each point of damage to any enemy in melee phase
  enemy_killed_m: 0.4, //for each enemy killed
  enemy_killed_lowests_hp_m: 0.6, //for killing the lowest-HP enemy on the board.
  enemy_killed_no_overkill_m: 0.8, //for Killing an enemy unit having its HP >= RNG_DMG at the activation
  loose_hp: -0.4, //for losing HP during the opponent’s melee/charge phase.
  killed_in_melee: -0.8, //for being killed in melee phase.

  // Various
  win: 1.0, //for winning the game
  lose: -1.0, //for losing the game
  atk_wasted_r: -0.8, // for wasting an attack (no enemy in range or no enemy attacked)
  atk_wasted_m: -0.8, // for wasting a melee attack (no enemy in range or no enemy attacked) 
  wait: -0.9 // for waiting without any action
};

export class SpaceMarineMeleeUnit {
  static FACTION = "Space Marines";
  static TEAM_COLOR = 0x0078ff;     // Example: blue

  

  name: string;
  hp: number;
  pos: [number, number];
  alive: boolean;

  constructor(name: string, hpMax: number, startPos: [number, number]) {
    this.name = name;
    this.hp = hpMax;
    this.pos = [...startPos];
    this.alive = true;
  }

  move(dx: number, dy: number, boardHeight: number, boardWidth: number, takenPositions: [number, number][]) {
    const newX = this.pos[0] + dx;
    const newY = this.pos[1] + dy;
    if (
      newX >= 0 && newX < boardHeight &&
      newY >= 0 && newY < boardWidth &&
      !takenPositions.some(([x, y]) => x === newX && y === newY)
    ) {
      this.pos = [newX, newY];
    }
  }

  takeDamage(amount: number) {
    this.hp -= amount;
    if (this.hp <= 0) {
      this.hp = 0;
      this.alive = false;
    }
  }

  reset(pos: [number, number], hpMax: number) {
    this.hp = hpMax;
    this.pos = [...pos];
    this.alive = true;
  }

  isAlive() {
    return this.hp > 0;
  }
}
