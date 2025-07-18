// frontend/src/utils/CombatSequenceManager.ts
import { Unit, UnitId, SingleAttackState } from '../types/game';

export interface SingleAttackResult {
  hitRoll: number;
  hitSuccess: boolean;
  woundRoll?: number;
  woundSuccess?: boolean;
  saveRoll?: number;
  saveSuccess?: boolean;
  damageDealt: number;
}

export class SingleAttackSequenceManager {
  private state: SingleAttackState | null = null;
  private onStateChange: ((state: SingleAttackState | null) => void) | null = null;
  private onAttackComplete: ((result: SingleAttackResult) => void) | null = null;
  private onAllAttacksComplete: ((totalDamage: number) => void) | null = null;

  /**
   * Start a new combat sequence for a unit
   */
  startCombatSequence(
    attacker: Unit,
    onStateChange: (state: SingleAttackState | null) => void,
    onAttackComplete: (result: SingleAttackResult) => void,
    onAllAttacksComplete: (totalDamage: number) => void
  ): void {
    console.log(`⚔️ Starting combat sequence for ${attacker.name}: ${attacker.ATTACK_LEFT || 0} attacks remaining`);
    
    this.onStateChange = onStateChange;
    this.onAttackComplete = onAttackComplete;
    this.onAllAttacksComplete = onAllAttacksComplete;

    const attacksRemaining = attacker.ATTACK_LEFT || 0;
    if (attacksRemaining <= 0) {
      console.log(`❌ No attacks remaining for ${attacker.name}`);
      this.completeAllAttacks(0);
      return;
    }

    this.state = {
      isActive: true,
      attackerId: attacker.id,
      targetId: null,
      currentAttackNumber: (attacker.CC_NB || 0) - attacksRemaining + 1,
      totalAttacks: attacker.CC_NB || 0,
      attacksRemaining: attacksRemaining,
      isSelectingTarget: true,
      currentStep: 'target_selection',
      stepResults: {}
    };

    this.notifyStateChange();
  }

  /**
   * Select target for current attack
   */
  selectTarget(targetId: UnitId): void {
    if (!this.state || this.state.currentStep !== 'target_selection') {
      console.log('❌ Cannot select target - not in target selection phase');
      return;
    }

    console.log(`⚔️ Attack ${this.state.currentAttackNumber}/${this.state.totalAttacks}: Target selected (${targetId})`);
    
    this.state.targetId = targetId;
    this.state.isSelectingTarget = false;
    this.state.currentStep = 'hit_roll';
    
    this.notifyStateChange();
  }

  /**
   * Process hit roll for current attack
   */
  processHitRoll(attacker: Unit): void {
    if (!this.state || this.state.currentStep !== 'hit_roll') return;

    const hitRoll = this.rollD6();
    if (attacker.CC_ATK === undefined) {
      throw new Error('attacker.CC_ATK is required');
    }
    const hitTarget = attacker.CC_ATK;
    const hitSuccess = hitRoll >= hitTarget;

    console.log(`🎲 Hit roll: ${hitRoll} (need ${hitTarget}+) = ${hitSuccess ? 'HIT' : 'MISS'}`);

    this.state.stepResults.hitRoll = hitRoll;
    this.state.stepResults.hitSuccess = hitSuccess;

    if (!hitSuccess) {
      // Miss - no wound roll needed
      this.completeSingleAttack({
        hitRoll,
        hitSuccess: false,
        damageDealt: 0
      });
      return;
    }

    this.state.currentStep = 'wound_roll';
    this.notifyStateChange();
  }

  /**
   * Process wound roll for current attack
   */
  processWoundRoll(attacker: Unit, target: Unit): void {
    if (!this.state || this.state.currentStep !== 'wound_roll') return;

    const woundRoll = this.rollD6();
    if (attacker.CC_STR === undefined) {
      throw new Error('attacker.CC_STR is required');
    }
    if (target.T === undefined) {
      throw new Error('target.T is required');
    }
    const woundTarget = this.calculateWoundTarget(attacker.CC_STR, target.T);
    const woundSuccess = woundRoll >= woundTarget;

    console.log(`🎲 Wound roll: ${woundRoll} (need ${woundTarget}+) = ${woundSuccess ? 'WOUND' : 'NO WOUND'}`);

    this.state.stepResults.woundRoll = woundRoll;
    this.state.stepResults.woundSuccess = woundSuccess;

    if (!woundSuccess) {
      // No wound - no save roll needed
      this.completeSingleAttack({
        hitRoll: this.state.stepResults.hitRoll!,
        hitSuccess: true,
        woundRoll,
        woundSuccess: false,
        damageDealt: 0
      });
      return;
    }

    this.state.currentStep = 'save_roll';
    this.notifyStateChange();
  }

