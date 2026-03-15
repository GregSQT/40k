# Refactor Observation pour Entrainement PPO (Blend-First)

## Objectif

Maximiser l'efficacite d'entrainement PPO (stabilite, sample efficiency, robustesse holdout), en priorisant un comportement tactique contextuel guide par l'observation plutot qu'une specialisation statique de type cible.

Ce document propose une refactorisation orientee performance, meme si le cout implementation/compute est eleve.

---

## Constat actuel (etat du code)

L'observation contient deja de forts signaux tactiques utiles pour choisir la bonne cible en contexte:
- `best_kill_probability`
- `danger_to_me`
- `distance`
- `is_priority_target`
- `coordination_bonus`
- informations LoS et menace equipe

En parallele, l'observation embarque encore des signaux "type statique":
- `combat_mix_score` base sur `unitType`
- `favorite_target` derive de `unitType`

Ces signaux peuvent biaiser la politique vers des heuristiques de categorie, alors que les features tactiques permettent deja des decisions cible-dependantes.

---

## Hypothese principale

Un pipeline "blend-first + observation tactique dynamique" est plus efficace pour PPO que "type/cible preferee statiques", sous reserve d'une observation coherente par phase (shoot/fight/charge) et d'une evaluation stricte par split holdout.

---

## Principe directeur de refactorisation

1. Garder les signaux tactiques dynamiques.
2. Reduire les priors statiques issus de `unitType` dans l'observation.
3. Rendre les features de selection arme/cible coherentes avec la phase courante.
4. Evaluer chaque etape via ablation avec gate robustesse (pas seulement reward train).

---

## Architecture cible (high-impact)

### A. Observation "phase-aware" pour engagement reel

Probleme actuel:
- Certaines features cible utilisent selection ranged par defaut, meme hors shoot.

Refactor:
- Calculer `best_weapon_index` et `best_kill_probability` selon phase active:
  - shoot -> arme ranged
  - fight -> arme melee
  - charge -> proxy melee/charge-reach (pas ranged par defaut)
- Conserver la meme semantique de slots d'action, mais avec scoring phase-coherent.

Impact attendu:
- Moins de bruit supervision implicite.
- Meilleure credit assignment PPO selon phase.

### B. Deprioriser les features de type statique

Probleme actuel:
- `combat_mix_score` et `favorite_target` derivent partiellement de `unitType`.

Refactor:
- Remplacer par signaux purement dynamiques derives des armes/état courant:
  - ratio efficacite melee/ranged contextuel
  - danger reciproque contextuel
  - valeur tactique cible (value/time-to-kill)
- Garder les champs statiques uniquement pour monitoring externe (pas comme feature prioritaire de policy).

Impact attendu:
- Moins de sur-specialisation.
- Meilleure adaptation inter-rosters et inter-matchups.

### C. Coherence entre sections observation

Probleme actuel:
- Une meme cible peut avoir des indications heterogenes entre "enemy units" et "valid targets".

Refactor:
- Harmoniser les fonctions de scoring pour que les sections utilisent la meme logique de dommage/TTK phase-aware.
- Introduire un unique service de scoring observation (fonctions centralisees).

Impact attendu:
- Moins de contradiction intra-observation.
- Plus grande stabilite d'apprentissage.

### D. Stabilisation PPO (option cout eleve)

Recommande si objectif = performance max:
- Plus de seeds pour decisions de merge.
- Eval holdout plus frequente avec split explicite `regular`/`hard`.
- Early-stop/gating base robustesse (overall + hard + worst-bot), pas reward train.
- Eventuellement augmenter capacite policy/value net si saturation detectee.

---

## Plan d'implementation (work packages)

### WP1 - Instrumentation et baseline (obligatoire)

But:
- figer baseline et obtenir profils d'erreurs.

Actions:
- Logger metriques par phase sur features cibles (distribution kill_prob, danger, valid_target count).
- Snapshot evaluation stratifiee par bins Blend/Tanking.

Definition of done:
- baseline reproductible (plusieurs seeds) + rapport de variance.

### WP2 - Phase-aware scoring dans valid targets

Fichiers cibles:
- `engine/observation_builder.py`
- `engine/ai/weapon_selector.py` (si adaptation necessaire)

Actions:
- rendre `best_weapon_index`/`best_kill_probability` dependants de la phase.
- verifier coherence action-mask vs target features.

Definition of done:
- pas de regression sur validite des actions.
- metriques observation coherentes en shoot/fight/charge.

### WP3 - Remplacement des priors statiques `unitType`

Fichiers cibles:
- `engine/observation_builder.py`

Actions:
- remplacer/neutraliser features basees sur `unitType` par signaux dynamiques.
- conserver fallback explicite uniquement en cas de donnees manquantes avec erreur claire.

Definition of done:
- aucune feature tactique critique ne depend de categorie statique.

### WP4 - Harmonisation du scoring cible (service unique)

Fichiers cibles:
- `engine/observation_builder.py`
- eventuel nouveau module utilitaire observation/scoring

Actions:
- unifier formules de menace/efficacite utilisees par sections ennemis + targets.

Definition of done:
- ecarts logiques elimines entre sections.

### WP5 - Tuning PPO et validation robustesse

Fichiers cibles:
- `ai/train.py`
- `ai/training_callbacks.py`
- configs agent

Actions:
- renforcer protocole d'evaluation holdout.
- selection meilleur modele par robustesse, pas reward train.

Definition of done:
- gains holdout stables sur seeds.

---

## Protocole d'ablation (decision scientifique)

Comparer au minimum:

- **B0 (baseline)**: systeme actuel
- **B1**: B0 + phase-aware valid-target scoring
- **B2**: B1 + suppression priors statiques `unitType`
- **B3**: B2 + scoring observation unifie

Pour chaque build:
- plusieurs seeds
- meme budget steps
- eval `holdout_regular` + `holdout_hard`

### Criteres de selection (ordre priorite)

1. `holdout_overall_mean` max
2. contrainte min sur `holdout_hard_mean`
3. contrainte min sur `worst_bot_score`
4. variance inter-seed acceptable

Si un build augmente overall mais degrade hard/worst-bot, il est rejete.

---

## Risques et mitigations

- Risque: regression rapide en debut training.
  - Mitigation: rollout progressif WP2 -> WP3 -> WP4 avec rollback simple.

- Risque: surcout compute important.
  - Mitigation: filtrer vite via tests courts avant runs longs.

- Risque: features trop corrigees => perte d'information.
  - Mitigation: garder instrumentation detaillee et seuils go/no-go.

---

## Go / No-Go

Go vers merge complet si:
- amelioration robuste holdout global
- pas de collapse sur holdout hard
- pas de degradation worst-bot
- comportement tactique observable plus coherent (priorisation cible contextuelle)

Sinon:
- conserver WP2 seulement (phase-aware), et reevaluer WP3/WP4.

---

## Recommandation finale

Pour "efficacite maximale PPO", la meilleure trajectoire est:
- **Blend-first en categorisation**
- **Observation tactique dynamique phase-aware**
- **Ablation stricte avec gate robustesse holdout**

Cette approche est plus couteuse, mais c'est celle qui maximise les chances de gains reels et transferables.

