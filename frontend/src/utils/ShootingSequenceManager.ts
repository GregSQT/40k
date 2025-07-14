// frontend/src/utils/ShootingSequenceManager.ts
import { Unit } from '../types/game';
import { CombatStep, CombatResult, calculateWoundThreshold, createCombatSteps } from '../components/CombatLogComponent';

export interface ShootingSequenceState {
  isActive: boolean;
  currentStepIndex: number;
  combatResult: CombatResult;
  shooter: Unit;
  target: Unit;
}

export class ShootingSequenceManager {
  private state: ShootingSequenceState | null = null;
  private onStateChange: ((state: ShootingSequenceState | null) => void) | null = null;
  private onSequenceComplete: ((finalDamage: number) => void) | null = null;

  /**
   * Initialize a new shooting sequence
   */
  startSequence(
    shooter: Unit, 
    target: Unit, 
    onStateChange: (state: ShootingSequenceState | null) => void,
    onSequenceComplete: (finalDamage: number) => void
  ): void {
    console.log('🔥 SEQUENCE MANAGER CALLED');
    console.log('Shooter:', shooter);
    console.log('Target:', target);

    // Check what dice properties we actually have - individual logs
    console.log('🎯 Shooter dice properties:');
    console.log('  RNG_NB:', shooter.RNG_NB);
    console.log('  RNG_ATK:', shooter.RNG_ATK);
    console.log('  RNG_STR:', shooter.RNG_STR);
    console.log('  RNG_AP:', shooter.RNG_AP);
    console.log('  RNG_DMG:', shooter.RNG_DMG);

    console.log('🛡️ Target defense properties:');
    console.log('  T:', target.T);
    console.log('  ARMOR_SAVE:', target.ARMOR_SAVE);
    console.log('  INVUL_SAVE:', target.INVUL_SAVE);

    console.log('🔧 Setting initial state...');
    this.onStateChange = onStateChange;
    this.onSequenceComplete = onSequenceComplete;

    // Validate required unit stats - throw errors if missing
    if (!shooter.RNG_NB) throw new Error(`Missing RNG_NB for shooter ${shooter.name}`);
    if (!shooter.RNG_ATK) throw new Error(`Missing RNG_ATK for shooter ${shooter.name}`);
    if (!shooter.RNG_STR) throw new Error(`Missing RNG_STR for shooter ${shooter.name}`);
    if (!shooter.RNG_AP && shooter.RNG_AP !== 0) throw new Error(`Missing RNG_AP for shooter ${shooter.name}`);
    if (!shooter.RNG_DMG) throw new Error(`Missing RNG_DMG for shooter ${shooter.name}`);
    
    if (!target.T) throw new Error(`Missing T for target ${target.name}`);
    if (!target.ARMOR_SAVE) throw new Error(`Missing ARMOR_SAVE for target ${target.name}`);
    if (!target.INVUL_SAVE && target.INVUL_SAVE !== 0) throw new Error(`Missing INVUL_SAVE for target ${target.name}`);

    // Extract unit stats - all validated above
    const shots = shooter.RNG_NB;
    const strength = shooter.RNG_STR;
    const armorPenetration = shooter.RNG_AP;
    const damage = shooter.RNG_DMG;
    
    const toughness = target.T;
    const armorSave = target.ARMOR_SAVE;
    const invulSave = target.INVUL_SAVE;

    // All values are D6 thresholds
    const hitTarget = shooter.RNG_ATK;
    const woundTarget = calculateWoundThreshold(strength, toughness);
    
    // Calculate final save (best of armor or invul, modified by AP)
    const modifiedArmorSave = Math.max(2, armorSave + armorPenetration); // AP makes saves harder
    
    // Handle invulnerable saves: 0 means no invul save (impossible = 7+)
    const effectiveInvulSave = invulSave <= 0 ? 7 : invulSave;
    
    // Use the better save (lower number = easier save)
    const finalSaveTarget = Math.min(modifiedArmorSave, effectiveInvulSave);

    console.log(`🛡️ Save calculation: armor=${armorSave}, AP=${armorPenetration}, modified=${modifiedArmorSave}, invul=${invulSave}, effectiveInvul=${effectiveInvulSave}, final=${finalSaveTarget}`);

    // Create combat steps
    const steps = createCombatSteps(shots, hitTarget, woundTarget, finalSaveTarget);

    // Initialize combat result
    const combatResult: CombatResult = {
      totalShots: shots,
      hits: 0,
      wounds: 0,
      saves: 0,
      damageDealt: 0,
      steps: steps
    };

    // Set initial state
    this.state = {
      isActive: true,
      currentStepIndex: 2, // Start with hit rolls (shots and range are auto-complete)
      combatResult,
      shooter,
      target
    };

    this.updateCurrentStep();
    this.notifyStateChange();
  }

