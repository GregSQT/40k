// frontend/src/roster/spaceMarine/SpaceMarineRangedUnit.ts

export class SpaceMarineRangedUnit {
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
