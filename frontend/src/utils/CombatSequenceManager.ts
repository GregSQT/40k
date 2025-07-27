// frontend/src/utils/CombatSequenceManager.ts
import { Unit, UnitId, SingleAttackState } from '../types/game';
import { rollD6, calculateWoundTarget, calculateSaveTarget } from '../../../shared/gameRules';

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
    
    this.onStateChange = onStateChange;
    this.onAttackComplete = onAttackComplete;
    this.onAllAttacksComplete = onAllAttacksComplete;

    const attacksRemaining = attacker.ATTACK_LEFT || 0;
    if (attacksRemaining <= 0) {
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
      return;
    }
    
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

    const hitRoll = rollD6();
    if (attacker.CC_ATK === undefined) {
      throw new Error('attacker.CC_ATK is required');
    }
    const hitTarget = attacker.CC_ATK;
    const hitSuccess = hitRoll >= hitTarget;
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

    const woundRoll = rollD6();
    if (attacker.CC_STR === undefined) {
      throw new Error('attacker.CC_STR is required');
    }
    if (target.T === undefined) {
      throw new Error('target.T is required');
    }
    const woundTarget = calculateWoundTarget(attacker.CC_STR, target.T);
    const woundSuccess = woundRoll >= woundTarget;
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

    const saveRoll = rollD6();
    if (target.ARMOR_SAVE === undefined) {
      throw new Error('target.ARMOR_SAVE is required');
    }
    if (attacker.CC_AP === undefined) {
      throw new Error('attacker.CC_AP is required');
    }
    const saveTarget = calculateSaveTarget(
      target.ARMOR_SAVE, 
      target.INVUL_SAVE || 0, 
      attacker.CC_AP
    );
    const saveSuccess = saveRoll >= saveTarget;
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
    
    this.notifyStateChange();
  }

  /**
   * Complete entire combat sequence
   */
  private completeAllAttacks(lastAttackDamage: number): void {
    
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

  // rollD6 method removed - now using shared function

  // calculateWoundTarget method removed - now using shared function

  // calculateSaveTarget method removed - now using shared function

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