  /**
   * Process save roll for current attack
   */
  processSaveRoll(attacker: Unit, target: Unit): void {
    if (!this.state || this.state.currentStep !== 'save_roll') return;

    const saveRoll = this.rollD6();
    if (target.ARMOR_SAVE === undefined) {
      throw new Error('target.ARMOR_SAVE is required');
    }
    if (attacker.CC_AP === undefined) {
      throw new Error('attacker.CC_AP is required');
    }
    const saveTarget = this.calculateSaveTarget(
      target.ARMOR_SAVE, 
      target.INVUL_SAVE || 0, 
      attacker.CC_AP
    );
    const saveSuccess = saveRoll >= saveTarget;

    console.log(`🎲 Save roll: ${saveRoll} (need ${saveTarget}+) = ${saveSuccess ? 'SAVED' : 'FAILED'}`);

    this.state.stepResults.saveRoll = saveRoll;
    this.state.stepResults.saveSuccess = saveSuccess;

    const damageDealt = saveSuccess ? 0 : (attacker.CC_DMG || 1);
    
    this.state.currentStep = 'damage_application';
    this.state.stepResults.damageDealt = damageDealt;

    this.completeSingleAttack({
      hitRoll: this.state.stepResults.hitRoll!,
      hitSuccess: true,
      woundRoll: this.state.stepResults.woundRoll!,
      woundSuccess: true,
      saveRoll,
      saveSuccess,
      damageDealt
    });
  }

  /**
   * Complete current attack and prepare for next
   */
  private completeSingleAttack(result: SingleAttackResult): void {
    if (!this.state) return;

    console.log(`💥 Attack ${this.state.currentAttackNumber} complete: ${result.damageDealt} damage`);

    // Notify attack completion
    if (this.onAttackComplete) {
      this.onAttackComplete(result);
    }

    // Decrease attacks remaining
    this.state.attacksRemaining--;

    if (this.state.attacksRemaining <= 0) {
      // All attacks complete
      this.completeAllAttacks(result.damageDealt);
      return;
    }

    // Prepare next attack
    this.state.currentAttackNumber++;
    this.state.targetId = null;
    this.state.isSelectingTarget = true;
    this.state.currentStep = 'target_selection';
    this.state.stepResults = {};

    console.log(`🔄 Next attack: ${this.state.currentAttackNumber}/${this.state.totalAttacks} (${this.state.attacksRemaining} remaining)`);
    
    this.notifyStateChange();
  }

  /**
   * Complete entire combat sequence
   */
  private completeAllAttacks(lastAttackDamage: number): void {
    console.log('⚔️ All attacks completed for unit');
    
    if (this.onAllAttacksComplete) {
      this.onAllAttacksComplete(lastAttackDamage);
    }

    this.state = null;
    this.notifyStateChange();
  }

  /**
   * Cancel current combat sequence
   */
  cancelSequence(): void {
    this.state = null;
    this.onStateChange = null;
    this.onAttackComplete = null;
    this.onAllAttacksComplete = null;
    this.notifyStateChange();
  }

  /**
   * Get current state
   */
  getState(): SingleAttackState | null {
    return this.state;
  }

  /**
   * Roll a D6
   */
  private rollD6(): number {
    return Math.floor(Math.random() * 6) + 1;
  }

  /**
   * Calculate wound target based on strength vs toughness
   */
  private calculateWoundTarget(strength: number, toughness: number): number {
    if (strength >= toughness * 2) return 2; // S >= 2*T: wound on 2+
    if (strength > toughness) return 3;       // S > T: wound on 3+
    if (strength === toughness) return 4;     // S = T: wound on 4+
    if (strength < toughness) return 5;       // S < T: wound on 5+
    return 6; // S <= T/2: wound on 6+
  }

  /**
   * Calculate save target accounting for AP and invulnerable saves
   */
  private calculateSaveTarget(armorSave: number, invulSave: number, armorPenetration: number): number {
    const modifiedArmor = armorSave + armorPenetration;
    
    // Use invulnerable save if it's better than modified armor save (and invul > 0)
    if (invulSave > 0 && invulSave < modifiedArmor) {
      return invulSave;
    }
    
    return modifiedArmor;
  }

  /**
   * Notify state change to subscribers
   */
  private notifyStateChange(): void {
    if (this.onStateChange) {
      this.onStateChange(this.state);
    }
  }
}

// Export singleton instance
export const singleAttackSequenceManager = new SingleAttackSequenceManager();