  /**
   * Process the next step in the sequence
   */
  nextStep(): void {
    if (!this.state) return;

    // Mark current step as complete
    if (this.state.currentStepIndex < this.state.combatResult.steps.length) {
      this.state.combatResult.steps[this.state.currentStepIndex].status = 'complete';
    }

    // Move to next step
    this.state.currentStepIndex++;

    if (this.state.currentStepIndex >= this.state.combatResult.steps.length) {
      // Sequence complete
      this.completeSequence();
      return;
    }

    this.updateCurrentStep();
    this.notifyStateChange();
  }

  /**
   * Get the current state
   */
  getState(): ShootingSequenceState | null {
    return this.state;
  }

  /**
   * Process dice rolls for the current step
   */
  processDiceRolls(rolls: number[]): void {
    if (!this.state) return;

    const currentStep = this.state.combatResult.steps[this.state.currentStepIndex];
    const targetValue = currentStep.targetValue;
    if (!targetValue) throw new Error(`Missing target value for step ${currentStep.step}`);
    const successes = rolls.filter(roll => roll >= targetValue).length;

    // Store roll results
    currentStep.diceRolls = rolls;
    currentStep.successes = successes;

    // Update combat result based on step type
    switch (currentStep.step) {
      case 'hit':
        this.state.combatResult.hits = successes;
        break;
      case 'wound':
        this.state.combatResult.wounds = successes;
        break;
      case 'save':
        this.state.combatResult.saves = successes;
        // Calculate final damage (wounds - successful saves)
        const unsavedWounds = this.state.combatResult.wounds - successes;
        this.state.combatResult.damageDealt = Math.max(0, unsavedWounds * (this.state.shooter.RNG_DMG));
        break;
    }

    this.notifyStateChange();
  }

  /**
   * Cancel the current sequence
   */
  cancelSequence(): void {
    this.state = null;
    this.notifyStateChange();
  }

  /**
   * Convert percentage (like 66%) to D6 threshold (like 4+)
   */
  private percentageToD6Threshold(percentage: number): number {
    if (percentage >= 83) return 2; // 83% = 2+
    if (percentage >= 67) return 3; // 67% = 3+
    if (percentage >= 50) return 4; // 50% = 4+
    if (percentage >= 33) return 5; // 33% = 5+
    if (percentage >= 17) return 6; // 17% = 6+
    return 7; // Impossible
  }

  /**
   * Update the current step status and auto-roll dice
   */
  private updateCurrentStep(): void {
    if (!this.state) return;

    // Set current step as active
    if (this.state.currentStepIndex < this.state.combatResult.steps.length) {
      const currentStep = this.state.combatResult.steps[this.state.currentStepIndex];
      currentStep.status = 'active';
      
      // Auto-roll dice for this step
      this.autoRollDiceForStep(currentStep);
    }

    // Skip non-dice steps automatically
    const currentStep = this.state.combatResult.steps[this.state.currentStepIndex];
    
    if (currentStep.step === 'damage') {
      // Auto-complete damage step
      currentStep.status = 'complete';
      this.state.currentStepIndex++;
      
      if (this.state.currentStepIndex >= this.state.combatResult.steps.length) {
        this.completeSequence();
        return;
      }
    }

    // Update step descriptions with current context
    this.updateStepDescriptions();
  }

