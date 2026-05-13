# CoreAgent — Training Logs

| Run | Épisodes | Robust score | Combined final | Combined@robust | Forgetting | Observations | Changements vs run précédent |
|-----|----------|-------------|---------------|-----------------|------------|--------------|------------------------------|
| run_20260512-213235 | 30k | **0.4857** | 43.6% | ? | -0.040 | BEST SESSION. Sweet spot roster fixe 16/10/6. Forgetting quasi nul. SAUVEGARDÉ. | Roster fixe 16/10/6 — baseline de référence |
| run_20260512-234103 | 30k | 0.4202 | 38.4% | 0.4426 | ? | target_kl=0.015 trop conservateur. Underfitting, holdout_hard_bot-07=0.0. Éliminé. | target_kl 0.02→0.015 |
| run_20260513-005303 | 30k | 0.4183 | 40.0% | 0.4197 | ? | target_kl=0.025 aussi inférieur. Les deux directions < baseline. target_kl=0.02 validé définitivement. | target_kl 0.02→0.025 |
| run_20260513-020335 | 30k | 0.3281 | 20.2% | 0.3431 | ? | batch_size=2048 catastrophique. Trop peu de gradient steps par rollout (384 vs 768). batch_size=1024 validé définitivement. | batch_size 1024→2048 |
| run_20260513-030832 | 30k | 0.3808 | 21.4% | 0.3844 | ? | n_steps=8192 inférieur. Rollout trop petit → instabilité. | n_steps 16384→8192 |
| run_20260513-041323 | 30k | 0.4345 | 32.1% | 0.4727 | ? | n_steps=32768 mieux que 8192 mais < baseline. n_steps=16384 validé définitivement. holdout_hard_bot-10 ≈0 récurrent. | n_steps 16384→32768 |
| run_20260513-091925 | 30k | 0.3640 | 24.3% | 0.3963 | ? | LR=0.0005→0.0001 inférieur. LR=0.0003→0.0001 validé. | LR initial 0.0003→0.0005 |
| run_20260513-114828 | 30k | 0.4201 | 33.0% | 0.4381 | ? | ent_coef fixe 0.02 inférieur. Entropie plus haute ne suffit pas à lever le plateau. | ent_coef 0.02→0.01 supprimé |
| run_9 (n_epochs=5) | — | — | — | — | — | Interrompu. vp_bot≈39 vs vp_agent≈23 confirmé → reward objectifs trop faibles. | n_epochs 3→5 |
