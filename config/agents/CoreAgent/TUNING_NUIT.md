# CoreAgent — Instructions tuning MODE NUIT

## Objectif
Maximiser le **robust score** (critère réel de sélection du BEST).  
BEST actuel : robust_score=**0.4857** (run_20260512-213235)

## Commande de lancement
```
W40K_PERF_TIMING_MIN_EPISODE=2 python3 ai/train.py --agent CoreAgent --training-config x1 --scenario bot --new --resolution 1
```

## Métriques à lire en fin de run (stdout)
```
📌 Robust checkpoint summary
   Best robust score: X.XXXX          ← CRITÈRE PRINCIPAL (battre 0.4857)
   Combined at robust best: X.XXXX    ← contexte
   Worst bot score at robust best: …
   Worst holdout regular/hard …

Combined Score: XX.X%                 ← indicateur secondaire seulement
```

## Colonnes Training_logs.md
| Run | Épisodes | Robust score | Combined final | Combined@robust | Forgetting | Observations | Changements |

## Règles validées définitivement (ne pas re-tester)
- Roster fixe start=end={ swarm:16, troop:10, elite:6 } — NE PAS CHANGER
- batch_size ≤ 512 → catastrophique
- Curriculum de roster → catastrophic forgetting
- Ne pas descendre sous 16/10/6 ni monter au-dessus de 24/16/10
- Tier2 tensorboard → ignoré (biaisé par composition roster)

## Config baseline (x1)
- LR: 0.0003→0.0001, n_steps: 16384, batch_size: 1024, n_epochs: 3
- target_kl: 0.02, ent_coef: 0.02→0.01, net_arch: [320, 320]
- 30k épisodes, n_envs=48, seed=12345

## Workflow — 2 phases

### Phase 1 : Screening (1 seed = 12345)
- Tester chaque hyperparamètre isolément
- 1 run par config, seed fixe 12345
- Critère d'élimination : robust_score < 0.47 (nettement inférieur au BEST)
- Métriques à partir de ep10k uniquement
- Logger chaque run dans Training_logs.md (1 ligne)

Hyperparamètres à tester (un seul changement par run) :
- target_kl : 0.015 / 0.025
- LR schedule : 0.0005→0.0001 / 0.0002→0.00005
- batch_size : 2048
- n_steps : 8192 / 32768
- n_epochs : 5

### Phase 2 : Validation (3 seeds)
- Uniquement pour les 2-3 meilleurs candidats du screening
- Seeds : 12345, 42, 7
- Critère BEST : robust_score moyen > 0.4857
- Si nouveau BEST → cp config + model + mv tensorboard

## Règles générales MODE NUIT
- Métriques à partir de ep10k uniquement
- Ne jamais modifier users.db ni ai/models/**/*.zip
- Une seule hypothèse par run
- Si nouveau BEST → sauvegarder immédiatement (cp + mv tensorboard)
- Stop si erreur bloquante non récupérable

## Sauvegarde BEST
```bash
cp config/agents/CoreAgent/CoreAgent_training_config.json config/agents/CoreAgent/BEST_CoreAgent_training_config.json
cp ai/models/CoreAgent/model_CoreAgent.zip ai/models/CoreAgent/BEST_model_CoreAgent.zip
mv tensorboard/<run_id> tensorboard/BEST_x1_CoreAgent
```