  /**
   * Automatically roll dice for the current step
   */
  private autoRollDiceForStep(step: CombatStep): void {
    if (!this.state) return;

    let numberOfDice = 0;
    let targetValue = step.targetValue;

    // Determine number of dice based on step type
    switch (step.step) {
      case 'hit':
        numberOfDice = this.state.combatResult.totalShots;
        break;
      case 'wound':
        numberOfDice = this.state.combatResult.hits;
        break;
      case 'save':
        numberOfDice = this.state.combatResult.wounds;
        break;
      default:
        return; // No dice rolling needed
    }

    // Validate targetValue
    if (targetValue === undefined || targetValue === null) {
      console.error(`❌ Missing target value for step ${step.step}`);
      console.error('Step details:', step);
      console.error('State:', this.state);
      return;
    }

    console.log(`🎲 ${step.step.toUpperCase()} PHASE: Rolling ${numberOfDice} dice, need ${targetValue}+ to succeed`);

    // Handle 0 dice scenario - auto-complete with 0 successes
    if (numberOfDice === 0) {
      console.log(`🎲 No dice to roll for ${step.step} phase - auto-completing with 0 successes`);
      step.diceRolls = [];
      step.successes = 0;
      
      // Update combat result using processDiceRolls to ensure consistency
      this.processDiceRolls([]);

      // Auto-advance to next step immediately for 0 dice scenarios
      setTimeout(() => {
        this.nextStep();
      }, 500); // Shorter delay for skipped phases
      return;
    }

    // Roll all dice at once
    const rolls: number[] = [];
    for (let i = 0; i < numberOfDice; i++) {
      rolls.push(Math.floor(Math.random() * 6) + 1);
    }

    console.log(`🎲 Dice results: [${rolls.join(', ')}]`);

    // Count successes
    const successes = rolls.filter(roll => roll >= targetValue).length;
    console.log(`🎲 Successes: ${successes}/${numberOfDice} (needed ${targetValue}+)`);

    // Process the results immediately
    this.processDiceRolls(rolls);

    // Auto-advance to next step after a brief display delay
    setTimeout(() => {
      this.nextStep();
    }, 1500); // 1.5 second delay to show results
  }

  /**
   * Update step descriptions with current results
   */
  private updateStepDescriptions(): void {
    if (!this.state) return;

    const steps = this.state.combatResult.steps;
    const result = this.state.combatResult;

    // Update descriptions based on current progress
    if (result.hits > 0) {
      const woundStep = steps.find(s => s.step === 'wound');
      if (woundStep) {
        woundStep.description = `Rolling ${result.hits} dice to wound`;
      }
    }

    if (result.wounds > 0) {
      const saveStep = steps.find(s => s.step === 'save');
      if (saveStep) {
        saveStep.description = `Rolling ${result.wounds} armor saves`;
      }
    }

    if (result.damageDealt > 0) {
      const damageStep = steps.find(s => s.step === 'damage');
      if (damageStep) {
        damageStep.description = `${result.damageDealt} damage dealt!`;
      }
    }
  }

  /**
   * Complete the shooting sequence
   */
  private completeSequence(): void {
    if (!this.state) return;

    const finalDamage = this.state.combatResult.damageDealt;
    
    // Mark all steps as complete
    this.state.combatResult.steps.forEach(step => {
      step.status = 'complete';
    });

    // Store completion callback before clearing state
    const completionCallback = this.onSequenceComplete;
    
    // Clear state immediately to prevent multiple calls
    this.state = null;
    this.onSequenceComplete = null;
    this.onStateChange = null;
    
    this.notifyStateChange();

    // Notify completion after a brief delay
    setTimeout(() => {
      if (completionCallback) {
        completionCallback(finalDamage);
      }
    }, 2000);
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
export const shootingSequenceManager = new ShootingSequenceManager();