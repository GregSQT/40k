# Plafonnement de l'apprentissage — P1 contre P0 : causes, solutions, état

> **Chantier ouvert le 2026-09-13.** Sujet : [Roadmap/training.md](../../Roadmap/training.md).
> Dossier de synthèse : il **relate** ce qui a été fait sur le plateau de la lignée P0 → P1 entre
> le 2026-09-11 et le 2026-09-13 (avec les antécédents P2 du 2026-09-04 → 09-08 qui ont fixé le
> régime de lignée), inventorie **toutes** les causes envisagées et **toutes** les solutions, et
> coche ce qui a été fait, testé, réfuté ou laissé ouvert. Il ne décide rien : la décision en
> attente est au §7. Toute nouvelle mesure s'ajoute ici **et** dans `training.md`.
>
> Légende des statuts : ☑ fait / mesuré · ◐ partiel · ☐ non fait · ✗ écarté (avec la raison) ·
> ⏳ proposé, en arbitrage.

---

## En clair — ce qu'on sait, ce qu'on propose (lecture non technique, 2026-09-13 soir)

**Le problème.** P1, c'est P0 réentraîné contre lui-même. Il gagne 6 parties sur 10 contre P0
depuis 40 000 parties et n'avance plus ; le seuil pour passer à l'étape suivante demande 6,5 sur
10.

**Ce qu'on a essayé et écarté.**
- Les réglages classiques de l'apprentissage (taille des lots, vitesse d'apprentissage, nombre
  de passes, plafond du gradient, poids du critic) : chacun testé ou mesuré, aucun ne débloque.
