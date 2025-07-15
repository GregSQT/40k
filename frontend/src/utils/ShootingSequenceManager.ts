// frontend/src/utils/ShootingSequenceManager.ts
import { Unit, UnitId, SingleShotState } from '../types/game';

export interface SingleShotResult {
  hitRoll: number;
  hitSuccess: boolean;
  woundRoll?: number;
  woundSuccess?: boolean;
  saveRoll?: number;
  saveSuccess?: boolean;
  damageDealt: number;
}

export class SingleShotSequenceManager {
  private state: SingleShotState | null = null;
  private onStateChange: ((state: SingleShotState | null) => void) | null = null;
  private onShotComplete: ((result: SingleShotResult) => void) | null = null;
  private onAllShotsComplete: ((totalDamage: number) => void) | null = null;

  /**
   * Start a new shooting sequence for a unit
   */
  startShootingSequence(
    shooter: Unit,
    onStateChange: (state: SingleShotState | null) => void,
    onShotComplete: (result: SingleShotResult) => void,
    onAllShotsComplete: (totalDamage: number) => void
  ): void {
    console.log(`🎯 Starting shooting sequence for ${shooter.name}: ${shooter.SHOOT_LEFT || 0} shots remaining`);
    
    this.onStateChange = onStateChange;
    this.onShotComplete = onShotComplete;
    this.onAllShotsComplete = onAllShotsComplete;

    const shotsRemaining = shooter.SHOOT_LEFT || 0;
    if (shotsRemaining <= 0) {
      console.log(`❌ No shots remaining for ${shooter.name}`);
      this.completeAllShots(0);
      return;
    }

    this.state = {
      isActive: true,
      shooterId: shooter.id,
      targetId: null,
      currentShotNumber: (shooter.RNG_NB || 0) - shotsRemaining + 1,
      totalShots: shooter.RNG_NB || 0,
      shotsRemaining: shotsRemaining,
      isSelectingTarget: true,
      currentStep: 'target_selection',
      stepResults: {}
    };

    this.notifyStateChange();
  }

  /**
   * Select target for current shot
   */
  selectTarget(targetId: UnitId): void {
    if (!this.state || this.state.currentStep !== 'target_selection') {
      console.log('❌ Cannot select target - not in target selection phase');
      return;
    }

    console.log(`🎯 Shot ${this.state.currentShotNumber}/${this.state.totalShots}: Target selected (${targetId})`);
    
    this.state.targetId = targetId;
    this.state.isSelectingTarget = false;
    this.state.currentStep = 'hit_roll';
    
    this.notifyStateChange();
  }

  /**
   * Process hit roll for current shot
   */
  processHitRoll(shooter: Unit): void {
    if (!this.state || this.state.currentStep !== 'hit_roll') return;

    const hitRoll = this.rollD6();
    if (shooter.RNG_ATK === undefined) {
      throw new Error('shooter.RNG_ATK is required');
    }
    const hitTarget = shooter.RNG_ATK;
    const hitSuccess = hitRoll >= hitTarget;

    console.log(`🎲 Hit roll: ${hitRoll} (need ${hitTarget}+) = ${hitSuccess ? 'HIT' : 'MISS'}`);

    this.state.stepResults.hitRoll = hitRoll;
    this.state.stepResults.hitSuccess = hitSuccess;

    if (!hitSuccess) {
      // Miss - complete this shot with 0 damage
      this.completeSingleShot({ 
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
   * Process wound roll for current shot
   */
  processWoundRoll(shooter: Unit, target: Unit): void {
    if (!this.state || this.state.currentStep !== 'wound_roll') return;

    const woundRoll = this.rollD6();
    if (shooter.RNG_STR === undefined) {
      throw new Error('tshooter.RNG_STR is required');
    }
    if (target.T === undefined) {
      throw new Error('target.T is required');
    }
    const woundTarget = this.calculateWoundTarget(shooter.RNG_STR, target.T);
    const woundSuccess = woundRoll >= woundTarget;

    console.log(`🎲 Wound roll: ${woundRoll} (need ${woundTarget}+) = ${woundSuccess ? 'WOUND' : 'NO WOUND'}`);

    this.state.stepResults.woundRoll = woundRoll;
    this.state.stepResults.woundSuccess = woundSuccess;

    if (!woundSuccess) {
      // Failed to wound - complete shot with 0 damage
      this.completeSingleShot({
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
   * Process save roll for current shot
   */
  processSaveRoll(shooter: Unit, target: Unit): void {
    if (!this.state || this.state.currentStep !== 'save_roll') return;

    const saveRoll = this.rollD6();
    if (target.ARMOR_SAVE === undefined) {
      throw new Error('target.ARMOR_SAVE is required');
    }
    if (target.INVUL_SAVE === undefined) {
      throw new Error('target.INVUL_SAVE is required');
    }
    if (shooter.RNG_AP === undefined) {
      throw new Error('shooter.RNG_AP is required');
    }
    const saveTarget = this.calculateSaveTarget(
      target.ARMOR_SAVE,
      target.INVUL_SAVE,
      shooter.RNG_AP
    );
    const saveSuccess = saveRoll >= saveTarget;

    console.log(`🎲 Save roll: ${saveRoll} (need ${saveTarget}+) = ${saveSuccess ? 'SAVED' : 'FAILED'}`);

    this.state.stepResults.saveRoll = saveRoll;
    this.state.stepResults.saveSuccess = saveSuccess;

    const damageDealt = saveSuccess ? 0 : (shooter.RNG_DMG);
    
    this.state.currentStep = 'damage_application';
    this.state.stepResults.damageDealt = damageDealt;

    this.completeSingleShot({
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
   * Complete current shot and prepare for next
   */
  private completeSingleShot(result: SingleShotResult): void {
    if (!this.state) return;

    console.log(`💥 Shot ${this.state.currentShotNumber} complete: ${result.damageDealt} damage`);

    // Notify shot completion
    if (this.onShotComplete) {
      this.onShotComplete(result);
    }

    // Decrease shots remaining
    this.state.shotsRemaining--;

    if (this.state.shotsRemaining <= 0) {
      // All shots complete
      this.completeAllShots(result.damageDealt);
      return;
    }

    // Prepare next shot
    this.state.currentShotNumber++;
    this.state.targetId = null;
    this.state.isSelectingTarget = true;
    this.state.currentStep = 'target_selection';
    this.state.stepResults = {};

    console.log(`🔄 Next shot: ${this.state.currentShotNumber}/${this.state.totalShots} (${this.state.shotsRemaining} remaining)`);
    
    this.notifyStateChange();
  }

  /**
   * Complete entire shooting sequence
   */
  private completeAllShots(lastShotDamage: number): void {
    console.log('🎯 All shots completed for unit');
    
    if (this.onAllShotsComplete) {
      this.onAllShotsComplete(lastShotDamage);
    }

    this.state = null;
    this.notifyStateChange();
  }

  /**
   * Cancel current shooting sequence
   */
  cancelSequence(): void {
    this.state = null;
    this.onStateChange = null;
    this.onShotComplete = null;
    this.onAllShotsComplete = null;
    this.notifyStateChange();
  }

  /**
   * Get current state
   */
  getState(): SingleShotState | null {
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
export const singleShotSequenceManager = new SingleShotSequenceManager();