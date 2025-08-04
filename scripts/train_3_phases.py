#!/usr/bin/env python3
"""
🎯 3-Phase Progressive AI Training Script
Implements the complete training curriculum for Warhammer 40K AI agents.

Phase 1: Individual Agent Specialization (30% - 300 episodes)
Phase 2: Cross-Faction Tactical Learning (40% - 500 episodes) 
Phase 3: Full Composition Mastery (30% - 400 episodes)

Usage:
    python scripts/train_3_phases.py
    python scripts/train_3_phases.py --max-concurrent 6
    python scripts/train_3_phases.py --total-episodes 1500

# Run complete 3-phase training (default 1200 episodes)
python scripts/train_3_phases.py

# Custom episode count and concurrency
python scripts/train_3_phases.py --total-episodes 100

# Run only a specific phase
python scripts/train_3_phases.py --phase 2  # Cross-faction learning only

# Show training plan without executing
python scripts/train_3_phases.py --plan-only


"""

import os
import sys
import time
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from config_loader import get_config_loader


class ThreePhaseTrainingManager:
    """Manages the complete 3-phase training curriculum."""
    
    def __init__(self, total_episodes=1200, max_concurrent=4):
        self.total_episodes = total_episodes
        self.max_concurrent = max_concurrent
        self.config = get_config_loader()
        
        # Phase distribution (episodes)
        self.phase_1_episodes = int(total_episodes * 0.30)  # 30% - Individual specialization
        self.phase_2_episodes = int(total_episodes * 0.40)  # 40% - Cross-faction learning
        self.phase_3_episodes = int(total_episodes * 0.30)  # 30% - Full composition mastery
        
        # Training configurations for each phase
        self.phase_configs = {
            1: {
                'name': 'Individual Agent Specialization',
                'training_config': 'conservative',
                'rewards_config': 'default',
                'episodes': self.phase_1_episodes,
                'phase': 'solo',
                'description': 'Each agent learns core role fundamentals'
            },
            2: {
                'name': 'Cross-Faction Tactical Learning', 
                'training_config': 'default',
                'rewards_config': 'default',
                'episodes': self.phase_2_episodes,
                'phase': 'cross_faction',
                'description': 'Learn to fight different factions with smaller forces'
            },
            3: {
                'name': 'Full Composition Mastery',
                'training_config': 'aggressive',
                'rewards_config': 'default', 
                'episodes': self.phase_3_episodes,
                'phase': 'full_composition',
                'description': 'Master your exact team composition'
            }
        }
        
        # Expected duration estimates (in hours)
        self.phase_durations = {
            1: '2-3 hours',
            2: '4-6 hours', 
            3: '3-4 hours'
        }
        
        self.start_time = None
        self.phase_results = {}

    def print_training_plan(self):
        """Display the complete training plan."""
        print("🎯 W40K AI 3-Phase Progressive Training Plan")
        print("=" * 80)
        print(f"📊 Total Episodes: {self.total_episodes:,}")
        print(f"🔄 Max Concurrent Sessions: {self.max_concurrent}")
        print(f"⏱️  Estimated Total Duration: 9-13 hours")
        print()
        
        for phase_num, config in self.phase_configs.items():
            percentage = (config['episodes'] / self.total_episodes) * 100
            print(f"📋 Phase {phase_num}: {config['name']} ({percentage:.0f}% - {config['episodes']} episodes)")
            print(f"🎯 Purpose: {config['description']}")
            print(f"⚙️  Config: {config['training_config']} training, {config['rewards_config']} rewards")
            print(f"⏱️  Duration: ~{self.phase_durations[phase_num]}")
            
            # Show what happens in each phase
            if phase_num == 1:
                print("📊 What Happens:")
                print("   • SpaceMarine agents train with solo scenarios (same vs same)")
                print("   • Tyranid agents train with solo scenarios (same vs same)")
                print("   • Focus: Basic unit movement, shooting, charge mechanics")
                print("   • Reward: Simplified rewards for easier learning")
            elif phase_num == 2:
                print("📊 What Happens:")
                print("   • Cross-faction matchups (Marines vs Tyranids)")
                print("   • Mixed role training (Melee vs Ranged)")
                print("   • Elite unit duels (Captain vs Carnifex)")
                print("   • Focus: Cross-faction combat, role synergy, tactical positioning")
                print("   • Reward: Balanced tactical rewards")
            elif phase_num == 3:
                print("📊 What Happens:")
                print("   • Full team compositions (9v9 battles)")
                print("   • Marines: 2 Intercessors + 2 Assault + 1 Captain")
                print("   • Tyranids: 4 Termagants + 4 Hormagaunts + 1 Carnifex")
                print("   • Focus: Team coordination, complex tactics, win optimization")
                print("   • Reward: Full sophisticated reward system")
            
            print("-" * 80)
            print()

    def run_training_phase(self, phase_num: int) -> bool:
        """Execute a single training phase."""
        config = self.phase_configs[phase_num]
        
        print(f"🚀 Starting Phase {phase_num}: {config['name']}")
        print(f"📊 Episodes: {config['episodes']:,}")
        print(f"⚙️  Training Config: {config['training_config']}")
        print(f"🎯 Phase Type: {config['phase']}")
        print(f"⏱️  Expected Duration: {self.phase_durations[phase_num]}")
        print()
        
        # Build command
        train_command = [
            sys.executable, 
            str(project_root / "ai" / "train.py"),
            "--orchestrate",
            "--training-phase", config['phase'],
            "--training-config", config['training_config'],
            "--rewards-config", config['rewards_config'],
            "--total-episodes", str(config['episodes']),
            "--max-concurrent", str(self.max_concurrent)
        ]
        
        print(f"🔧 Command: {' '.join(train_command)}")
        print()
        
        # Record phase start time
        phase_start = time.time()
        
        try:
            # Execute training phase
            result = subprocess.run(
                train_command,
                cwd=str(project_root),
                check=True,
                capture_output=False,  # Show output in real-time
                text=True
            )
            
            # Record results
            phase_duration = time.time() - phase_start
            self.phase_results[phase_num] = {
                'success': True,
                'duration_seconds': phase_duration,
                'duration_hours': phase_duration / 3600,
                'episodes': config['episodes'],
                'return_code': result.returncode
            }
            
            print(f"✅ Phase {phase_num} completed successfully!")
            print(f"⏱️  Duration: {phase_duration / 3600:.1f} hours")
            print()
            
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"❌ Phase {phase_num} failed with return code: {e.returncode}")
            
            self.phase_results[phase_num] = {
                'success': False,
                'duration_seconds': time.time() - phase_start,
                'episodes': config['episodes'],
                'return_code': e.returncode,
                'error': str(e)
            }
            
            return False
        
        except KeyboardInterrupt:
            print(f"🛑 Phase {phase_num} interrupted by user")
            
            self.phase_results[phase_num] = {
                'success': False,
                'duration_seconds': time.time() - phase_start,
                'episodes': config['episodes'],
                'interrupted': True
            }
            
            return False

    def print_phase_summary(self):
        """Print summary of completed phases."""
        if not self.phase_results:
            return
            
        print("📊 Training Phase Summary")
        print("=" * 60)
        
        total_duration = 0
        successful_phases = 0
        total_episodes_completed = 0
        
        for phase_num in sorted(self.phase_results.keys()):
            result = self.phase_results[phase_num]
            config = self.phase_configs[phase_num]
            
            status = "✅ SUCCESS" if result['success'] else "❌ FAILED"
            duration_hours = result.get('duration_hours', result['duration_seconds'] / 3600)
            
            print(f"Phase {phase_num}: {config['name']}")
            print(f"  Status: {status}")
            print(f"  Episodes: {result['episodes']:,}")
            print(f"  Duration: {duration_hours:.1f} hours")
            
            if result['success']:
                successful_phases += 1
                total_episodes_completed += result['episodes']
            
            total_duration += duration_hours
            print()
        
        print(f"📈 Overall Results:")
        print(f"  Successful Phases: {successful_phases}/3")
        print(f"  Total Episodes: {total_episodes_completed:,}")
        print(f"  Total Duration: {total_duration:.1f} hours")
        
        # Training completion rate
        completion_rate = (total_episodes_completed / self.total_episodes) * 100
        print(f"  Completion Rate: {completion_rate:.1f}%")
        
        if successful_phases == 3:
            print("🎉 All phases completed successfully!")
            print("🤖 Your AI agents are now fully trained and ready for battle!")
        else:
            print("⚠️  Some phases failed. Consider re-running failed phases.")

    def run_complete_training(self) -> bool:
        """Execute the complete 3-phase training curriculum."""
        self.start_time = time.time()
        
        print("🎯 Starting Complete 3-Phase AI Training Curriculum")
        print(f"🕐 Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Execute each phase in sequence
        for phase_num in [1, 2, 3]:
            success = self.run_training_phase(phase_num)
            
            if not success:
                print(f"🛑 Training stopped due to Phase {phase_num} failure")
                break
                
            # Brief pause between phases
            if phase_num < 3:
                print("⏸️  Brief pause between phases...")
                time.sleep(5)
        
        # Print final summary
        total_duration = time.time() - self.start_time
        print("🏁 3-Phase Training Complete!")
        print(f"🕐 End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"⏱️  Total Duration: {total_duration / 3600:.1f} hours")
        print()
        
        self.print_phase_summary()
        
        # Check if all phases succeeded
        all_succeeded = all(result.get('success', False) for result in self.phase_results.values())
        return all_succeeded

    def run_single_phase(self, phase_num: int) -> bool:
        """Run a single specific phase."""
        if phase_num not in self.phase_configs:
            print(f"❌ Invalid phase number: {phase_num}. Must be 1, 2, or 3.")
            return False
            
        print(f"🎯 Running Single Phase: {phase_num}")
        print()
        
        return self.run_training_phase(phase_num)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="🎯 3-Phase Progressive AI Training for Warhammer 40K",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/train_3_phases.py                    # Run all 3 phases with defaults
  python scripts/train_3_phases.py --total-episodes 1500   # Custom episode count
  python scripts/train_3_phases.py --max-concurrent 6      # More concurrent sessions
  python scripts/train_3_phases.py --phase 2               # Run only phase 2
  python scripts/train_3_phases.py --plan-only             # Show training plan only
        """
    )
    
    parser.add_argument(
        "--total-episodes", 
        type=int, 
        default=1200,
        help="Total episodes across all phases (default: 1200)"
    )
    
    parser.add_argument(
        "--max-concurrent", 
        type=int, 
        default=4,
        help="Maximum concurrent training sessions (default: 4)"
    )
    
    parser.add_argument(
        "--phase", 
        type=int, 
        choices=[1, 2, 3],
        help="Run only a specific phase (1=solo, 2=cross_faction, 3=full_composition)"
    )
    
    parser.add_argument(
        "--plan-only", 
        action="store_true",
        help="Show the training plan without executing"
    )
    
    args = parser.parse_args()
    
    # Create training manager
    trainer = ThreePhaseTrainingManager(
        total_episodes=args.total_episodes,
        max_concurrent=args.max_concurrent
    )
    
    # Show training plan
    trainer.print_training_plan()
    
    if args.plan_only:
        print("📋 Training plan displayed. Use without --plan-only to execute.")
        return 0
    
    # Confirm with user
    print("🤔 Ready to start training? This will take 9-13 hours total.")
    response = input("Continue? (y/N): ").strip().lower()
    
    if response not in ['y', 'yes']:
        print("🛑 Training cancelled by user.")
        return 0
    
    print()
    
    # Execute training
    if args.phase:
        # Run single phase
        success = trainer.run_single_phase(args.phase)
    else:
        # Run complete curriculum
        success = trainer.run_complete_training()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())