// frontend/src/utils/ShootingSequenceManager.ts
import { Unit, UnitId, SingleShotState } from '../types/game';
import { rollD6, calculateWoundTarget, calculateSaveTarget } from '../../../shared/gameRules';

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
    
    this.onStateChange = onStateChange;
    this.onShotComplete = onShotComplete;
    this.onAllShotsComplete = onAllShotsComplete;

    const shotsRemaining = shooter.SHOOT_LEFT || 0;
    if (shotsRemaining <= 0) {
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
      return;
    }    
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

    const hitRoll = rollD6();
    if (shooter.RNG_ATK === undefined) {
      throw new Error('shooter.RNG_ATK is required');
    }
    const hitTarget = shooter.RNG_ATK;
    const hitSuccess = hitRoll >= hitTarget;

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

    const woundRoll = rollD6();
    if (shooter.RNG_STR === undefined) {
      throw new Error('shooter.RNG_STR is required');
    }
    if (target.T === undefined) {
      throw new Error('target.T is required');
    }
    const woundTarget = calculateWoundTarget(shooter.RNG_STR, target.T);
    const woundSuccess = woundRoll >= woundTarget;

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

    const saveRoll = rollD6();
    if (target.ARMOR_SAVE === undefined) {
      throw new Error('target.ARMOR_SAVE is required');
    }
    if (target.INVUL_SAVE === undefined) {
      throw new Error('target.INVUL_SAVE is required');
    }
    if (shooter.RNG_AP === undefined) {
      throw new Error('shooter.RNG_AP is required');
    }
    const saveTarget = calculateSaveTarget(
      target.ARMOR_SAVE,
      target.INVUL_SAVE,
      shooter.RNG_AP
    );
    const saveSuccess = saveRoll >= saveTarget;

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
    this.notifyStateChange();
  }

  /**
   * Complete entire shooting sequence
   */
  private completeAllShots(lastShotDamage: number): void {
    
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
export const singleShotSequenceManager = new SingleShotSequenceManager();