- L'exploration : l'agent hésite très peu sur les décisions courtes (charger, viser, se
  déployer). Le faire hésiter 2 à 5 fois plus (expérience d'hier) n'a rien changé au jeu.
- Baisser le seuil de promotion : le même dispositif passait quand le seuil valait 0,55 ; écarté
  par décision, parce que ça promeut un agent qui n'apprend plus.

**La cause, mesurée ce soir.** À chaque étape d'apprentissage, l'agent reçoit un « conseil » :
dans quelle direction se modifier pour mieux jouer. On a mesuré quelle part de ce conseil est du
vrai signal et quelle part est du hasard (dés, choix aléatoires de l'adversaire, longues chaînes
de conséquences). Avec les réglages actuels, **le conseil est du hasard à 98 %** : l'agent bouge
à chaque étape, mais dans une direction tirée au sort — c'est le plateau. Deux mesures
indépendantes (deux sessions, deux programmes) donnent le même chiffre. Un agent volontairement
plus faible (28 % contre P0) est dans la même situation : ce n'est pas que P1 aurait « tout
appris », c'est que ce régime ne laisse passer presque aucun signal.

**Deux leviers, insuffisants séparément, jamais essayés ensemble.**
- Raccourcir la « mémoire » du crédit (sur combien de coups futurs on juge une décision, le
  paramètre λ) : le signal passe de 2 % à 6 %. Mieux, mais encore 94 % de hasard.
- Agrandir les lots (juger sur 4 fois plus de coups avant de bouger) : essayé seul le
  7 septembre, sans effet — normal, il n'y avait alors aucun signal à amplifier.
- Les deux ensemble : jamais essayé. La formule vérifiée sur les données prédit **environ 18 %
  de signal, dix fois aujourd'hui**.

**La recommandation.** Relancer P1 avec trois valeurs changées dans le profil `x1_lineage`
(`config/agents/ArmageddonAgent_x1/ArmageddonAgent_x1_training_config.json`, bloc
`model_params`) et rien d'autre : `gae_lambda` 0,95 → **0,2**, `n_steps` 8160 → **32640**,
`batch_size` 1020 → **4080**. Commande habituelle (`python3 ai/train.py --agent
ArmageddonAgent_x1 --training-config x1_lineage --scenario bot --etape P1`), 30 000 épisodes
(~6 h), à juger sur la courbe `03_selfplay/P0`, aujourd'hui plate à 0,59. Un point à surveiller :
la mémoire du GPU au premier lot de 4 080 (un essai avait planté le 7 septembre ; la cause a été
levée depuis, mais ce n'est pas revérifié) — si ça plante, `batch_size` 2 040.

**Si ça ne bouge pas.** Le levier « réglages » est épuisé. Il faut alors changer la façon dont
l'agent reçoit son conseil : soit une tête « Q » qui moyenne les dés (quelques jours de code),
soit l'entraînement par recherche (MCTS, plusieurs semaines, chantier gelé après J3). C'est
l'arbitrage que l'autre session propose ; il ne se pose qu'après ce run.

**Mesure optionnelle (20 min, aucun code).** Sonder le modèle « traité » de l'expérience
d'hier (celui qui hésite plus) contre son témoin : si l'hésitation augmente le signal, la
température devient un levier chiffrable ; sinon on sait que le hasard vient des dés et de
l'adversaire, pas du manque d'exploration. Pas nécessaire pour lancer le run.

---

## 0. Résumé au 2026-09-13

**Symptôme.** P1 (reprise des poids de P0, profil `x1_lineage`) plafonne contre P0 : sondes
déterministes 0,547 → 0,623 → 0,601 (moyennes de 3 sondes) entre 60 000 et 120 000 épisodes
cumulés, seuil de promotion 0,65 jamais approché ; toutes les courbes de jeu sont plates après
~20 000 épisodes d'étape ; run arrêté le 2026-09-12 après 14 h 56.

**Prouvé (mesuré, reproductible).**
1. À ce point de P1, **le gradient de politique d'une update est du bruit à plus de 97,8 %**
   (fraction de signal f_8160 = 0,005 [−0,012, 0,022], 24 rollouts de 8 160 pas dans l'env exact
   de P1). Un lot 44 fois plus grand serait le **minimum** pour une update à moitié signal — s'il
   y a un signal, ce que 24 rollouts ne peuvent pas affirmer. Le critic, lui, reçoit un gradient
   réel (f = 0,27). `scripts/grad_signal_probe.py`, [training.md#signal-p1-2026-09-13](../../Roadmap/training.md#signal-p1-2026-09-13).
2. Les **têtes courtes sont effondrées** (charge_slot 0,007 nat sur 0,86 possible, shoot_slot
   0,23 / 1,58, deploy_slot 0,16 / 1,95) et `ent_coef` 0,01 pèse 1,3 % du gradient ; mais
   **rouvrir l'exploration ×2 à ×5 n'a aucun effet mesurable sur le jeu** (holdout 87,5 % → 87,9 %,
   vs P0 28 % → 22 %, dans le bruit). [training.md#entropie-normalisee](../../Roadmap/training.md#entropie-normalisee).
3. **L'early-stop KL coupe chaque update** (761/761 sur P1, 590/590 et 588/588 sur les bras
   entnorm), et cette KL est produite par un pas de bruit, pas par un déplacement dirigé.
4. **La source du bruit est mesurée (suite 123, 2026-09-13).** Sur les mêmes rollouts, descendre
   λ de 0,95 à 0 rend un gradient détectable (‖G‖² × 3,4, Δf appairé −0,038 [−0,070, −0,005])
   mais **f(λ=0) = 0,053 [0,036, 0,070]** : au λ le plus bas l'update reste à 95 % de bruit,
   B_noise ≈ 147 000 pas. **Var(δ) = 0,050 = Var(r) 0,043 + Var(ΔV) 0,065 − 0,058** (ρ = −0,55) :
   le critic anticipe la récompense façonnée, δ garde l'échelle de Var(r), portée par le tir
   (0,96) et le combat (0,7–0,8), quasi nulle sur les mouvements (0,12). P0 déterministe : mêmes
   nombres. **L'instrument est sain** : un contrôle à poids aléatoires rend f = 0,43 [0,27, 0,59]
   à λ = 0,95 ; le contrôle `entnorm_040721` (30 points de holdout plus faible) rend f = 0,006
   comme P1 et ne discriminait pas. [training.md#signal-p1-lambda-2026-09-13](../../Roadmap/training.md#signal-p1-lambda-2026-09-13).

**Réfuté comme levier.** Taille de lot (n_steps × batch_size), `target_kl`, `n_epochs`,
`learning_rate`, `max_grad_norm`, part du critic (`vf_coef`), `ent_coef` seul, entropie
normalisée par l'état : tous règlent une direction qui n'en est pas une, ou ont été testés sans
effet.

**Ouvert.** Le gradient TD(0) détecté est celui d'un estimateur biaisé par l'erreur du critic,
pas la preuve d'une pente utile ; le gradient d'issue (±150) reste nul à la précision de K = 24.
Ce qui n'est pas identifiable sans l'espérance : la part de Var(r) qui est du dé (ΔV dépend
aussi du dé, une cible tuée change s′).

**Décision en attente (§7).** L'option B est exécutée : à lot fixe, ni λ ni l'adversaire
déterministe ne réduisent le bruit ; ce qui reste est le crédit lui-même. Reste à trancher le
mécanisme d'avantage moyenné — tête Q (S14) ou distillation par recherche (S15) — et si S11
(récompense en espérance, bornée à 86 % de Var(δ)) précède.

---

## 1. Le symptôme, mesuré

### 1.1 Le run

| | |
|---|---|
| Commande | `python3 ai/train.py --agent ArmageddonAgent_x1 --training-config x1_lineage --scenario bot --etape P1` |
| Run | `tensorboard/x1_lineage_ArmageddonAgent_x1/run_20260912-065925`, journal `training_x1_02-p01.log` |
| Départ | 2026-09-12 06:59, reprise de `model_ArmageddonAgent_x1_P0.zip` = `robust_0.8683` (P0 à froid, 50 000 épisodes `x1_long`, 2026-09-10 22:31) |
| Profil `x1_lineage` | lr 0,001 · ent_coef 0,01 · n_steps 8 160 (340 × 24 envs) · batch_size 1 020 (8 mini-lots) · n_epochs 4 · target_kl 0,015 (coupure à 0,0225) · clip 0,2 · vf_coef 0,17 · max_grad_norm 0,5 · γ 0,99 · λ 0,95 · normalize_advantage · siège P2 à 0,70 |
| Adversité (curriculum P1) | pool = P0 seul à 70 % (**stochastique**, `opponent.deterministic: false`), bots 30 % (alpha 16, attrition 14, decapitation 16, endgame 14, racer 10, scorer 21, random 9), 2 fichiers de scénario en 20 entrées pondérées (murs de référence), rampe de déploiement figée à 0,90 (10 % d'épisodes déployés par le moteur) |
| Parité d'ouverture | 0,473 contre P0 à l'épisode 50 000 (fenêtre [0,40, 0,60] tenue) |
| Arrêt | Ctrl+C le 2026-09-12 vers 21:56, à 76 590 épisodes d'étape (126 590 cumulés), 1 052 updates PPO, dernière sonde à 70 000 |
| Modèle conservé | canonique `model_ArmageddonAgent_x1.zip` = `ArmageddonAgent_x1_12345_robust_0.9078.zip` (18:52, 110 177 épisodes cumulés = 60 000 d'étape), **non promu** |

### 1.2 Sondes contre P0 (300 épisodes, argmax des deux côtés, holdout)

| épisodes cumulés | 50 000 | 60 000 | 70 000 | 80 000 | 90 000 | 100 000 | 110 000 | 120 000 |
|---|---|---|---|---|---|---|---|---|
| sonde brute | 0,473 (baseline) | 0,547 | 0,533 | 0,560 | 0,660 | 0,600 | 0,610 | 0,593 |
| moyenne 3 sondes (décision) | — | 0,547 | 0,540 | 0,547 | 0,584 | 0,607 | 0,623 | 0,601 |

Seuils : promotion ≥ 0,65 après 30 000 épisodes d'étape ; destruction < 0,50 après 20 000.
Erreur-type d'une sonde ≈ 2,9 points, mais les sondes sont des **blocs corrélés** (même modèle,
argmax contre argmax) : ±5 points entre voisines ne sont pas du bruit d'échantillonnage.

### 1.3 Courbes du run, par quart (76 590 épisodes)

| courbe | Q1 | Q2 | Q3 | Q4 | lecture |
|---|---|---|---|---|---|
| `03_selfplay/P0` (jeu stochastique, 69,6 % des épisodes) | 0,541 | 0,596 | 0,585 | 0,595 | plat dès Q2 |
| `game_critical/win_rate_overall` | 0,602 | 0,637 | 0,650 | 0,654 | monte par les bots et le siège, pas par P0 |
| `seat_aware/winrate_agent_p1` / `_p2` | 0,633 / 0,589 | 0,658 / 0,628 | 0,666 / 0,643 | 0,668 / 0,648 | écart de siège ~2 pts |
| `01_VP/a_vp_diff` | 6,07 | 7,38 | 7,42 | 7,44 | plat |
| `game_critical/episode_reward` | 373 | 410 | 408 | 411 | plat |
| `reward_when_won` / `reward_when_lost` | 574 / 40 | 587 / 51 | 587 / 52 | 589 / 52 | récompense quasi binaire |
| `game_critical/episode_length` | 110 | 113 | 112 | 114 | |
| `00_critical/s_win_rate_deploy_active` / `_auto` | 0,637 / 0,512 | 0,686 / 0,518 | 0,682 / 0,495 | 0,690 / 0,475 | 10 % des épisodes joués à 0,50 |
| `bot_eval/worst_bot_score` (holdout, 7 points) | 0,86 | 0,83 | 0,86 | 0,865 | bots saturés (0,86–0,92) |
| `train/approx_kl` / `approx_kl_max` | 0,0095 / 0,030 | 0,0091 / 0,030 | 0,0090 / 0,028 | 0,0096 / 0,035 | coupure > 0,0225 sur 761/761 (suite 110) |
| `train/clip_fraction` | 0,069 | 0,062 | 0,060 | 0,064 | sous le plancher 0,10 du profil |
| `train/entropy_loss` | −0,78 | −0,72 | −0,70 | −0,74 | plat (bande [−2,0, −0,5]) |
| `train/explained_variance` | 0,888 | 0,892 | 0,892 | 0,889 | critic excellent |
| `train/gradient_norm` (brute) / `grad_clip_fraction` | 0,401 / 0,158 | 0,394 / 0,148 | 0,393 / 0,152 | 0,391 / 0,141 | écrêtage sur 15 % des mini-lots seulement |
| `diag/grad_norm_policy_mb0` / `value` / `entropy` | 0,349 / 0,237 / 0,0054 | 0,346 / 0,222 / 0,0044 | 0,349 / 0,220 / 0,0046 | 0,350 / 0,217 / 0,0046 | part policy 0,62 |
| `train/value_loss` | 0,193 | 0,178 | 0,174 | 0,173 | |

Composition de la récompense par épisode (moyenne 400) : objectifs 272 (62 %), bonus de résultat
178, pénalités −97, issue ±150 → +47 (= 150 × (0,656 − 0,344)), actions de base ≈ 0 ;
`immediate_reward_ratio` 0,31. Aucune troncature, aucune action invalide, 0,2 % de nuls.

### 1.4 Ce qui progresse quand même

- Holdout bots du canonique : **90,0 %** le 2026-09-11 (`robust_0.8933`) → **91,0 %** le
  2026-09-13 (`robust_0.9078`), zéro victoire par élimination, écart de siège 12 points, écart de
  roster 12 points ([training.md#holdout-2026-09-13](../../Roadmap/training.md#holdout-2026-09-13)).
- Un modèle **à froid** de 40 000 épisodes (témoin entnorm `x1_40k`) ne bat P0 qu'à **28 %** ;
  P1 (P0 + 60 000 épisodes) le bat à ~60 %. La lignée a donc extrait +10 points au-dessus de la
  parité de construction (0,50), puis s'est arrêtée.
- Sous les seuils en vigueur jusqu'au 2026-09-11 (0,55 contre le champion), **le même dispositif
  promouvait** : P1 promu le 2026-09-11 à 05:06 à 30 000 épisodes (P0 = 0,561, gate 0,563), P2
  promu le même jour à 13:09 (P0 = 0,607, P1 = 0,599). Les seuils sont passés à 0,60 / 0,55 à
  09:14 puis à **0,65 / 0,60** à 18:13 (destruction 0,40 → 0,50, `promote_min_episodes` 30 000),
  et P1 a été rejoué depuis P0. Fait rapporté, pas un levier : baisser le seuil a été **écarté
  par décision** le 2026-09-12 (§4, S18).

### 1.5 Ce que le plateau n'est pas

Pas une destruction (aucune chute sous 0,50, entropie stable, EV 0,89) ; pas une panne
d'appariement (parité d'ouverture tenue) ; pas un artefact de fenêtre courte (7 sondes, 4 quarts
plats sur 76 590 épisodes, cf. [feedback sur les fenêtres courtes](../../Roadmap/training.md#regime-lignee-2026-09-07)) ;
pas un problème d'échelle des retours (`returns_mean` 1,63, `ratio_mb0` = 1,0, dérive des
log-prob 1,7 × 10⁻⁴).

---

## 2. Chronologie

### 2.1 Antécédents qui ont fixé le régime de lignée (2026-09-04 → 09-10)

- **2026-09-04** — P2 repris de P1 avec les rampes du profil reparcourues depuis le départ :
  ent_coef 0,018 → 0,100, éval bots 0,911 → 0,694, score contre P1 0,118 (parité 0,50 garantie
  par construction). Détruit. Leçon : une rampe en fraction de run rend à un modèle convergé le
  régime d'un démarrage.
- **2026-09-05** — rampe repartant de la valeur atteinte (0,0177) : sonde **plate à 0,496 sur
  6 mesures et 60 000 épisodes**, éval bots sous celle du modèle de départ. Détruit autrement.
- **2026-09-06** — `run_20260906-200401`, quatre leviers ouverts ensemble (lr 0,002, ent_coef
  0,07, n_epochs 6, max_grad_norm 2,0) : contre P1 0,32 dès le premier quart, entropie montant
  sans plateau. Détruit ; échec attribuable à aucun des quatre. Même jour, décomposition du
  gradient (`run_20260906-225839`) : **le critic captait 75,2 % de la norme** (value 1,035,
  policy 0,323, entropie 0,018) ; la norme brute dépassait `max_grad_norm` 0,5 sur 93 % des
  updates (facteur 2,4).
- **2026-09-07** — `vf_coef` 0,5 → 0,25 (`run_20260907-000919` : part policy 0,235 → 0,50, EV
  intacte) puis **0,17** dans le profil de lignée (part policy 0,62). `n_steps` 32 640 essayé :
  **55/55 updates coupées par la KL vers le 32ᵉ mini-lot sur 128**, trois quarts du rollout
  jamais vus, ×3,8 plus lent par épisode ; `batch_size` 4 080 : crash VRAM (8,89 Go / 8,19).
  Régime de lignée « option A » : profil `x1_lineage` scalaire pour toute étape reprise (lr
  0,001, ent_coef 0,03 puis 0,01), P00 supprimée, verrou de parité, décisions sur la moyenne de
  3 sondes, graines d'évaluation tirées au hasard, part de bots 30 % en P1 (bots saturés
  0,86–0,99).
- **2026-09-08** — `n_steps` rendu à 8 160, `ent_coef` 0,01, `promote_min_episodes` 30 000
  (`81df8c074`). Précédent P2 `run_20260906-123804` : creux de 20 000 épisodes puis reprise
  franche à 102 000 (vs P1 0,467 → 0,549).
- **2026-09-10** — quatre correctifs moteur qui changent l'issue des parties (contrôle d'objectif
  sommé par figurine, caractéristiques défensives effectives, table de dégâts complétée — 57
  armes sur 231 valaient zéro —, exclusivité des profils combi) : **nouvelle lignée**, P0 à froid
  rejoué (`robust_0.8314` 08:35, puis `robust_0.8683` 22:31, retenu).

### 2.2 Les trois jours (2026-09-11 → 09-13)

| date / heure | action | résultat / observation | référence |
|---|---|---|---|
| 09-11 05:06 | P1 (from P0) promu à 30 000 épisodes | vs P0 0,561 (sonde), 0,563 (gate), seuil 0,55 | `curriculum.log`, `model_ArmageddonAgent_x1_P1.zip` |
| 09-11 09:14 / 09:18 | seuils 0,55 / 0,50 → **0,60 / 0,55** ; siège P2 0,6 → **0,70** | commits `1acd59c87`, `e903c8c35` | config |
| 09-11 13:09 | P2 (from P1) promu à 30 000 | P0 0,607, P1 0,599 (seuils chargés au démarrage : 0,55) | `curriculum.log`, `_P2.zip` |
| 09-11 15:59 | **Holdout 90,0 %** consigné (`robust_0.8933`) | siège P1 95,5 / P2 85,7 ; SM 95,5 / Orks 84,0 ; réserves 20.01 déclarées 22,8 % | [holdout-2026-09-11](../../Roadmap/training.md#holdout-2026-09-11), `4d1d5f89f` |
| 09-11 18:13 | seuils → **0,65 / 0,60**, destruction 0,40 → 0,50, `promote_min` 30 000 | commit `6571ac847` | `curriculum.json` |
| 09-11 21:06 | canonique remis à P0 (`robust_0.8683`), reprise P1 | artefacts écartés `pre_resume_20260911-210621` | `ai/models/ArmageddonAgent_x1/` |
| 09-12 06:59 | **Run P1** relancé (`run_20260912-065925`) | parité 0,473 ; sondes §1.2 | `training_x1_02-p01.log` |
| 09-12 (journée) | sonde d'**entropie par famille** sur le canonique (6 épisodes, 1 301 décisions) | charge 0,007 / 0,86, shoot 0,23 / 1,58, deploy 0,16 / 1,95, oath 0,11 / 1,59, fight_weapon 0,17 / 1,35, move 2,23 / 5,07 ; ent_coef = 1,3 % du gradient | [entropie-normalisee](../../Roadmap/training.md#entropie-normalisee) |
| 09-12 18:04 | tag **`train/n_minibatches_done`** (suite 110) | P1 : 761/761 updates coupées ; position inconnue (tag postérieur) | `e488d9c01` |
| 09-12 ~21:56 | **P1 arrêté** (décision utilisateur : plateau) | 76 590 épisodes d'étape ; canonique = `robust_0.9078` | log |
| 09-12 21:34 | **entropie normalisée par l'état** livrée (clé `entropy_normalize_by_legal`, `scripts/family_entropy_probe.py`, 16 tests) | mécanisme + agent dédié `ArmageddonAgent_x1_entnorm` | `fc9054cea`, `ec2c122ee` |
| 09-12 22:03 | bras raccourcis à 40 000 épisodes ; chaîne contrôle → traité lancée | `logs/entnorm_chain.log` | `d4ede63f0` |
| 09-12 20:43 → 23:43 | checkpoints : rotation, retrait de fin de run, horodatage par run, contrat compagnon (suites 111–115) | infrastructure autour du run, sans effet causal | ROADMAP_INDEX |
| 09-13 04:07 | fin du **contrôle** `x1_40k` (6 h 03) | holdout 87,5 % ; `n_minibatches_done` 15,2 / 32 ; 590/590 coupées | `logs/entnorm_control.log` |
| 09-13 09:48 | fin du **traité** `x1_40k_entnorm` (5 h 41) | holdout 87,9 % ; entropie normalisée −0,70 vs −0,47 ; 15,9 / 32 ; 588/588 | `logs/entnorm_treated.log` |
| 09-13 09:51 | sonde H/KL par famille des deux modèles finaux | têtes courtes du traité 2–5× plus hésitantes ; deploy_slot figé des deux côtés ; move 3,00 vs 2,28 | `logs/entnorm_probe.log` |
| 09-13 09:53 → 10:03 | **Holdout 91,0 %** du canonique (`robust_0.9078`) | 273/300 ; siège 97,7 / 85,7 ; 5 « dead unit fighting » = faux positif Deadly Demise (suites 116–121) | [holdout-2026-09-13](../../Roadmap/training.md#holdout-2026-09-13) |
| 09-13 09:54 | `_doc` de `x1_lineage` corrigé : « les quatre epochs vont au bout » **réfuté** | coupure mesurée, pas résolue | `6fc774530` |
| 09-13 ~12:45 → 14:45 | contrôle et traité **contre P0**, 300 parties chacun | contrôle 28 %, traité 22 % (IC95 de l'écart ±7) | `logs/entnorm_vsP0.log` |
| 09-13 (après-midi) | relecture des 160 tags du run P1 par quart | tout est plat après ~20 000 épisodes d'étape (§1.3) | ce dossier |
| 09-13 18:38 | **Fraction de signal des updates** (`scripts/grad_signal_probe.py`, 12 tests, suite 122) | f_8160 = 0,005 ; ‖G‖² policy ∋ 0 ; critic f = 0,27 ; entropie f = 0,96 ; issue ∋ 0 | `663d7b867`, [signal-p1-2026-09-13](../../Roadmap/training.md#signal-p1-2026-09-13) |
| 09-13 (soir) | arbitrage sur la suite (§7) | recommandation B | ce dossier |

---

## 3. Causes possibles — inventaire et statut

### A. Optimisation

| # | cause | mécanisme | statut | preuve / observation |
|---|---|---|---|---|
| A1 | Lot trop petit : l'update est dominée par le bruit d'échantillonnage | chaque pas de gradient est un tirage ; la politique marche au hasard | ☑ **bruit confirmé**, ✗ **levier réfuté** | f_8160 = 0,005 [−0,012, 0,022], f_1020 = 0,0006 ; B_noise ≥ 358 000 pas (×44 minimum) ; les 8 mini-lots d'un rollout n'ont aucune composante commune (E‖G_rollout‖² = E‖g_mb‖² / 8 exactement) |
| A2 | Early-stop KL coupant chaque update (≈ 15 pas sur 32) | la moitié du rollout n'est jamais apprise | ☑ symptôme confirmé, ✗ cause réfutée | 761/761 sur P1 ; la KL de coupure est produite par un pas de bruit ; à 32 640 la coupure tombait au 32ᵉ/128 (pire) |
| A3 | Learning rate inadapté | pas trop grand (désapprend) ou trop petit (n'avance pas) | ✗ écarté | il règle l'amplitude d'une direction qui n'en est pas une ; lr ×2 a participé à une destruction (2026-09-06) |
| A4 | `n_epochs` trop faible | plus de passes sur le même lot | ✗ écarté | 4 vs 6 mesuré par l'utilisateur, 4 retenu ; les epochs ne moyennent pas le bruit, ils ajoutent du biais off-policy |
| A5 | Écrêtage `max_grad_norm` détruisant l'amplitude | pas de taille fixe | ☑ réfuté depuis vf_coef 0,17 | norme brute 0,39, écrêtage sur 15 % des mini-lots (93 % avant le 2026-09-07) |
| A6 | Critic captant le gradient | la politique n'en reçoit qu'un quart | ☑ réfuté (corrigé le 2026-09-07) | part policy 0,235 → 0,62 ; EV 0,87 → 0,89 ; le critic reçoit encore un gradient réel (f = 0,27) |
| A7 | Normalisation des retours / obs désaccordée | avantages à la mauvaise échelle | ☑ vérifié sain | `returns_mean` 1,63 = `old_values_mean` 1,63 ; ratio_mb0 = 1,000 ; dérive de valeur 2 × 10⁻⁴ ; parité d'ouverture tenue |
| A8 | Adam transforme un gradient nul-en-moyenne en pas de taille ~lr | c'est le mécanisme par lequel le bruit devient déplacement (approx_kl 0,009 par update sans progrès) | ◐ constat, pas une cause première | découle de A1 ; la marche aléatoire de P2-OLD (~6 nats de KL cumulée pour rien) en était déjà le signe |

### B. Exploration

| # | cause | mécanisme | statut | preuve / observation |
|---|---|---|---|---|
| B1 | Effondrement des têtes courtes (charge, tir, pose, Oath, arme) | p ≈ 1 sur l'action jouée → gradient nul par construction (∝ p(1−p)) | ☑ **état confirmé**, ✗ **cause suffisante réfutée** | entropies §2.2 ; expérience entnorm : têtes 2–5× plus hésitantes, 0 effet sur le jeu ; `move_cell` **non effondrée** (2,2 nats) n'a pas de signal non plus (f = 0,024 [−0,07, 0,11]) |
| B2 | `ent_coef` trop faible, moyenne d'entropie dominée par le mouvement | 1,3 % du gradient, n'agit que sur move | ☑ mesuré ; ✗ pousser fort détruit | ent_coef 0,1 sur poids convergés → vs P1 0,118 (2026-09-04) ; 0,07 → détruit (2026-09-06) |
| B3 | Aucune exploration structurée (température, ε, bruit d'action) | la politique joue toujours le même coup, rien à comparer | ☐ non testé | nécessaire pour charge/pose (p = 0,993), insuffisant seul (B1) ; l'exploration **ajoute** de la variance |
| B4 | Adversaire P0 stochastique à l'entraînement, déterministe en sonde | variance d'action adverse dans σ² ; métrique désalignée | ☑ **testé (2026-09-13) → ✗** | collecte P0 déterministe : f(λ=0,95) = 0,009 [−0,014, 0,031], f(λ=0) = 0,061 [0,029, 0,093], Var(δ) 0,0492 — indistinguable de la collecte stochastique ; l'échantillonnage adverse n'est pas le bruit |

### C. Signal de crédit et récompense

| # | cause | mécanisme | statut | preuve / observation |
|---|---|---|---|---|
| C1 | Variance des retours que l'action ne contrôle pas (dés, jeu adverse, horizon GAE ~17 pas à λγ = 0,94) noyant ΔQ | SNR² = p(1−p)·ΔQ²/σ² | ☑ **source décomposée (2026-09-13)** | Var(δ) = 0,050 = Var(r) 0,043 + Var(ΔV) 0,065 + 2 Cov −0,058 (ρ = −0,55) : le critic anticipe la récompense façonnée, δ garde l'échelle de Var(r) ; parts de r : tir 0,96, combat 0,7–0,8, mouvement 0,12 ; ni λ (f plafonne à 0,05) ni l'adversaire déterministe ne la réduisent |
| C2 | Récompense façonnée dominante (objectifs 62 %, kills, pénalités −97) : l'agent optimise un proxy | issue = terme parmi d'autres | ◐ composition mesurée ; direction non mesurable | gradient d'issue ±150 : ‖G‖² ∋ 0 ; cosinus (façonné, issue) non mesurable à K = 24 |
| C3 | Point stationnaire réel : plus rien à gagner contre P0 avec cette récompense | le gradient vrai est nul, pas seulement noyé | ☑ **réfuté à λ ≤ 0,5** | ‖G‖² exclut 0 dès λ = 0,5 sur les mêmes rollouts (λ = 0 : 8,7 × 10⁻⁴ [5,8 × 10⁻⁴, 1,2 × 10⁻³]) ; le contrôle à poids aléatoires est vu à λ = 0,95 (f = 0,43) ; le gradient TD(0) détecté reste biaisé par l'erreur du critic, ce n'est pas la preuve d'une pente utile |
| C4 | Horizon γ / λ trop long | variance ∝ horizon | ☑ **testé (balayage appairé) → levier insuffisant** | f_8160 : 0,015 (0,95) → 0,007 (0,8) → 0,027 (0,5) → 0,048 (0,2) → **0,053 [0,036, 0,070] (0)** ; Δf(0,95 − 0) = −0,038 [−0,070, −0,005] ; B_noise à λ = 0 : 147 000 pas — l'update reste à 95 % de bruit au λ le plus bas |
| C5 | Pénalités −97 par épisode, source non ventilée | signal contradictoire ? | ☐ non investigué | `reward/penalties_total` chevauche `base_actions` (wait, charge_fail) ; ventilation absente |
| C6 | Récompense sur le **jet** de dés plutôt que sur son espérance | variance de r_t | ☐ non testé | modification moteur ; à dimensionner par C1 avant |

### D. Adversité et environnement

| # | cause | mécanisme | statut | preuve / observation |
|---|---|---|---|---|
| D1 | Pool à un seul membre (P0 à 70 %) : surspécialisation | rien d'autre que P0 à battre, style unique | ◐ constat, effet non mesuré | `stages.P1.pool = [P0]` ; la diversité n'arrive qu'en P2 |
| D2 | Bots saturés (30 % du budget sans gradient) | avantage quasi constant | ☑ constaté, assumé | 0,86–0,99 en holdout ; raison du 30 % (adversité structurellement différente) |
| D3 | Siège P2 sur-représenté (0,70) | P2 plus dur (0,627 vs 0,656 en jeu, 85,7 vs 97,7 en holdout) | ◐ décision du 2026-09-11, effet non isolé | l'écart de siège n'a pas bougé depuis le 2026-08-12 (12 points) |
| D4 | 10 % d'épisodes déployés par le moteur joués à 0,50 | position non choisie par l'agent | ☐ non traité | `s_win_rate_deploy_auto` 0,50 vs 0,69 en actif ; `r_obj_held_diff_deploy_auto` −0,24 |
| D5 | Deux fichiers de scénario | diversité de terrain faible | ☐ non testé | É9 (second scénario) ouvert par ailleurs |
| D6 | Moteur modifié pendant la lignée (35 commits entre les holdouts) | références invalidées | ☑ acté, pas une cause du plateau | P0 et P1 jouent le même moteur ; seules les comparaisons avant/après sont interdites |

### E. Mesure et critère

| # | cause | mécanisme | statut | preuve / observation |
|---|---|---|---|---|
| E1 | Sonde argmax contre argmax : blocs corrélés | ±5 points entre sondes voisines | ☑ connu, traité | décision sur la moyenne de 3 sondes ; graines tirées au hasard depuis le 2026-09-07 |
| E2 | Seuil 0,65 hors de portée de ce dispositif | le même dispositif promouvait à 0,55 | ☑ fait établi ; ✗ **baisser le seuil écarté par décision** (2026-09-12) | §1.4 ; un seuil abaissé promeut un agent qui n'apprend plus |
| E3 | Fenêtre de lecture trop courte | conclusion prématurée | ☑ écarté | 7 sondes, 4 quarts plats, 1 052 updates |
| E4 | Instrument de mesure du signal biaisé | faux zéro | ☑ **réfuté (2026-09-13)** | contrôle à poids aléatoires (`--random-init`) : f = 0,43 [0,27, 0,59] à λ = 0,95, K = 12 ; value f 0,97 ; le contrôle `entnorm_040721` rend f = 0,006 comme P1 — il n'était pas positif, pas l'instrument cassé ; implémentation indépendante (40k-a2) concordante |

### F. Capacité et architecture

| # | cause | mécanisme | statut | preuve / observation |
|---|---|---|---|---|
| F1 | Réseau ou têtes pointeur sous-dimensionnés | ne peut pas représenter mieux | ☐ non testé | indices contraires : critic apprend encore (EV 0,89), holdout 91 % |
| F2 | Observation insuffisante pour distinguer les situations décisives | information manquante | ☐ non testé | contrats d'observation V11 ; aucune mesure d'aliasing d'états |

### G. Convergence

| # | cause | mécanisme | statut | preuve / observation |
|---|---|---|---|---|
| G1 | P1 = P0 + entraînement contre lui-même : +10 points puis limite de ce que PPO extrait d'un adversaire identique avec des dés | le gain marginal tombe sous le bruit | ☐ non distingué de C1 / C3 | 0,50 → 0,60 en 40 000 épisodes puis plat ; reproductible (P1 du 2026-09-11 : 0,561 à 30 000) |

---

## 4. Solutions possibles — inventaire et statut

| # | solution | cause visée | statut | coût | observation |
|---|---|---|---|---|---|
| S1 | `n_steps` × 4 (32 640) | A1 | ☑ testée (P2, 2026-09-07) → ✗ | config | coupure KL au 32ᵉ/128, ×3,8 plus lent ; mesure du 2026-09-13 : ×44 serait le minimum |
| S2 | `batch_size` 4 080 | A1 | ☑ testée → ✗ | config | crash VRAM (8,89 Go) ; VRAM libérée depuis (obs non résidentes), mais levier réfuté par f |
| S3 | `target_kl` relevé / `n_epochs` | A2 | ✗ écarté | config | 0,03 prendrait des pas de 0,045 nat hors région de confiance ; direction = bruit |
| S4 | `learning_rate` | A3 | ✗ écarté | config | idem ; antécédent de destruction |
| S5 | `vf_coef` 0,5 → 0,17 | A6 | ☑ livrée (2026-09-07) | config | part policy 0,62, EV intacte ; aucun effet sur le plateau |
| S6 | `max_grad_norm` 2,0 | A5 | ☑ testée (2026-09-06) → instrument seulement | config | redescendu à 0,5 ; norme brute publiée depuis |
| S7 | Régime scalaire de lignée (lr 0,001, ent_coef 0,01) | rampes reparcourues | ☑ livrée (2026-09-07/08) | config + code | a stoppé les destructions ; n'a pas produit de progression au-delà de 0,60 |
| S8 | Entropie normalisée par l'état + `ent_coef` × 5 | B1, B2 | ☑ testée (2026-09-12/13) → **sans effet** | code + agent dédié, 2 runs (11 h 44) | exploration ×2–5 sur têtes courtes ; holdout +0,4 pt, vs P0 −6 pts, dans le bruit ; clé conservée, désactivée par défaut |
| S9 | Température des logits (T ≈ 2) à la collecte **et** dans le ratio PPO, T = 1 en évaluation | B1, B3 | ☐ envisagée (rapport du 2026-09-13, option C) | code (`_action_logits`, côté workers comme `evaluate_actions`) | nécessaire pour charge/pose, insuffisante seule ; ajoute de la variance : à mesurer **après** la question C1 |
| S10 | `gae_lambda` 0,95 → 0,8 / 0,5 / 0,2 / 0 ; `gamma` 0,97 | C1, C4 | ☑ **λ mesuré a posteriori (2026-09-13) → ✗ comme levier seul** | config | f(λ=0) = 0,053 [0,036, 0,070] < 0,1 : le critère écrit pour relancer P1 à ce λ n'est pas atteint ; γ non balayé (critic à 0,99) |
| S11 | Récompense en **espérance** pour tir et mêlée (dés joués pour la partie, récompensés sur la valeur attendue) | C1, C6 | ☐ envisagée, **dimensionnée** | moteur + contrat d'entraînement | borne : Var(r) = 86 % de Var(δ), portée par tir (0,96) et combat (0,7–0,8) ; la part exactement retirée, Var(r − E[r∣s,a]), n'est pas identifiable sans l'espérance (ΔV dépend aussi du dé) |
| S12 | P0 **déterministe** à l'entraînement | B4 | ☑ **mesurée (2026-09-13) → ✗** | config (`opponent.deterministic`) | mêmes f et même Var(δ) qu'en stochastique ; ne retire rien de mesurable |
| S13 | Sonde étendue : balayage λ appairé + décomposition de Var(δ) + contrôle positif + P0 déterministe | C1, C3, C4, E4 | ☑ **livrée et exploitée (2026-09-13, suite 123)** | script + tests (24), 4 collectes (~1 h 30 de GPU) | verdict : aucune des trois issues écrites ne s'applique telle quelle ; par élimination argumentée → changer le mécanisme (S14 / S15), S11 dimensionnée ; [training.md#signal-p1-lambda-2026-09-13](../../Roadmap/training.md#signal-p1-lambda-2026-09-13) |
| S14 | Avantage moyenné pour l'acteur : tête Q(s,a) dans PPO (A = Q − V, dés moyennés par régression) | C1 | ⏳ **désignée par S13, décision en attente (§7)** | code IA | mesurable par la même sonde ; S13 a conclu « le bruit d'un pas noie le ΔQ restant, à lot fixe ni λ ni l'adversaire ne le réduisent » |
| S15 | Distillation par recherche (MCTS S0 → S2, `mcts.md`) | C1, G1 | ☐ gelée « après J3, seulement si la démo l'exige » (ROADMAP_INDEX) | semaines ; clone d'état 745 ms → ≤ 30 ms | remède de principe quand le gradient de politique est du bruit ; à ouvrir sur décision si S13 / S14 échouent |
| S16 | Pool élargi dès P1 (P0 + exploiteur) ou part de bots | D1 | ☐ non testée | curriculum | rien ne dit que la diversité crée du signal là où P0 n'en donne plus |
| S17 | Second scénario / rosters (É9) | D5 | ☐ ouvert ailleurs | scénarios | |
| S18 | Baisser le seuil 0,65 / laisser courir / promotion sur plateau | E2 | ✗ **écartés par décision** (2026-09-12) | — | « un seuil abaissé promeut un agent qui n'apprend plus ; le problème reste dans la lignée » |
| S19 | Traiter les 10 % d'épisodes déployés par le moteur à 0,50 | D4 | ☐ non investigué | config / moteur | suspicion, pas de preuve d'effet sur P0 |
| S20 | Ventiler les pénalités −97 | C5 | ☐ non investigué | tracker | |
| S21 | K ≈ 316 rollouts pour distinguer ‖G‖² = 0 de 8 × 10⁻⁵ | C3 | ✗ jugé inutile pour la décision | ~4 h | même à la borne haute, l'update est du bruit à > 97,8 % |
| S22 | Second run traité entnorm (variance entre entraînements) | B1 | ☐ non fait | ~6 h | écart holdout < 10 points → « pas de verdict » selon le critère écrit ; remplacé par la mesure S13 plus directe |
| S23 | **λ court ET lot ×4 ensemble** : `gae_lambda` 0,2, `n_steps` 32 640, `batch_size` 4 080 (8 mini-lots, `target_kl` inchangé) | C1, C4, A1 | ⏳ **proposé (§7, complément 40k-a2)**, prédiction chiffrée | config `x1_lineage`, run ~6 h | f attendu ≈ 0,18 [0,13, 0,32] contre 0,018 aujourd'hui (f_B = 1 / (1 + B_noise / B), B_noise(λ = 0,2) = 145 000 [69 000, 222 000]) ; ni λ seul ni lot seul n'ont été testés ensemble ; risque VRAM du lot 4 080 à revoir |

---

## 5. Ce qui a été fait, en détail

### 5.1 Run P1 `run_20260912-065925` (2026-09-12)
- [x] Reprise de P0 sous le régime de lignée, parité d'ouverture vérifiée (0,473).
- [x] 7 sondes contre P0 (§1.2), aucune au-dessus de 0,66 brut, moyenne maximale 0,623.
- [x] Arrêt sur décision utilisateur à 76 590 épisodes d'étape ; canonique = instantané robuste
      0,9078 (score robuste = pire cas bots / scénarios / holdout, **pas** un score de pool).
- [x] Relecture des 160 tags par quart (§1.3) : rien ne bouge après ~20 000 épisodes d'étape.
- Observation : la politique **se déplace** à chaque update (approx_kl 0,009 nat, 1 052 updates)
  sans rien améliorer ; le critic reste excellent ; la récompense est quasi binaire (587 / 52).

### 5.2 Holdouts (2026-09-11 et 2026-09-13)
- [x] 90,0 % puis 91,0 % (300 épisodes, 6 bots, 2 rosters, siège alterné), zéro élimination.
- [x] Écart de siège 12 points et écart de roster 12 points, inchangés.
- [x] 5 « dead unit fighting » qualifiés faux positif (Deadly Demise, suites 116–121).
- Observation : le holdout bots est proche de sa saturation ; il ne mesure pas le plateau, qui
  se lit contre P0.

### 5.3 Sonde d'entropie par famille (2026-09-12, `scripts/family_entropy_probe.py`)
- [x] 6 épisodes, 1 301 décisions, plancher uniforme vérifié (logits à zéro, H = ln n).
- [x] Têtes courtes effondrées (§2.2) ; `ent_coef` = 1,3 % du gradient, n'agit que sur move.
- Observation : une politique **neuve** n'est pas uniforme sur les têtes pointées (d'où le
  plancher uniforme).

### 5.4 Comptage des pas de gradient (`train/n_minibatches_done`, suite 110)
- [x] Tag publié (`e488d9c01`), doublon `00_critical/v_n_minibatches_done`.
- [x] Première lecture (x1_40k) : 15,2 / 32 en moyenne, 13,4 → 18,2 par quart.
- [x] `_doc` de `x1_lineage` corrigé (« les quatre epochs vont au bout » réfuté).
- Observation : sur P1 lui-même la position de la coupure reste inconnue (run antérieur au tag).

### 5.5 Expérience « entropie normalisée par l'état » (2026-09-12 → 09-13)
- [x] Mécanisme : terme `−mean(H_i / ln n_i)` sur les états à n_i > 1, clé sérialisée dans le
      zip, `train/entropy_loss` brut conservé, `train/entropy_loss_normalized` publié partout
      (16 tests, rouge/vert par mutation sur cinq défauts).
- [x] Agent dédié `ArmageddonAgent_x1_entnorm` (copie complète), profils `x1_40k` (contrôle) et
      `x1_40k_entnorm` (clé + ent_coef 0,5 → 0,05, ×5 ≈ ln n moyen du mouvement).
- [x] Deux runs même code enchaînés (contrôle 22:04 → 04:07, traité 04:07 → 09:48).
- [x] Résultats : holdout 87,5 vs 87,9 % ; vs P0 28 vs 22 % (300 parties) ; entropie normalisée
      −0,47 vs −0,70 ; H par famille traité / contrôle : activate 0,90 / 0,41, shoot 0,77 / 0,34,
      shoot_weapon_sel 0,85 / 0,36, oath 1,00 / 0,60, charge 0,24 / 0,05, wait 0,75 / 0,23,
      fight_weapon 0,45 / 0,25, move 3,00 / 2,28, deploy 0,29 / 0,36 (figé des deux côtés).
- [x] Conclusion consignée : le mécanisme fait ce qu'il devait sur l'exploration, **aucun effet
      sur le jeu** ; clé conservée, désactivée par défaut.
- [ ] Second run traité (variance entre entraînements) — non fait, cf. S22.

### 5.6 Fraction de signal des updates (2026-09-13, `scripts/grad_signal_probe.py`, suite 122)
- [x] Env exact de P1 reconstruit par les briques de `ai/train.py` (curriculum, overrides,
      20 entrées de scénario, 24 envs, VecNormalize figée avec `norm_reward` rétabli), refus si
      un entraînement tourne, vérification en sortie que zip / pkl / JSON n'ont pas bougé.
- [x] Acceptation tenue au premier rollout (policy mb0 0,378 vs 0,354 ± 0,052, EV 0,895, ep_len
      114,8, returns 1,773, part pool 0,67).
- [x] 24 rollouts, 1 743 épisodes, 0 sans vainqueur ; ‖G_vrai‖² sans biais (Gram hors diagonale),
      f_8160, f_1020, B_noise, jackknife, 20 groupes de paramètres, cosinus sans biais.
- [x] Résultat §0 ; 12 tests (rouge/vert par mutation : diagonale incluse → 4 rouges, queue
      d'épisode acceptée → 1 rouge).
- Observation : le seul groupe dont f exclut 0 (`shoot_weapon_sel_query_net`, 0,085 [0,015,
  0,155]) est à ~2σ sur 20 groupes, ce que le test multiple produit seul.

### 5.7 Autour du run, sans lien causal avec le plateau
- [x] Checkpoints : rotation (111), retrait de fin de run (112, 113), horodatage par run (114),
      contrat compagnon par modèle (115).
- [x] Analyzer : journalisation Deadly Demise et verdicts §1.7 (116 → 121).
- [x] Tracker sur une seule abscisse, sondes comptées dans le temps bloqué (2026-09-11).

### 5.8 Sonde étendue — balayage λ, Var(δ), contrôles (2026-09-13, suite 123)
- [x] `scripts/grad_signal_probe.py` : `--gae-lambdas` (GAE recalculé a posteriori, égal à SB3
      au 1e-6 sur chaque rollout, gradient policy repris avec la même permutation, différences
      appairées jackknife), décomposition Var(δ) par famille (`action_family`, phase lue dans le
      one-hot `global_bin`), `--model` / `--vec-normalize` (autre politique, son pkl, jamais
      celui du canonique), `--random-init SEED`, `--opponent-deterministic`. 24 tests, rouge/vert
      par mutation (GAE sans coupure d'épisode, identité de variance, ΔV, pkl du canonique,
      copies GPU du buffer, réinitialisation).
- [x] Piège attrapé par la vérification d'alignement : `GpuMaskableDictRolloutBuffer` uploade
      avantages/retours sur GPU une fois au premier `get()` ; `set_buffer_advantages` rafraîchit
      les deux exemplaires.
- [x] Quatre collectes (P1, contrôle 040721, contrôle aléatoire, P0 déterministe) ; résultats
      §0-4 et [training.md#signal-p1-lambda-2026-09-13](../../Roadmap/training.md#signal-p1-lambda-2026-09-13) ;
      implémentation indépendante (session 40k-a2) concordante, contrôle synthétique f = 0,667
      (plafond de l'instrument).
- Observation : une passe `--random-init` sur trois tuée par le moteur (`engine/w40k_core.py::_process_squad_action`, levée « execute_squad_move a échoué »,
  incohérence masque/exécution « collision intra-plan » pendant un tour bot) — état atteint par
  une politique aléatoire seulement ; bug hors chantier, consigné.

---

## 6. Ce qui n'a pas été fait

- [x] **Contrôle positif** de la sonde sur le chemin policy — fait le 2026-09-13 : le témoin
      entnorm_040721 ne discrimine pas (f = 0,006 comme P1) ; le contrôle à poids aléatoires
      (`--random-init`) rend f = 0,43 [0,27, 0,59] (C3, E4 fermés).
- [x] **Décomposition de Var(δ_t)** — faite le 2026-09-13 (C1) : Var(r) = 86 % de Var(δ),
      ρ(r, ΔV) = −0,55 ; S11 bornée par là.
- [x] **Balayage λ appairé** — fait le 2026-09-13 : f(λ=0) = 0,053 [0,036, 0,070] (C4, S10).
- [x] Sonde avec **P0 déterministe** — faite le 2026-09-13 : mêmes nombres (B4, S12).
- [ ] Température d'exploration (S9) — après la question de variance, pas avant.
- [ ] Récompense en espérance (S11).
- [ ] Tête Q / avantage moyenné (S14) ; distillation par recherche (S15, gelée).
- [ ] Ventilation des pénalités −97 (C5) ; déploiement auto à 0,50 (D4).
- [ ] Pool élargi dès P1 (S16) ; second scénario (S17).
- [ ] Aucun **run d'entraînement** n'a été relancé depuis l'arrêt du 2026-09-12 hors les deux bras
      entnorm ; aucun réglage n'a été retenu pour un tel run.

---

## 7. Décision en attente — arbitrage ouvert le 2026-09-13

**Problème.** Le gradient qui fait bouger la politique n'a plus de direction mesurable à 8 160
pas, alors que le critic apprend encore. On ne sait pas si c'est parce que le bruit des parties
cache un signal réel ou parce qu'il n'y a plus rien à gagner contre P0 avec cette récompense.
Les remèdes diffèrent : réduire la variance dans le premier cas, changer l'objectif ou la manière
d'apprendre dans le second.

- **A — Le plan du rapport du 2026-09-13** : horizon (S10), puis température (S9), puis
  récompense en espérance (S11), chacun jugé par la sonde. Gain : config seule pour les deux
  premiers. Coût : l'horizon serait jugé sous la résolution de la sonde, γ y est mal mesuré, et
  la cause n'est jamais établie.
- **B — Mesures appairées d'abord, puis le levier désigné** (S13) : une collecte de 24 rollouts
  exploitée en post-traitement — balayage λ 0,95 → 0, décomposition de Var(δ), contrôle positif —
  plus une seconde collecte contre P0 déterministe. Gain : ~40 min tranchent entre un réglage de
  λ et un changement de mécanisme ; la cause du bruit devient mesurée. Coût : extension de la
  sonde (options `--gae-lambdas`, `--model` / `--vec-normalize`, `--opponent-deterministic`,
  décomposition) et ses tests.
- **C — Ouvrir maintenant la distillation par recherche** (S15) : la recherche moyenne les dés
  par simulation, la politique est entraînée par supervision, plus de variance d'avantage. Gain :
  remède de principe. Coût : plusieurs semaines, clone d'état à ramener de 745 à ≤ 30 ms,
  ROADMAP_INDEX le gèle après J3.

**Recommandation : B.** Les mesures sont une sonde, pas un run, et elles décident entre un
changement de config et un chantier de plusieurs semaines. Règle écrite avant lecture :
- f_policy(λ = 0) > 0,1, intervalle excluant 0 → P1 relancé avec ce λ, 30 000 épisodes, jugé sur
  `03_selfplay/P0` ;
- f_policy(λ = 0) ≈ 0 mais f(contrôle positif) > 0 → l'instrument est sain, le bruit d'un seul
  pas noie le ΔQ restant : avantage moyenné (S14) ou recherche (S15), la décomposition disant si
  S11 vaut la peine avant ;
- f(contrôle positif) ≈ 0 → le chemin policy de la sonde est cassé, rien d'autre ne se décide ;
- dans toutes les branches, la température (S9) vient après la question de variance.

**B exécutée le 2026-09-13 (suite 123) — règle appliquée aux nombres.** f_policy(λ = 0) =
**0,053 [0,036, 0,070]** : exclut 0 mais cinq fois sous 0,1 → pas de run à ce λ. f(contrôle
040721) = 0,006 [−0,005, 0,017] ≈ 0, mais f(contrôle à poids aléatoires) = **0,43 [0,27, 0,59]**
→ l'instrument est sain ; c'est le contrôle choisi qui n'était pas positif (même profil que P1 à
30 points de holdout d'écart). Aucune des trois lignes ne s'applique telle quelle ; ce qui les
départage : à lot fixe, ni λ (‖G‖² × 3,4 mais f plafonne à 0,05, B_noise 147 000 pas) ni
l'adversaire déterministe (mêmes nombres) ne réduisent le bruit ; Var(δ) = 0,050 est à
l'échelle de Var(r) = 0,043 (ρ(r, ΔV) = −0,55, le critic anticipe la récompense façonnée),
portée par le tir (0,96) et le combat (0,7–0,8). Issue : la deuxième ligne par élimination —
**avantage moyenné**, S14 (tête Q) ou S15 (recherche) ; S11 bornée à 86 % de Var(δ) sans que sa
part exacte (Var(r − E[r∣s,a])) soit identifiable avant de l'implémenter.

**Décision restante (nouvel arbitrage à ouvrir) : S14 contre S15, et S11 avant ou non.** Ce
dossier ne le tranche pas.

**Complément de la session parallèle 40k-a2 (collecte `main.json`, même soir) — trois points
qui changent l'arbitrage ci-dessus.**

1. **Un levier de configuration reste non joué : λ court ET lot ×4 ensemble (S23).**
   L'élimination ci-dessus a testé λ à lot fixe (f plafonne à 0,05) et, le 2026-09-07, le lot
   ×4 à λ fixe (0,95, où le signal est indétectable). Elle n'a pas testé la combinaison, et les
   nombres mesurés la prédisent : f_B = 1 / (1 + B_noise / B) — c'est la définition même de
   B_noise, vérifiée sur les rollouts — donne à λ = 0,2 (B_noise 145 000 [69 000, 222 000]) et
   B = 32 640 : **f ≈ 0,18 [0,13, 0,32], dix fois aujourd'hui** ; à λ = 0,95 : ≈ 0,07, non
   distinguable de 0. Config `x1_lineage` : `gae_lambda` 0,2, `n_steps` 32 640, `batch_size`
   4 080, `target_kl` inchangé — les 8 mini-lots rendent la coupure KL à ~15 pas ≈ 2 epochs de
   tout le rollout (l'objection du 32ᵉ/128 de 2026-09-07 disparaît) ; risque VRAM du lot
   4 080 à revoir dès la première update (obs non résidentes depuis le 2026-09-07). Un run P1
   de 30 000 épisodes jugé sur `03_selfplay/P0` contre le plat à 0,59 coûte ~6 h et tranche si
   la lignée repart avant d'engager des semaines sur S14 / S15 ; s'il ne bouge rien avec
   f ≈ 0,18, le levier config est épuisé et S14 / S15 restent seuls.
2. **« S11 bornée à 86 % de Var(δ) » n'est pas une borne.** Var(r) / Var(δ) = 0,86 garde
   Var(E[r∣s,a]) (qu'une récompense en espérance conserve) et ignore la covariance : avec
   ρ(r, ΔV) = −0,55 ce rapport peut dépasser 1 sans que l'espérance retire quoi que ce soit
   (ΔV = −r/2 donne 4,0 pour 0 % retirable). La part retirable est Var(ε) + 2 Cov(ε, ΔV) avec
   ε = r − E[r∣s,a], inaccessible sans l'espérance ; la seule lecture solide de la table est que
   la part de transition seule (Var ΔV 0,065) dépasse Var δ (0,048–0,050).
3. **Le contrôle à poids aléatoires valide le code, pas le régime.** Une politique aléatoire a
   l'entropie maximale, et le signal par échantillon vaut p(1−p)·ΔQ²/σ² : son f = 0,43 vient
   du facteur p(1−p), que les politiques entraînées n'ont plus (têtes courtes à p ≈ 0,99). Le
   fait informatif est le témoin 040721 : entraîné, 30 points sous P1, aussi indétectable à
   λ = 0,95 — dans ce régime le gradient à long horizon d'une politique entraînée est sous la
   résolution quelle que soit sa marge de progrès, ce qui penche vers « noyé » plutôt que
   « stationnaire » pour P1, et soutient S23. Mesure à 20 min qui isolerait le facteur
   d'exploration : sonder le modèle **traité** entnorm (même code, entropie ×2–5 sur les têtes
   courtes) contre son témoin — `--model .../model_ArmageddonAgent_x1_entnorm.zip` — et lire si
   f monte avec l'entropie à ΔQ inchangé.

**Arbitrage proposé par 40k-a2 (à trancher par l'utilisateur) :** A — run P1 direct avec S23
(6 h, décisif) ; B — sonde à 32 640 d'abord (option `n_steps` à ajouter, ~80 min) puis run ;
C — S14 / S15 sans passer par le levier. Recommandation A : la prédiction repose sur une identité
vérifiée sur les données, B confirmerait ce que les nombres disent déjà, et C engage des semaines
sans savoir si un changement de config suffisait.

---

## 8. Références

- Runs : `tensorboard/x1_lineage_ArmageddonAgent_x1/run_20260912-065925` (P1) ;
  `tensorboard/x1_40k_ArmageddonAgent_x1_entnorm/` (contrôle) ;
  `tensorboard/x1_40k_entnorm_ArmageddonAgent_x1_entnorm/` (traité).
- Journaux : `training_x1_02-p01.log`, `curriculum.log`, `logs/entnorm_chain.log`,
  `logs/entnorm_control.log`, `logs/entnorm_treated.log`, `logs/entnorm_probe.log`,
  `logs/entnorm_vsP0.log`, `logs/holdout_x1_20260913.log`.
- Modèles : `ai/models/ArmageddonAgent_x1/model_ArmageddonAgent_x1.zip` (= `robust_0.9078`),
  `model_ArmageddonAgent_x1_P0.zip` (= `robust_0.8683`), `_P1.zip` et `_P2.zip` du 2026-09-11 ;
  `ai/models/ArmageddonAgent_x1_entnorm/model_ArmageddonAgent_x1_entnorm_20260913-040721.zip`
  (contrôle) et `model_ArmageddonAgent_x1_entnorm.zip` (traité).
- Instruments : `scripts/grad_signal_probe.py`, `scripts/family_entropy_probe.py`,
  `ai/patched_ppo.py` (tags `train/n_minibatches_done`, `train/entropy_loss_normalized`,
  `diag/grad_norm_*_mb0`, `diag/grad_share_policy_mb0`).
- Commits : `1acd59c87`, `e903c8c35`, `6571ac847` (seuils et siège, 2026-09-11) ; `e488d9c01`
  (suite 110) ; `fc9054cea` / `ec2c122ee` (entnorm) ; `d4ede63f0` (40 000) ; `6fc774530` (`_doc`
  x1_lineage) ; `a4c693c38` (résultats entnorm + holdout) ; `663d7b867` / `c4d2a6039` (sonde de
  signal, suite 122).
- Docs : [training.md#entropie-normalisee](../../Roadmap/training.md#entropie-normalisee),
  [training.md#regime-lignee-2026-09-07](../../Roadmap/training.md#regime-lignee-2026-09-07),
  [training.md#signal-p1-2026-09-13](../../Roadmap/training.md#signal-p1-2026-09-13),
  [training.md#regime-2026-09-06](../../Roadmap/training.md#regime-2026-09-06),
  [training.md#holdout-2026-09-11](../../Roadmap/training.md#holdout-2026-09-11),
  [training.md#holdout-2026-09-13](../../Roadmap/training.md#holdout-2026-09-13),
  [mcts.md](mcts.md) (S15), `config/agents/ArmageddonAgent_x1/curriculum.json` (`_doc` de P2 :
  historique des essais d'hyperparamètres), `_doc` du profil `x1_lineage`.
