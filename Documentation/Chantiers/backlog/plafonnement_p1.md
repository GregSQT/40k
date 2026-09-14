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
`batch_size` 1020 → **2040**. Commande habituelle (`python3 ai/train.py --agent
ArmageddonAgent_x1 --training-config x1_lineage --scenario bot --etape P1`), 30 000 épisodes
(~6 h), à juger sur la courbe `03_selfplay/P0`, aujourd'hui plate à 0,59.

**Pourquoi 2 040 et pas 4 080 — mesuré le 2026-09-13 au soir sur la vraie politique et de
vraies observations** (48 états d'un moteur, tuilés ; un forward + backward comme dans
l'update) : la mémoire GPU d'un lot croît linéairement, 1,47 Go alloués (1,92 réservés) à
1 020, 2,88 (3,80) à 2 040, **5,69 Go alloués et 7,47 Go réservés à 4 080** — sur une carte de
8,19 Go dont l'hôte Windows prend 0,5 à 2,4 Go selon le moment : le lot de 4 080 replante
comme le 7 septembre. À 2 040 il reste plus de 2 Go de marge dans le pire cas. **La RAM de la
VM ne craint rien** : le buffer d'observations passe de 0,93 Go à 3,72 Go (119 Ko par
observation, 32 640 observations), plus autant en transit au retour des 24 workers, soit ~7,5 Go
de pic pour 35 Go disponibles ; la garde d'`apply_rollout_n_steps` refuse de toute façon un
buffer au-delà de la moitié de la mémoire libre (le « 44 Go qui tuaient la VM » étaient
393 216 observations, douze fois plus). Avec 2 040, le rollout fait 16 mini-lots ; la coupure
KL à ~15 pas couvre alors une epoch entière du rollout, et la prédiction f ≈ 0,18 porte sur le
gradient du rollout complet (32 640), pas sur la taille du mini-lot.

**Décision prise le 2026-09-13 : run lancé dans la nuit du 13 au 14 — RÉFUTÉ (§5.9) : `03_selfplay/P0`
chute 0,50 → 0,41 en 8 000 épisodes, arrêté à 02:22. Lecture : λ change aussi la cible du critic.**
**2026-09-14 : essai `vf_coef` 0,3 (§5.10) RÉFUTÉ — même plateau 0,585 que la référence, atteint
plus lentement. Run S11 (§5.11, récompense de tir et de mêlée en espérance) ARRÊTÉ par la garde à
20 000 : argmax 0,47 contre P0 alors que l'agent échantillonné tient 0,55 et que l'entropie
monte. Suivant : terme de marge de VP B6 (§5.12, second avis), sur le régime de référence.**

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
  jamais vus, déplacement de politique ×3,8 plus lent par épisode (`target_kl` plafonne l'update ;
  horloge inchangée, ~126 s par 32 640 pas) ; `batch_size` 4 080 : crash VRAM (8,89 Go / 8,19).
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
| A3 | Learning rate inadapté | pas trop grand (désapprend) ou trop petit (n'avance pas) | ☐ **ROUVERT le 2026-09-14 soir (§9.2)** | l'argument « amplitude d'une direction qui n'en est pas une » ne vaut que pour une update, pas pour un run ; FAIT : le zip P0 porte lr 0,0005 (fin de rampe), `x1_lineage` reprend à 0,001 — une politique convergée reprise au double de son lr ; coupure KL à 11–16 mini-lots sur 32 sur les deux runs qui publient le compteur ; jamais testé isolément (le lr ×2 du 2026-09-06 était mêlé à trois autres leviers) |
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
| D6 | Moteur modifié pendant la lignée (35 commits entre les holdouts) | références invalidées | ☑ acté, pas une cause du plateau ; **complété §9.1 : le seuil 0,65 a été posé le 09-11 sur un jeu où P1 faisait 0,713** | P0 et P1 jouent le même moteur ; seules les comparaisons avant/après sont interdites — et la référence 0,713 (curriculum.log ligne 10, autre P0, autre observation) n'est PAS comparable au 0,60 actuel ; le seul point de référence valide est ce qu'un exploiteur atteint MAINTENANT (S25) |

### E. Mesure et critère

| # | cause | mécanisme | statut | preuve / observation |
|---|---|---|---|---|
| E1 | Sonde argmax contre argmax : blocs corrélés | ±5 points entre sondes voisines | ☑ connu, traité | décision sur la moyenne de 3 sondes ; graines tirées au hasard depuis le 2026-09-07 |
| E2 | Seuil 0,65 hors de portée de ce dispositif | le même dispositif promouvait à 0,55 | ☑ fait établi ; ✗ **baisser le seuil écarté par décision** (2026-09-12), **réaffirmé le 2026-09-14 soir (§9.4)** | §1.4 ; un seuil abaissé promeut un agent qui n'apprend plus ; 0,65 est un seuil de CONFIRMATION de domination, le plafond attendu contre P0 est ~0,90 — « plateau normal d'un self-play » est écarté |
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
| G1 | P1 = P0 + entraînement contre lui-même : +10 points puis limite de ce que PPO extrait d'un adversaire identique avec des dés | le gain marginal tombe sous le bruit | ☐ non distingué de C1 / C3 ; **la lecture « limite normale » est écartée par décision (§9.4) ; le plafond réel se mesure par S25** | 0,50 → 0,60 en 40 000 épisodes puis plat ; reproductible (P1 du 2026-09-11 : 0,561 à 30 000) |

---

## 4. Solutions possibles — inventaire et statut

| # | solution | cause visée | statut | coût | observation |
|---|---|---|---|---|---|
| S1 | `n_steps` × 4 (32 640) | A1 | ☑ testée (P2, 2026-09-07) → ✗ | config | coupure KL au 32ᵉ/128, déplacement par épisode ×3,8 plus lent (horloge inchangée) ; mesure du 2026-09-13 : ×44 serait le minimum |
| S2 | `batch_size` 4 080 | A1 | ☑ testée → ✗ | config | crash VRAM (8,89 Go) ; VRAM libérée depuis (obs non résidentes), mais levier réfuté par f |
| S3 | `target_kl` relevé / `n_epochs` | A2 | ✗ écarté | config | 0,03 prendrait des pas de 0,045 nat hors région de confiance ; direction = bruit |
| S4 | `learning_rate` | A3 | ✗ écarté | config | idem ; antécédent de destruction |
| S5 | `vf_coef` 0,5 → 0,17 | A6 | ☑ livrée (2026-09-07) ; **0,3 testé le 2026-09-14 → résultat NUL dans le bruit (§5.10, requalifié §9.3 : une graine, sonde ±2,9 pts, blocs ±5 — ce n'est pas une réfutation)** | config | part policy 0,62, EV intacte ; aucun effet sur le plateau ; question rouverte par l'utilisateur : à 0,17 le tronc partagé est façonné à 62 % par un gradient qui est du bruit à 98 % |
| S6 | `max_grad_norm` 2,0 | A5 | ☑ testée (2026-09-06) → instrument seulement | config | redescendu à 0,5 ; norme brute publiée depuis |
| S7 | Régime scalaire de lignée (lr 0,001, ent_coef 0,01) | rampes reparcourues | ☑ livrée (2026-09-07/08) | config + code | a stoppé les destructions ; n'a pas produit de progression au-delà de 0,60 |
| S8 | Entropie normalisée par l'état + `ent_coef` × 5 | B1, B2 | ☑ testée (2026-09-12/13) → **sans effet** | code + agent dédié, 2 runs (11 h 44) | exploration ×2–5 sur têtes courtes ; holdout +0,4 pt, vs P0 −6 pts, dans le bruit ; clé conservée, désactivée par défaut |
| S9 | Température des logits (T ≈ 2) à la collecte **et** dans le ratio PPO, T = 1 en évaluation | B1, B3 | ☐ envisagée (rapport du 2026-09-13, option C) | code (`_action_logits`, côté workers comme `evaluate_actions`) | nécessaire pour charge/pose, insuffisante seule ; ajoute de la variance : à mesurer **après** la question C1 |
| S10 | `gae_lambda` 0,95 → 0,8 / 0,5 / 0,2 / 0 ; `gamma` 0,97 | C1, C4 | ☑ **λ mesuré a posteriori (2026-09-13) → ✗ comme levier seul** | config | f(λ=0) = 0,053 [0,036, 0,070] < 0,1 : le critère écrit pour relancer P1 à ce λ n'est pas atteint ; γ non balayé (critic à 0,99) |
| S11 | Récompense en **espérance** pour tir et mêlée (dés joués pour la partie, récompensés sur la valeur attendue) | C1, C6 | ☑ **testée le 2026-09-14 → ✗ garde de destruction** (argmax 0,47 vs P0, échantillonné 0,55, entropie montante ; §5.11) | moteur + contrat d'entraînement | borne : Var(r) = 86 % de Var(δ), portée par tir (0,96) et combat (0,7–0,8) ; la part exactement retirée, Var(r − E[r∣s,a]), n'est pas identifiable sans l'espérance (ΔV dépend aussi du dé) |
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
| S24 | **Marge de VP** (B6) : `vp_margin_factor × Δ(VP_moi − VP_lui)` en ledger, à la place de `objective_reward_factor × VP_propres` ; échauffement du critic `value_warmup_updates` | C1, C5 | ☑ **code livré et mergé le 2026-09-14 (§5.12) ; contrat, profil et run à faire** | moteur + tracker + PPO + contrat | somme téléscopique = 6 × marge finale ; les VP concédés coûtent −6 chacun (0 avant) ; Corr(ΔVP_moi, Δmarge) = 0,82 sur 40 parties → additionner les deux termes aurait fait +11 / −5, rejeté |
| S23 | **λ court ET lot ×4 ensemble** : `gae_lambda` 0,2, `n_steps` 32 640, `batch_size` 2 040 (16 mini-lots, `target_kl` inchangé) | C1, C4, A1 | ☑ **testée (2026-09-14, §5.9) → ✗ détruit** : 0,50 → 0,41 en 8 000 épisodes ; λ change la cible du critic, la prédiction f supposait le critic fixe | config `x1_lineage`, 5 lancements (3 tués par la RAM, 1 correctif de collecte, 1 jugé) | f attendu ≈ 0,18 [0,13, 0,32] contre 0,018 aujourd'hui (f_B = 1 / (1 + B_noise / B), B_noise(λ = 0,2) = 145 000 [69 000, 222 000]) ; ni λ seul ni lot seul n'ont été testés ensemble ; VRAM mesurée : 3,80 Go réservés à 2 040, 7,47 à 4 080 (replanterait) ; RAM buffer 3,72 Go |

---

| S25 | **Exploiteur de P0, meilleur cas** : agent dédié (copie de config, curriculum réduit à P0 + E0 ciblant P0), reprise de P0, 100 % P0, adversaire déterministe, siège 0,5, lr 0,0005, 60 000 épisodes, sonde argmax habituelle | plafond (E2, G1, D6) | ⏳ **désignée §9.5, à lancer sur décision** | config seule (agent dédié comme `ArmageddonAgent_x1_entnorm`) + copie du zip P0 | mesure le meilleur cas sans attribution ; verdict ≥ 0,68 → bissecter avec P1 (lr, déterminisme, siège, bots) ; plat ~0,60 → le mécanisme d'apprentissage est le goulot, pas le gate, et S9 / deux λ / S14 / S15 se jouent dans CE dispositif (le plus lisible) |
| S26 | **lr de reprise 0,0005** (valeur finale de P0) au lieu de 0,001 dans `x1_lineage` | A3 | ☐ à tester, second bras de S25 seulement si S25 ≥ 0,68 | config | jugé d'abord par `train/n_minibatches_done` (attendu : 32 sur 32), puis par `03_selfplay/P0` à UPDATES égales |
| S27 | **Mesures statiques par siège** (aucun entraînement) : P0 argmax vs P0 argmax, P0 échantillonné vs P0 argmax, P1 (`robust_0.9078`) vs P0, 300 parties par cellule et par siège | E1, D3 | ⏳ **désignée §9.5, à faire d'abord** | script lecture seule | dit quelle part du 0,60 est structurelle (siège, dés) ; mesure partielle existante à 40 parties (siège 1 : 6/15, siège 2 : 16/25) dans le sens INVERSE de l'écart de siège holdout — non concluante à ce n |

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
      one-hot `global_bin`), `--model` (autre politique, son pkl compagnon, jamais celui du
      canonique), `--random-init SEED`, `--opponent-deterministic`. 24 tests, rouge/vert
      par mutation (GAE sans coupure d'épisode, identité de variance, ΔV, pkl du canonique,
      copies GPU du buffer, réinitialisation).
- [x] Piège attrapé par la vérification d'alignement : `GpuMaskableDictRolloutBuffer` uploade
      avantages/retours sur GPU une fois au premier `get()` ; la première version rafraîchissait
      les deux exemplaires (`set_buffer_advantages`).
- [x] Simplification après /simplify (2026-09-13, après les quatre collectes) : pertes policy des
      λ supplémentaires prises dans la même passe avant que les quatre termes (plus de seconde
      passe `get()` par λ, plus de mutation du buffer, `set_buffer_advantages` supprimé) ;
      `gae_advantages` délègue à `RolloutBuffer.compute_returns_and_advantage` de SB3 ; le λ du
      modèle est toujours balayé (`--gae-lambdas` = λ supplémentaires, défaut `0.8,0.5,0.2,0`) ;
      `f_batch_of` / `true_sq_of` partagés entre `signal_stats` et les différences appairées ;
      `check_control_acceptance` réutilise `check_acceptance(keys=…)`. 24 tests, rouge/vert par
      mutation (normalisation oubliée pour le balayage).
- [x] Revue de la sonde (2026-09-13, suite 124) — quatre trous fermés, aucun nombre publié ne
      change : (1) `--model` comparé par chemin RÉSOLU (`ai/models` est un lien symbolique dans
      les worktrees : le canonique orthographié par son realpath passait pour un contrôle) et le
      canonique refusé en `--model` ; `--vec-normalize` retiré — chaque zip a son pkl compagnon
      (contrat 115), un autre pkl ne mesure rien. (2) « 0 épisode sans vainqueur » était un garde
      mort : le moteur pose `winner = DRAW_WINNER` à sa limite anti-runaway ; la sonde lit
      `info["TimeLimit.truncated"]` (comme `ai/training_callbacks`) et S'ARRÊTE sur toute
      troncature, sur chaque rollout (faux nul + bootstrap replié dans la récompense du dernier
      pas → Var(r) faussée). (3) `--opponent-deterministic` jugé sur la plomberie, plus sur les
      bornes du run de référence (autre adversaire) ; mode écrit dans le JSON (`acceptance.mode`).
      (4) `vf_coef` / `ent_coef` du checkpoint mesuré rapportés (`model_hyperparams`, en-têtes
      des termes) — un contrôle a les siens. Doc : « part r » est descriptive, pas la part
      retirable par une récompense en espérance (déjà rétracté §7) ; parts rendues nan quand
      Var(δ) est un résidu d'arrondi. 26 tests, rouge/vert par mutation (realpath zip et pkl,
      plancher, troncature, vainqueur None).
- [x] Quatre collectes (P1, contrôle 040721, contrôle aléatoire, P0 déterministe) ; résultats
      §0-4 et [training.md#signal-p1-lambda-2026-09-13](../../Roadmap/training.md#signal-p1-lambda-2026-09-13) ;
      implémentation indépendante (session 40k-a2) concordante, contrôle synthétique f = 0,667
      (lu « plafond de l'instrument » ; c'est un estimateur du gradient d'entropie, dépendant de
      la politique — non repris).
- [x] Arbitrage des deux implémentations (2026-09-13, suite 125) : main gardée (GAE par SB3,
      familles lues comme le moteur, trous de la revue fermés) ; repris de 40k-a2 les stats par
      groupe pour chaque λ (`per_lambda[λ][groupe]`, celles citées dans training.md à λ = 0) et
      la garde `model._last_episode_starts == dones[-1]` ; branche et worktree 40k-a2 supprimés.
- [x] /simplify (2026-09-13, suite 125, quatre angles) : une seule famille d'accumulateurs
      indexée par clé de backward (les quatre termes puis les λ, plus de jumeaux `sweep_*`),
      `group_grams` partagé, `lambda_sweep_stats` reprend les stats déjà calculées (plus de
      recalcul du λ du modèle), mode d'acceptation décidé une fois dans le contexte
      (`acceptance.mode` + `PLUMBING_ACCEPTANCE_KEYS`, wrapper supprimé), troncature levée dans
      le recorder lui-même, `load_vec_normalize` réutilisé, `model_hyperparams` porté par le seul
      `context`. Écarté : gradients des six pertes « ratio » en un seul backward vectorisé
      (`is_grads_batched`, −30 à −50 % estimés sur la phase gradients) — change le chemin autograd
      de l'instrument publié, à mesurer avant d'adopter. 26 tests, mutation rouge/vert (stats par
      groupe, troncature).
- [x] Go/no-go du backward vectorisé (2026-09-13, suite 126) — **abandonné sur mesure**. Sur le
      code actuel (1 passe avant + 8 backward par mini-lot : 4 termes + 4 λ), 3 rollouts P1
      réels (`--rollouts 3`, canonique, `x1_lineage`) : collecte 37,6 / 32,8 / 30,4 s, gradients
      7,2 / 6,7 / 6,8 s → phase gradients = 16,1 / 16,9 / 18,3 % du rollout, 17,0 % cumulé
      (20,7 s sur 121,5 s). Critère fixé avant la mesure : ne vectoriser que si ≥ 25 %. Borne
      haute du gain (−6/8 des backward, tout le reste inchangé) ≈ 5 s par rollout, ≈ 2 min sur
      une collecte de 24 ; changer le chemin autograd de l'instrument publié ne vaut pas ce gain.
      Rappel : à cotangentes empilées, un vjp batché fait les mêmes FLOPs de gradient de poids
      que 6 backward séparés — le gain ne viendrait que du nombre de lancements de kernels.
- Observation : une passe `--random-init` sur trois tuée par le moteur (`engine/w40k_core.py::_process_squad_action`, levée « execute_squad_move a échoué »,
  incohérence masque/exécution « collision intra-plan » pendant un tour bot) — état atteint par
  une politique aléatoire seulement ; bug hors chantier, consigné.

---

### 5.9 Run S23 — λ 0,2 + rollout 32 640 / lot 2 040 (nuit du 2026-09-13 au 14) — RÉFUTÉ

**Config** : `x1_lineage` `gae_lambda` 0,2, `n_steps` 32 640, `batch_size` 2 040 (commit `5744e9d66`),
tout le reste inchangé ; commande habituelle `--etape P1`, reprise de P0 (`robust_0.8683`).
Règle §7 complétée avant le lancement (branches d/e, validées).

**Cinq lancements.** Le rollout ×4 a d'abord été un problème de RAM, pas de GPU :

| tentative | envs | issue | RAM disponible min (VM 39 Go) |
|---|---|---|---|
| 1 (23:14) | 24 | tuée par le watchdog à 23:39, 6 updates faites | 1 Go, swap 9 Go |
| 2 (23:42) | 16 | tuée à 23:51, pendant le 1ᵉʳ rollout | 2 Go |
| 3 (23:55) | 12 | tuée à 00:08, pendant le 1ᵉʳ rollout | 2 Go (workers 20,8 Go) |
| 4 (00:14) | 12, **correctif de collecte** (`a59ff5a61`) | arrêtée à 00:47 pour passer à 8 envs | 4 Go (learner 3,5 Go en régime, 7,3 au pic) |
| 5 (00:47) | 8 | **jugée**, arrêtée par l'utilisateur à 02:22 | 7 Go (learner max 7,6 Go, workers 17,4 Go) |

Cause mesurée (séries à 10 s, `mem_s23_*.tsv`) : chaque worker garde sa trajectoire en listes de
blocs de 104 Ko puis `np.stack` (deux exemplaires au pic, blocs jamais rendus au tas : 0,9 → 1,7 Go
de RSS par worker à 32 640 pas) ; le learner recevait la **liste complète** des trajectoires, les
empilait (`obs_all`), puis remplissait le buffer pas à pas — **trois exemplaires** des
observations (3 × 3,4 Go). Le coût RAM d'un rollout est proportionnel au rollout **total**, pas au
nombre d'envs : baisser `n_envs` ne rend que la base par worker. Correctif : tableaux préalloués
côté worker, `iter_trajectories` côté learner (chaque trajectoire copiée dans le buffer à la
réception puis libérée) ; verrou `TestDistributedRolloutObservationsLandInBuffer`, rouge/vert par
mutation (steps inversés, obs non libérées). Le 4 080 de VRAM n'a jamais été atteint : 7,3–7,7 Go
réservés à 2 040 sur 8,19, sans erreur CUDA.

**Résultat (tentative 5, `run_20260914-004747`, 8 340 épisodes d'étape, 26 updates).** Parité
d'ouverture 0,490. Plomberie conforme : `n_steps` 4 080 par env, buffer reconstruit,
`train/n_minibatches_done` 21–44 sur 64 (rollout vu en entier, 1,3 à 2,8 epochs),
`train/time_update` 11–13 s.

| tranche d'épisodes d'étape | 0–1k | 1–2k | 2–3k | 3–4k | 4–5k | 5–6k | 6–7k |
|---|---|---|---|---|---|---|---|
| `03_selfplay/P0` (≈ 700 parties/tranche) | 0,498 | 0,506 | 0,500 | 0,461 | 0,459 | 0,410 | 0,422 |
| `game_critical/win_rate_overall` | 0,612 | 0,603 | 0,601 | 0,591 | 0,586 | 0,576 | 0,568 |
| `01_VP/a_vp_diff` | 5,36 | 5,17 | 5,64 | 4,06 | 4,53 | 1,73 | 2,25 |
| `s_win_rate_deploy_active` | 0,618 | 0,607 | 0,610 | 0,562 | 0,582 | 0,527 | 0,535 |

Référence (`run_20260912-065925`) sur [0, 10 000) : 0,508. Ici 0,457 sur [0, 8 340), **monotone
décroissant** (erreur-type par tranche ≈ 0,02 : la chute vaut 5 écarts-types). Pendant la chute :
`train/explained_variance` 0,973 → 0,980, `train/value_loss` 0,055 → 0,032, `approx_kl` 0,006–0,014,
`clip_fraction` 0,06–0,10, `entropy_loss` −0,79 → −0,73 (stable), `grad_share_policy_mb0` 0,67–0,79.

**Lecture.** La prédiction f ≈ 0,18 (§7, complément 40k-a2) était mesurée **a posteriori** sur des
rollouts collectés avec le critic entraîné à λ = 0,95 : elle décrit l'avantage de l'acteur à critic
fixe. Dans un run, λ change aussi la **cible du critic** (SB3 : `returns = advantages + values`) ; à
0,2 le critic apprend quasi TD(0) en bootstrap sur lui-même, son EV de 0,98 est auto-référentielle
(la cible est presque sa propre prédiction), et la politique suit un critic qui dérive. La branche
(e) de la règle (« λ court biaise vers le proxy du critic ») est le bon verdict, mais son mécanisme
est la dérive de la cible, pas un biais de direction mesurable sur ce checkpoint : une sonde de
cosinus sur un critic dérivé ne mesurerait rien, elle n'a pas été faite. Fenêtre < 20 000, donc
verdict rendu **par l'utilisateur** sur la monotonie, pas par la règle ; le run se serait détruit
seul à 20 000 (garde < 0,50).

**Ce que S23 ferme.** Le levier config « nettoyer le gradient par λ et le lot » : λ long = bruit
(f 0,018), λ court partout = critic cassé. Reste ouvert, non testé : **λ court pour l'avantage de
l'acteur seul, λ long pour la cible du critic** (deux jeux d'avantages dans le buffer) — le crédit
propre d'un mouvement est V(s′) − V(s) (12 % de dés) et il est noyé à λ 0,95 sous les dés des tirs
suivants (95,5 %). À dimensionner, décision utilisateur requise avant code.

**Correction de lecture, même nuit.** « Le tir est du dé » (§0-4, §5.8) est faux comme résumé : le
tir est une optimisation d'espérance (arme × cible, portée, figurines) que l'agent a **acquise**
(têtes de tir à p ≈ 0,99, 90 % contre les bots). Ce qui est du dé, c'est l'écart entre l'espérance
qu'il a apprise et le jet qu'il reçoit comme récompense — 95,5 % de la variance du signal d'un tir.
D'où S11 (§5.11) : récompenser le choix sur son espérance, pas sur le jet. Et `move_cell` n'est pas
« aléatoire » : 2,23 nats sur ln 194 = 5,07, soit ~9 cases sérieuses sur 194 ; c'est la seule tête
qui hésite encore, et la seule dont le crédit propre n'est pas du dé.

### 5.10 Essai `vf_coef` 0,3 (2026-09-14, décision utilisateur) — RÉFUTÉ

Profil ramené au régime de référence (`n_steps` 8 160, `batch_size` 1 020, λ 0,95, 24 envs, commit
`467eff961`), seule différence `vf_coef` 0,17 → 0,3. Commande habituelle, `training_x1_04-p01-vf030.log`,
lancé 02:36, parité d'ouverture à lire. Question posée : S5 a réglé « le critic étouffe la
politique » (0,5 : 75 % du tronc) ; à 0,17 le tronc partagé reçoit 62 % de son gradient d'une
politique dont le gradient est du bruit à 98 %, alors que le critic a un signal réel (f = 0,27).
0,3 n'est pas calibré : c'est un essai entre les deux valeurs mesurées. P0 a été entraîné à froid à
0,17 (90 % contre les bots) : 0,17 n'empêche pas d'apprendre ; la question porte sur la reprise à
chaud contre un adversaire de même niveau. Jugement par la règle §7 (moyenne de `03_selfplay/P0`
sur 20 000–30 000 contre 0,585–0,595 ; garde de destruction à 20 000).

**Résultat (`run_20260914-023713`, 02:36 → 10:26, ~48 000 épisodes d'étape, arrêté par
l'utilisateur).** Parité d'ouverture 0,520.

| fenêtre d'étape | [0, 10k) | [10k, 20k) | [20k, 30k) | [30k, 40k) | [40k, 50k) |
|---|---|---|---|---|---|
| référence 0,17 (`run_20260912-065925`) | 0,508 | 0,571 | 0,601 | 0,592 | 0,585 |
| `vf_coef` 0,3 | 0,509 | 0,519 | 0,572 | 0,577 | 0,585 (5 630 pts) |

Sondes `pool_eval/vs_P0` : 0,493 (10 000) / 0,580 (20 000) / 0,587 (30 000, moyenne 0,553) /
0,570 (40 000, moyenne 0,579) — promotion jamais approchée. `diag/grad_share_policy_mb0` 0,47
(0,62 à 0,17), `explained_variance` 0,88, `n_minibatches_done` 11–16 sur 32, RAM min 5 Go aux
sondes (24 envs + 2 workers d'évaluation).

**Verdict.** À 30 000 : < 0,62 et montante → branche (d), laissé courir ; à 48 000 il a
**rejoint exactement le plateau de la référence (0,585)**, en y arrivant 3 points plus lentement
sur chaque fenêtre. Un critic mieux servi ne déplace pas le plafond : `vf_coef` n'en est pas la
cause, et le tronc partagé « façonné par le bruit » non plus, puisque lui donner plus de signal
critic (part policy 0,62 → 0,47) ne change rien au jeu. 0,17 rétabli. S5 reste « livrée, aucun
effet sur le plateau », désormais dans les deux sens.

### 5.11 S11 — récompense en espérance pour tir et mêlée (2026-09-14, décision utilisateur) — RUN ARRÊTÉ PAR LA GARDE

Principe : le moteur jette les dés pour la partie (la cible perd ses PV selon le vrai jet), mais la
récompense versée à l'agent pour un tir ou une mêlée est calculée à partir de l'espérance de son
choix (arme × cible : touche × blessure × sauvegarde × D, `engine/weapon_damage_cache.py::squad_expected_damage`,
source unique déjà utilisée par les bots). Même choix → même récompense. Objectifs, pénalités et
issue ±150 restent sur le vrai résultat. Bonus de kill (2,0) : en espérance aussi (proportionnel
aux dégâts espérés rapportés aux PV d'une figurine), sinon il reste le terme dominant et bruité du
tir. Clé de config pour l'activer (le run de référence reste rejouable).

**Livré le 2026-09-14 à 03:45 (worktree `worktree-s11-reward-esperance`, commit `f626a786e`, à
merger après le jugement de vf_coef — les workers d'évaluation rechargent le code de main).**
- `engine/phase_handlers/attack_sequence.py::expected_attack_pool_damage` : espérance EXACTE de
  `roll_attack_pool` + comparaison de sauvegarde, par faces, relances d'abilités (`RerollProfile`),
  plancher 10.07, [SUSTAINED]/[LETHAL]/[DEVASTATING]/[TWIN-LINKED]/[TORRENT]. Verrou :
  `tests/unit/engine/test_expected_attack_pool_damage.py` — égalité avec `expected_damage_per_attack`
  sans relance (28 cas), **Monte-Carlo contre le roller lui-même** (10 cas × 40 000 attaques,
  tolérance 0,015), rouge par mutation (relance de touche, de sauvegarde, plancher ignorés).
- `shared_utils.py::intent_expected_damage` : appelée par les DEUX rollers (tir et mêlée) sur les
  mêmes seuils, profil et relances que `roll_attack_pool` ; dégât = E[min(D + bonus, HP_MAX)] avec
  le HP_MAX du profil de base (`units_cache`), FNP d'unité (facteur P(aucun seuil ne sauve)) ;
  NB en espérance quand le roller de tir le tire, nombre résolu sinon. Sommée par cible dans
  `summary["expected_damage_by_target"]` ; `targets_meta[sid]` porte `alive_count`, `hp_max`,
  `points_per_hp_mean` (= VALUE / (effectif initial × HP_MAX)), `model_value_mean`. Aucune
  lecture par figurine (une première version lisait la première figurine vivante : 56 fixtures
  sans `UNIT_RULES`/`points_per_hp` la refusaient ; les caches d'escouade sont la source).
- `reward_calculator.py::_squad_combat_shaping` : clé OBLIGATOIRE `squad_shaping.reward_on_expectation`
  (booléen, ajoutée à `false` dans les deux rewards_config) ; à `true`, dégâts = points_par_PV_moyen
  × hp_w × E[dmg] et kills = min(E[dmg] / HP_MAX, vivantes) × valeur_moyenne × kill_f (proxy
  linéaire assumé) ; wipe sur le résultat réel ; côté défensif (pénalité des tirs adverses) par la
  même fonction. Verrou : `TestS11RewardOnExpectation` (7 tests), rouge par mutation (plafond des
  kills, drapeau ignoré). Vrai chemin : `test_shoot_attack_sequence.py` (3 tests S11 : même choix →
  même espérance 0,25 que le jet réussisse ou rate ; plafond par les PV).
- Approximations assumées (docstring) : escouade vue comme son profil de base (leader attaché non
  distingué), FNP positionnel d'une figurine (Unbreakable Resolve) hors espérance, [DEVASTATING]
  avec le même facteur FNP, NB pré-tiré conditionné (tir fractionné, mêlée).
- Mesure de S11 : PAS de nouveau composant de breakdown (aurait touché `REWARD_BREAKDOWN_COMPONENTS`,
  le tracker et ses verrous) ; l'instrument existant suffit — `scripts/grad_signal_probe.py` sur le
  checkpoint S11 contre celui de P1 : Var(δ) par famille (tir 0,115 aujourd'hui) et f.
- Constat hors sujet, prouvé sur HEAD avec les modules d'origine : **57 tests rouges préexistants**
  (`test_precision.py`, `test_weapon_rule_log_tokens.py` 29, `test_weapon_value_no_silent_fallback.py` 7,
  `test_fight_special_rules.py` 6, `test_special_rules_e2e.py` 5, `test_melta_shoot.py` 3,
  `test_squad_shoot_log_dead_target_position.py` 3) : `_resolve_one_manual_wound` → `_collect_fnp_thresholds`
  → `_model_rules_view` exige `UNIT_RULES` sur la figurine blessée depuis `2693007f2`, et ces fixtures
  n'en portent pas. Identiques avec et sans S11 (listes comparées) ; non corrigés ici.

**Deux refus au lancement, corrigés.** (1) Le contrat d'entraînement (`ai/training_contract.py`)
refuse de reprendre P0 avec une table de récompense dont les clés ont changé : réécrit sciemment
pour le snapshot P0 et le canonique (`write_contract`, même espérance de récompense par
construction — l'espérance a la moyenne du jet). (2) Le run est mort à sa première activation de
tir : `_build_target_meta` lisait `units_cache[sid]["HP_MAX"]`, présent dans toutes les doublures
de test et **absent en production** (`units_cache` ne porte que `HP_CUR`) — code testé mais jamais
appelé sur le vrai chemin. Corrigé (`_target_base_hp_max` : HP_MAX de la première figurine vivante
du `models_cache`) et verrouillé par `tests/unit/engine/test_s11_reward_on_expectation_e2e.py` :
partie réelle (`W40KEngine` + `BotControlledEnv`, actions légales au hasard, espion sur
`calculate_reward`), résumés complets sur de vraies figurines, `result_bonuses` de chaque tir de
l'agent = formule sur l'espérance, ≠ formule sur les événements ; rouge par réintroduction du défaut.

**Run S11 lancé le 2026-09-14 à 11:00** : S11 mergé dans main (`296c1bc3d` + correctif),
`reward_on_expectation: true` dans `ArmageddonAgent_x1_rewards_config.json`, profil de référence
(`vf_coef` 0,17 rétabli), commande habituelle `--etape P1`, `training_x1_05-p01-s11.log`. Seule
différence avec `run_20260912-065925` : la récompense de tir et de mêlée est l'espérance du choix,
plus le jet. Jugé par la règle §7 (moyenne de `03_selfplay/P0` sur 20 000–30 000 contre 0,601 /
plat 0,585 ; sondes ; garde à 20 000).

**Résultat (`run_20260914-103745`, 10:37 → 14:05, 20 000 épisodes d'étape, 272 updates) : arrêté
par la garde de destruction** — sondes contre P0 (argmax des deux côtés) 0,450 à 10 000 et 0,497 à
20 000, moyenne 0,473 < 0,50. Parité d'ouverture 0,463.

| fenêtre d'étape | [0, 10k) | [10k, 20k) | sonde 10k | sonde 20k |
|---|---|---|---|---|
| référence 0,17 | 0,508 | 0,571 | 0,547 | 0,533 |
| S11 | **0,538** | 0,549 | **0,450** | 0,497 |

Le paradoxe est le fait principal : la courbe d'entraînement (agent **échantillonné** contre P0
stochastique) est au niveau ou au-dessus de la référence (par tranche de 2 000 : 0,530 / 0,523 /
0,536 / 0,540 / 0,559 / 0,525 / 0,550 contre 0,468 / 0,504 / 0,523 / 0,509 / 0,523 / 0,554 /
0,566), les courbes de jeu sont saines et montent (`win_rate_overall` 0,616 → 0,624, kills 10,4 →
11,1, `damage_efficiency` 3,16 → 3,58, `episode_reward` 373 → 400, EV 0,88), mais la politique
**argmax** perd contre P0 argmax. Symptôme distinctif : **l'entropie monte** — `train/entropy_loss`
−0,78 → −0,85 par quart (référence : −0,78 → −0,72, elle **descend**), `entropy_loss_normalized`
−0,46 → −0,52, `policy_gradient_loss` −0,004 → −0,007, KL et clip_fraction inchangés.

**Lecture (hypothèses, non prouvées).** L'espérance rend les avantages de tir *honnêtes* : deux
cibles d'espérance voisine gardent des probabilités voisines, là où le jet produisait des pics
(un kill chanceux → avantage énorme → p → 1) qui **figeaient** les têtes courtes. La politique
échantillonnée s'en trouve bien, l'argmax d'une distribution plus plate ne coïncide plus avec le
comportement récompensé. Seconde hypothèse : le proxy linéaire des kills (E[dmg] / HP_MAX) paie
une blessure partielle comme un tiers de kill, donc ne récompense plus **finir** une figurine
(concentration de tir) ; les kills réels du run ne baissent pourtant pas. À départager par une
sonde d'entropie par famille sur le checkpoint S11 (`scripts/family_entropy_probe.py`) et une
sonde stochastique contre P0 (est-ce l'argmax seul qui perd ?).

**Verdict (2026-09-14, utilisateur).** Le run avait pour but de valider S11 tel que codé, par la
règle §7 ; la garde a tranché avant la fenêtre de jugement. **S11 tel que codé est réfuté comme
levier** : reprendre P0 avec cette récompense détruit la politique déterministe. Ce que le test ne
dit pas : si c'est l'**idée** (payer l'espérance plutôt que le jet) ou son **exécution** (proxy
linéaire des kills E[dmg] / HP_MAX qui ne paie plus « finir » une figurine ; aplatissement des
têtes courtes quand les avantages deviennent honnêtes) qui est en cause. La courbe échantillonnée
au niveau de la référence et l'entropie montante pointent vers l'exécution, mais ce n'est pas
prouvé. Clé `reward_on_expectation` remise à `false` ; le code reste, verrouillé et réversible.

**Ce qui départagerait idée et exécution, sans run (≈ 1 h de GPU, à décider)** :
1. `scripts/family_entropy_probe.py --model-a <checkpoint S11 20 000> --model-b <P1 référence robust_0.9078>` :
   quelles têtes ont gagné de l'entropie (tir/cible → aplatissement des avantages honnêtes ;
   mouvement → autre chose).
2. Sonde stochastique contre P0 du checkpoint S11 (`opponent.deterministic` et agent échantillonné,
   300 parties) : si ≈ 0,55 comme la courbe, c'est l'argmax seul qui perd — l'idée tient, la
   distribution s'est aplatie ; si ≈ 0,47, la politique a réellement régressé.
3. Variante d'exécution S11b : espérance pour le terme **dégâts** seulement, bonus de kill et de wipe
   sur le résultat **réel** (finir une figurine reste payé au jet) — une clé de plus, 5 lignes dans
   `_squad_combat_shaping`, testable en 6 h. À ne lancer que si 1-2 désignent le proxy des kills.

Précision à updates égales (240 premières updates, même horloge) : `train/entropy_loss` référence
−0,767 / −0,786 / −0,796 / −0,782 / −0,806 / −0,788 par sixième (oscille, +0,02) ; S11 −0,775 /
−0,796 / −0,828 / −0,821 / −0,875 / −0,860 (+0,08, monotone) ; KL, clip_fraction, value_loss et EV
identiques entre les deux. C'est un aplatissement mesuré mais modéré, pas une politique qui part
en vrille — d'où la sonde par famille pour nommer les têtes concernées.

---

## ÉTAT AU 2026-09-14 14:30 — POUR REPRENDRE SANS CONTEXTE {#etat-2026-09-14}

**Où on en est.** Quatre leviers joués depuis le 2026-09-13 soir, tous réfutés ou arrêtés :
S23 (λ 0,2 + rollout ×4, §5.9 : critic qui dérive), `vf_coef` 0,3 (§5.10 : même plateau 0,585,
plus lent), S11 tel que codé (§5.11 : garde de destruction, argmax 0,47 contre P0 alors que
l'agent échantillonné tient 0,55, entropie +0,08 nat). Le plateau 0,59-0,60 contre P0 tient.
Correctifs livrés au passage : collecte Phase 3 (`a59ff5a61`, RAM ÷ 3), 57 tests rouges
préexistants sur main identifiés (fixtures sans `UNIT_RULES`, non corrigés — voir SUITE du rapport
de session, `_model_rules_view` exige la clé sur la figurine blessée depuis `2693007f2`).

**Artefacts.** Config : `x1_lineage` au régime de référence (lr 0,001, ent 0,01, n_steps 8 160,
vf_coef 0,17, tout le reste hérité) ; `rewards_config.squad_shaping.reward_on_expectation` doit
être **`false`** (à vérifier : remis après la fin du holdout de clôture du run S11, qui tournait
encore à 14:30). Contrats d'entraînement du canonique et du snapshot P0 réécrits avec la clé S11
(`write_contract`, 2026-09-14 10:29) — ils restent valides clé à true ou false (le contrat compare
les CLÉS, pas les valeurs). Checkpoint S11 à 20 000 épisodes pour les sondes :
`ai/models/ArmageddonAgent_x1/ppo_checkpoint_20260914-103747_7687944_steps.zip` (+ pkl compagnon) ;
P1 de référence : `ArmageddonAgent_x1_12345_robust_0.9078.zip` ; P0 : `model_ArmageddonAgent_x1_P0.zip`.
Logs : `training_x1_03-p01-s23_*.log` (5 tentatives), `training_x1_04-p01-vf030.log`,
`training_x1_05-p01-s11.log`. TensorBoard : `run_20260914-004747` (S23), `run_20260914-023713`
(vf 0,3), `run_20260914-103745` (S11). Aucun run ne doit être lancé tant que `pgrep -af ai/train.py`
n'est pas vide.

**Décisions utilisateur en vigueur.** « Plat » n'est jamais rejoué plus longtemps ; payer les VP
(registre `victory_points`), pas la tenue d'objectifs ; marge de VP en **B6** (6 × Δ(VP_moi −
VP_lui), `objective_reward_factor` retiré, `on_objective_bonus` laissé — second avis du
2026-09-14, mesure sur 40 parties : VP concédés corrélés −0,83 à l'issue, marge par tour sd 6,8) ;
S14/S15 en réserve, pas avant les résultats ci-dessous ; menace par case en observation écartée.

**⚠️ Relecture du 2026-09-14 soir (§9) : l'ordre ci-dessous est REMPLACÉ par le plan §9.5 — mesures statiques S27, puis exploiteur meilleur cas S25, puis leviers de mécanisme dans ce dispositif ; B6 passe après, sur deux graines.**

**Prochaines actions, dans l'ordre (état au 14:30, périmé par §9.5).**
1. **Marge de VP B6** : code en cours dans une autre session (worktree, prompt du 2026-09-14
   ~13:00 : terme ledger dans `calculate_reward` au site de `objective_turn_reward`, composante
   `vp_margin`, suppression de `_calculate_objective_reward_per_turn` / `once_claim` /
   `reward_per_objective_turn5`, contrats à réécrire pour le canonique ET le snapshot P0). Après
   merge : run sur le régime de référence, clé S11 à false, `training_x1_06-p01-marge.log`, jugé
   par la règle §7 contre la référence `run_20260912-065925` (0,601 sur 20-30k, plat 0,585).
   Surveiller `01_VP/a_vp_diff` à côté de `03_selfplay/P0` (marge qui monte avec win-rate plate =
   prise de risque).
2. **Pendant ce run, départager idée et exécution de S11 (CPU, ~1 h)** : sondes 1 et 2 ci-dessus
   sur le checkpoint S11 ; puis S11b seulement si le proxy des kills est désigné, et après le
   verdict de la marge, jamais empilé.
3. En réserve, par ordre : deux λ acteur/critic (override de `compute_returns_and_advantage` dans
   `ai/gpu_rollout_buffer.py` + clé `model_params`, décision utilisateur requise) ; mesure du plafond
   0,65 par un exploiteur E1 contre P0 (jamais fait) ; S16 pool élargi ; S14/S15.

**Règle de lecture (§7, inchangée)** : moyenne de `03_selfplay/P0` sur les épisodes d'étape
20 000-30 000 ; ≥ 0,65 ou promotion → la lignée reprend ; 0,62-0,65 montante → 60 000 ;
< 0,62 montante → 60 000 puis rejuger ; < 0,62 plate → levier épuisé ; < 0,585 → arrêt ;
garde de destruction < 0,50 (moyenne des sondes) après 20 000. Jamais de conclusion sur moins de
3 sondes ou 20 000 épisodes d'étape.

### 5.12 B6 — marge de VP en ledger + échauffement du critic (2026-09-14, décision utilisateur) — CODE LIVRÉ ET MERGÉ, RUN À LANCER

**Décision.** Le terme d'objectif `objective_reward_factor × VP_propres` (versé une fois par tour à
la frontière command → move, joueur contrôlé seulement) est remplacé par un **ledger de marge** :
à chaque appel de `calculate_reward`, `vp_margin_factor × Δ(VP_moi − VP_lui)` depuis le dernier
versement, `game_state["vp_margin_paid"]` servant de filigrane. Facteur 6 inchangé. Pourquoi
remplacer et non ajouter : Corr(ΔVP_moi, Δmarge) = 0,82 sur 40 parties, les deux termes
ensemble auraient valu +11 par VP propre et −5 par VP cédé ; le ledger seul vaut +6 / −6.
Pourquoi un ledger et non un versement par tour : la somme télescope en **6 × marge finale**, y
compris quand la partie se termine par élimination ; et les VP de l'adversaire tombent pendant
SON tour — aucun filtre `current_player`, `BotControlledEnv` (`accumulate_reward=True`) crédite
le step gym de l'agent. Le bonus « se poser sur un objectif » (`on_objective_bonus`) est conservé
et reste dans `objective` ; `vp_margin` est un composant de ventilation à part.

**Livré (worktree `worktree-marge-vp-b6`, mergé dans main le 2026-09-14 après l'arrêt de S11).**
- `engine/reward_calculator.py::_calculate_vp_margin_reward`, appelée au site des récompenses de
  frontière (avant le tri action / réponse système), propagée par tous les chemins de retour ;
  `_calculate_objective_reward_per_turn`, `_calculate_objective_reward_turn5` (mort :
  `reward_per_objective_turn5 = 0`) et `_get_primary_objective_config` supprimées.
  `vp_margin_paid` absent → `ConfigurationError` (T1), initialisé à 0 aux deux sites de création
  de `game_state` dans `w40k_core.py`.
- `REWARD_BREAKDOWN_COMPONENTS` / `DENSE_REWARD_BREAKDOWN_COMPONENTS` : composant `vp_margin`.
  Tracker : `reward/vp_margin_total` ; `reward/objective_share` = (objective⁺ + vp_margin⁺) /
  positifs (« part de score ») ; `01_VP/f_obj_rewards` = `vp_margin_factor × marge finale`.
- Config (worktree seulement) : `objective_rewards.vp_margin_factor: 6.0` remplace
  `objective_reward_factor` et `reward_per_objective_turn5` dans les deux `rewards_config`.
- **Échauffement du critic** (`ai/patched_ppo.py`) : clé `model_params.value_warmup_updates`
  (kwarg du constructeur, comme `entropy_normalize_by_legal` ; dans `_PLAIN_CURRICULUM_KEYS`
  pour `--append`). Pendant les N premières updates du run, `loss = vf_coef × value_loss` —
  politique et entropie annulées, early-stop KL désactivé ; `train/value_warmup_active` publié.
  La clé ET le compteur `_vwu_done` sont exclus du zip (`_excluded_save_params`) : l'échauffement
  est un régime de run, jamais hérité d'un checkpoint — seul le profil du run l'active. Second
  review du 2026-09-14 : exclure le compteur seul ne suffisait pas, la clé restaurée au `load`
  et laissée en place par un profil qui ne la porte pas (`_apply_curriculum_model_params` ne
  pose que ce que le profil porte) aurait rejoué N updates critic-only sur tout `--append`
  ultérieur. Motif : le critic a appris une cible qui payait +6 par VP propre et 0 par VP
  cédé ; à la reprise, sa cible change, et le premier gradient de politique serait calculé sur
  des avantages faux.
  **Marqueur « échauffé sous cette table » (décision B, 2026-09-14).** La clé vit dans
  `x1_lineage`, donc chaque `--append` d'étape suivante l'aurait portée encore et rejoué 20
  updates critic-only (~1 440 épisodes, politique figée) sans garde-fou. Le zip retient
  désormais `value_warmup_done_under` = empreinte de la table de récompense sous laquelle le
  dernier échauffement s'est ACHEVÉ (`training_contract.reward_table_fingerprint` : clés ET
  valeurs, hors clés `_doc` — le critic apprend la somme, un facteur doublé est une autre
  cible ; le contrat `build_contract`, lui, ne compare que les noms). Écrit par `train` à la
  dernière update du régime, pas à l'ouverture : un checkpoint pris au milieu ne se dit pas
  échauffé, `--resume-from` rejoue le régime entier. `ai/train.py::arm_value_warmup` (les
  deux chemins d'entraînement, après création ou chargement + curriculum) pose
  `value_warmup_contract_id` (empreinte du run, exclue du zip, obligatoire sinon `train`
  lève) et SAUTE l'échauffement (`value_warmup_updates` remis à 0 sur le modèle, log « non
  rejoué ») quand le profil demande la clé et que le zip porte déjà cette empreinte : la clé
  reste dans `x1_lineage` sans état à gérer, `--append` d'étape suivante et `--resume-from`
  après crash passent. Le refus `ValueError` livré le matin est retiré le soir même (review :
  `--resume-from` pose `append=True` et applique le même profil, donc la reprise d'un run
  planté après la 20e update était refusée tant que la clé n'était pas retirée, puis remise au
  changement de table — un état manuel, précisément ce que le marqueur devait supprimer ; le
  saut empêche le rejeu tout autant). Marqueur d'une autre table ou absent : l'échauffement se
  joue, le log dit les deux empreintes. Tests : `tests/unit/ai/test_value_warmup_marker.py`
  (14) — rouge constaté sans la remise à 0 (2 tests, dont un qui joue une update sur le vrai
  `train` : `value_warmup_active` = 0), et rouge si le marqueur est écrit dès la première
  update.
  **Gel hors critic (review du 2026-09-14).** Annuler les termes ne suffit pas : l'extracteur
  de features est PARTAGÉ (`PointerMaskablePolicy` exige `share_features_extractor=True`, et
  ses logits `q · e_i` lisent les embeddings de l'extracteur), donc la value loss seule
  déplaçait l'extracteur, et la politique avec lui — sans clip ni early-stop KL. Le test
  initial était vert parce que `MlpPolicy` a un extracteur `Flatten` sans paramètre. Désormais,
  pendant le warmup, seuls `mlp_extractor.value_net` et `value_net` gardent un gradient
  (`_critic_only_param_ids`, `grad = None` sur le reste avant `optimizer.step()`) : politique
  immobile au bit près, mesuré sur `PointerMaskablePolicy` + `SpatialCombinedExtractor`. Coût
  assumé : l'extracteur n'apprend pas la nouvelle cible pendant le warmup, seule la tête critic
  (2 × 512 + linéaire) la remappe ; l'apprentissage joint reprend après.
  **Buffers gelés aussi (second review du 2026-09-14).** Le gel des paramètres ne figeait pas
  les statistiques d'`EntityRunningNorm` : `train()` tourne en `set_training_mode(True)`, et
  chaque forward avance `running_mean/var/count` — mesuré sur la policy de production après une
  update warmup : 9 buffers sur 16 déplacés, Δprobs 4,5e-4, `approx_kl` 1,7e-3 ≠ 0. Ces modules
  passent en `eval()` pour l'update warmup (statistiques figées comme pendant les rollouts) ;
  `set_training_mode` étant récursif, rien à rétablir. Le premier test ne comparait que
  `named_parameters()`, pas les buffers.
- **`SelfPlayWrapper` accumule les steps de P2** (`ai/env_wrappers.py`, review du 2026-09-14).
  Le wrapper ne rendait à P0 que le step TERMINAL de P2 et jetait les autres — le ledger
  avançait, l'agent ne touchait rien, et la somme téléscopique était fausse sur le chemin
  self-play pur (`ai/train.py`, branche sans bots) : mesuré sur 4 parties aléatoires, vp_margin
  perdu +180 / +270 / +120 / +180 pour des marges finales +5 / +20 / −10 / −5. Jumeau de
  `BotControlledEnv` (`accumulate_reward=True`, 0 écart sur 20 parties) : les deux boucles P2
  (avant et après l'action de P0) additionnent maintenant chaque step, pénalité défensive
  comprise. Test : `tests/unit/ai/test_selfplay_wrapper_reward_accumulation.py` (3, rouge sur
  l'ancien wrapper).
- **Porte « pool vide → advance_phase » de `step_with_mask`** (`engine/w40k_core.py`, second
  review du 2026-09-14) : elle rendait 0.0 sans passer par `calculate_reward` ni compter le
  step. Or la transition elle-même peut attribuer des VP et terminer la partie (marquage de la
  phase command, marquage du second joueur en fin de round 5 → limite de tours) : le dernier
  delta du ledger et le ±situational y étaient perdus, `reset` remettait `vp_margin_paid` à 0,
  et la somme téléscopique était fausse sur cette porte (le ±150 y était déjà perdu avant B6).
  La porte verse maintenant `calculate_reward` sur le payload `{**result, action: advance_phase,
  reason: pool_empty}` (classé réponse système par l'indicateur explicite `pool_empty`,
  `system_response` = 0) et compte le step (`_account_step_metrics`, troisième appelant).
  Mesure de reachabilité : 0 passage par cette porte sur 110 parties aléatoires
  `BotControlledEnv` (agent P1 et P2) — la cascade absorbe les phases vides ; la porte reste le
  chemin des WAIT forcés des deux wrappers, et elle était déjà verrouillée comme porte
  terminale (`test_terminal_info_all_paths.py`).
- **Format de save `W40KTL10`** (`services/game_saves.py`) : `vp_margin_paid` est une clé
  mutable de premier niveau lue par `require_key` à chaque step, PvP compris — une row TL09
  rendrait un état amputé et le premier step lèverait. Bump + TL09 en `_LEGACY_LOSSES`,
  `_TL10_KEYS` (132 clés) dans `test_save_format_key_contract.py`.
- Tests (rouge par mutation, constatés) : `test_objective_turn_reward.py` réécrit (versement =
  6 × Δmarge, delta adverse hors tour, deux appels → 0, filigrane, erreur si clé absente,
  ventilation) — rouge sur « filtre `current_player` réintroduit » et « filigrane non écrit » ;
  `test_s11_reward_on_expectation_e2e.py` : somme des `vp_margin` sur une partie moteur réelle =
  6 × marge finale, paramétré siège p1 / p2 × graines 42 / 7 depuis le 2026-09-14 soir (second
  avis : le siège p2 et le marquage du second joueur en fin de phase fight du round 5 n'étaient pas
  verrouillés), avec garde « VP > 0 » contre le vert vacant et, en p2, versement vu sur le step
  terminal (turn 5, fight, game_over) ; RandomBot semé par `random.seed` (module global) ; rouge
  sur le filtre `current_player` en siège p1 (dernier versement = celui de l'adversaire, jamais
  rattrapé) ; en p2 le filtre ne fait que retarder les deltas, c'est le test unitaire qui le voit ;
  `tests/unit/ai/test_critic_warmup.py` (13) : politique immobile / critic mobile pendant le
  warmup (rouge si la loss complète revient), compteur saturant, kwarg accepté en `--new`,
  ni clé ni compteur hérités du zip + modèle rechargé sans warmup (rouge si la clé voyage), zip
  antérieur à B6 chargé à 0, extracteur partagé à paramètres immobile (rouge sans le gel),
  `PointerMaskablePolicy` réelle : seuls les tenseurs `mlp_extractor.value_net.*` /
  `value_net.*` bougent, buffers d'`EntityRunningNorm` et distribution de la politique
  identiques au bit près pendant le warmup puis mobiles après (rouge sans le `eval()`) ;
  `test_terminal_info_all_paths.py::test_pool_empty_gate_pays_the_ledger_and_the_outcome` :
  la porte pool-vide verse 6 × 15 + 50 et l'accumule (rouge à 0.0).
  Fixtures adaptées : `test_reward_calculator.py`, `test_agent_decision_mechanism.py`,
  `test_terminal_info_all_paths.py`, `test_metrics_single_writer.py`, `test_metrics_tracker_utils.py`,
  `test_train_helpers.py` (couverture synthétique de la clé). 241 verts sur les onze fichiers touchés.

**Préparation faite le 2026-09-14 (18:20), run NON lancé.**
- Contrat du snapshot P0 réécrit sur les nouvelles clés de récompense (`write_contract` sur
  `model_ArmageddonAgent_x1_P0.zip`, écart après : aucun). C'est CE contrat que `--etape P1`
  copie sur le canonique avant `enforce_training_contract` — le `--init` du canonique est sans
  effet sur ce chemin. Archive préalable : `model_ArmageddonAgent_x1_P0_pre_b6_20260914.zip`
  (copie identique, `cmp`) + `..._pre_b6_20260914_training_contract.json` (ancien contrat).
- `value_warmup_updates: 20` dans `x1_lineage.model_params` (note `value_warmup_updates_normal`
  dans le profil). Conversion mesurée sur S11 : 1 update = 8 160 pas ≈ 72 épisodes (480 000 pas
  pour 4 223 épisodes entre deux checkpoints), donc ≈ 1 440 épisodes, ~15 min. Contrôle à
  l'update 21 : `train/explained_variance` remontée vers ~0,87.
- `reward_on_expectation: false` (régime de référence), aucun `ai/train.py` en cours.
- **À lancer par l'utilisateur** : commande habituelle `--etape P1`, log
  `training_x1_06-p01-marge.log`, jugé par la règle §7 contre 0,601 / 0,585 ; surveiller
  `01_VP/a_vp_diff` à côté de `03_selfplay/P0`.

## 6. Ce qui n'a pas été fait

- [x] **Contrôle positif** de la sonde sur le chemin policy — fait le 2026-09-13 : le témoin
      entnorm_040721 ne discrimine pas (f = 0,006 comme P1) ; le contrôle à poids aléatoires
      (`--random-init`) rend f = 0,43 [0,27, 0,59] (C3, E4 fermés).
- [x] **Décomposition de Var(δ_t)** — faite le 2026-09-13 (C1) : Var(r) = 86 % de Var(δ),
      ρ(r, ΔV) = −0,55 ; S11 bornée par là.
- [x] **Balayage λ appairé** — fait le 2026-09-13 : f(λ=0) = 0,053 [0,036, 0,070] (C4, S10).
- [x] Sonde avec **P0 déterministe** — faite le 2026-09-13 : mêmes nombres (B4, S12).
- [x] **Levier S23** (λ 0,2 + 32 640 / 2 040) — testé dans la nuit du 2026-09-13 au 14, réfuté (§5.9).
- [x] **`vf_coef` 0,3** — run du 2026-09-14 02:36 → 10:26, réfuté (§5.10).
- [x] **S11** — code livré et mergé ; run du 2026-09-14 10:37 → 14:05 arrêté par la garde (moyenne des sondes 0,473 < 0,50) ; entropie montante, argmax perd, échantillonné tient (§5.11).
- [ ] **B6 / S24** — code livré et mergé, contrat P0 réécrit, `value_warmup_updates: 20` posé (§5.12) ; reste : lancer le run « marge » et le juger.
- [ ] Température d'exploration (S9) — après la question de variance, pas avant.
- [ ] Tête Q / avantage moyenné (S14) ; distillation par recherche (S15, gelée).
- [ ] Ventilation des pénalités −97 (C5) ; déploiement auto à 0,50 (D4).
- [ ] Pool élargi dès P1 (S16) ; second scénario (S17).
- [x] Runs relancés depuis l'arrêt du 2026-09-12 : deux bras entnorm (09-12/13), S23 (09-13/14, réfuté),
      vf_coef 0,3 (09-14, en cours).

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
  sonde (options `--gae-lambdas`, `--model`, `--opponent-deterministic`, décomposition) et ses
  tests.
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
   **2 040**, `target_kl` inchangé — 16 mini-lots, la coupure KL à ~15 pas ≈ une epoch entière
   du rollout (l'objection du 32ᵉ/128 de 2026-09-07 disparaît). Pas 4 080 : VRAM mesurée le
   soir même sur la vraie politique, 7,47 Go réservés par lot de 4 080 contre 3,80 à 2 040, sur
   8,19 Go partagés avec l'hôte (0,5 à 2,4 Go) — le 4 080 replante comme le 7 septembre ;
   RAM hôte du buffer 3,72 Go (+ autant en transit), sans risque pour la VM. Un run P1
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

**DÉCISION (utilisateur, 2026-09-13) : A — run P1 avec S23** (`gae_lambda` 0,2, `n_steps`
32 640, `batch_size` 2 040 dans `x1_lineage`, rien d'autre), 30 000 épisodes d'étape jugés sur
`03_selfplay/P0` contre le plat à 0,59 du run de référence. Règle écrite avant le run :
moyenne de `03_selfplay/P0` sur les épisodes d'étape 20 000–30 000 ≥ 0,65, ou promotion par la
sonde (`pool_eval/vs_P0_3ep` ≥ 0,65) → S23 fonctionne, la lignée reprend sous ce profil (il
s'applique à toutes les étapes reprises) ; entre 0,62 et 0,65 et courbe montante → laisser
courir jusqu'à 60 000 ; < 0,62 et plate → levier config épuisé, ouvrir l'arbitrage S14 / S15.
**Complétée le 2026-09-13 à 23:10, avant le lancement (validée par l'utilisateur)** : deux branches
manquaient. (d) < 0,62 mais courbe montante (Q3 > Q2 hors bruit) → laisser courir jusqu'à 60 000 et
rejuger sur 50 000–60 000 — S23 fait 4× moins d'updates par épisode que la référence (`target_kl`
plafonne chaque update), ~105 updates à 30 000 contre ~280 quand la référence a atteint son plat.
(e) < 0,585 sur 20 000–30 000 (sous le plat de référence) → arrêter, verdict « λ court biaise vers
le proxy du critic » (C3 : le gradient TD détecté est biaisé par l'erreur du critic), S11-λ écartée,
arbitrage S14 / S15 ouvert. Décision utilisateur du même soir : « plat » n'est pas rejoué à 60 000
— un plateau est un symptôme, la cause est ailleurs ; GPU rendu aux sondes (modèle entnorm traité,
checkpoint S23 avec balayage λ). Contrôle de plomberie, pas de jugement : `train/n_minibatches_done`
attendu ~15–20 sur 64 ; ≤ 8 → rollout non vu en entier, prédiction f ≈ 0,18 inapplicable.
Plomberie vérifiée avant : `_apply_curriculum_model_params` (ai/train.py) pose `gae_lambda`,
`batch_size` et `n_steps` sur le modèle repris et reconstruit le buffer avec le nouveau λ
(`recreate_rollout_buffer`, inconditionnel) ; `n_steps` est converti par env avant le
chargement (32 640 → 1 360 × 24). **Résultat en §5.9 : réfuté (critic qui dérive sous une cible
TD(0,2)). Suite décidée le 2026-09-14 par l'utilisateur : essai `vf_coef` 0,3 (§5.10) puis S11
(§5.11) ; S14 / S15 restent en réserve ; « menace par case » en observation écartée (l'ennemi bouge
avant de tirer) ; deux λ acteur/critic à dimensionner ; plafond 0,65 jamais mesuré (aucun exploiteur
n'a tourné contre ce P0).**

---

## 9. Relecture externe du 2026-09-14 soir — faits manqués, corrections, plan {#relecture-2026-09-14}

Relecture par une session indépendante du dépôt (pas du dossier), contre-relue par la session
du dossier. Ce qui suit est **vérifié dans le dépôt** sauf mention contraire.

### 9.1 Trois scores P1 ≥ 0,69 que le dossier ne cite pas

`curriculum.log` (ignoré par git, non daté ligne à ligne) :

| ligne | étape | régime | épisodes | vs P0 (gate) | quand |
|---|---|---|---|---|---|
| 7 | P1 | x1_long, new | 100 000 | 0,737 | avant option A |
| 9 | P1 | from:P00 | 80 000 | 0,697 | avant option A |
| 10 | P1 | **x1_lineage, from:P0** | 30 008 | **0,713** | entre la ligne P0 à 75 001 et le P0 actuel (09-10 22:31) |
| 14 | P1 | x1_lineage, from:P0 | 30 000 | 0,563 | 09-11 05:06 |
| 15 | P2 | x1_lineage, from:P1 | 30 000 | 0,650 vs P0, 0,579 vs P1 | 09-11 13:09 |

Entre la ligne 10 et la ligne 14 : les quatre commits moteur du 2026-09-10 (`ab669cdd4` OC
sommée par figurine — `engine/game_state.py` + `engine/observation_entities.py` ;
`422115af4` exclusivité combi — `engine/observation_*` ; `35382ab9b` dégâts espérés sur cible
effective ; `e2040c062` table de dégâts complétée — `engine/weapon_damage_cache.py`, consommée
par `ai/bot_doctrines.py`, `ai/benchmark_bots.py` et le cache de meilleure arme de
`engine/w40k_core.py` ; 0 hit `expected_damage|weapon_damage` dans `engine/observation_*.py`),
plus deux changements d'observation du 09-09 qui ont imposé un P0 neuf. Le seuil est passé de
0,55 à 0,65 le 09-11 (§1.4), le jour du 0,563. **Le seuil 0,65 a donc été fixé sur un jeu où P1
faisait 0,71, et n'a jamais été confronté au jeu actuel.** Réserve : le P0 de la ligne 10 n'est
pas le P0 actuel (75 001 épisodes contre 50 000, autre observation), donc « même adversaire »
n'est pas acquis et le 0,713 n'est **pas** une référence comparable. **Conclusion sur les
commits du 09-10 : aucune action code ; la seule référence valide est ce qu'un exploiteur
atteint maintenant (S25).** Ce que ces commits ont changé pour le joueur (qui tient un
objectif, adversité des bots) ne se lit pas dans le code, il se lit dans les parties : S27.

### 9.2 Le régime de reprise double le learning rate

Vérifié : `model_ArmageddonAgent_x1_P0.zip` porte `learning_rate` 0,0005 (fin de la rampe
0,002 → 0,0005 de `x1_long`, `training_x1_01-p00.log` ligne 55) ; `x1_lineage` pose 0,001,
constant, et `_apply_curriculum_model_params` (`ai/train.py`) l'applique à la reprise ;
`train/learning_rate` est plat à 0,001 sur les 1 052 updates de `run_20260912-065925` ;
`train/approx_kl_max` ≥ 0,0225 sur 1 052/1 052 ; `train/n_minibatches_done` 11–16 sur 32 sur
les deux runs qui le publient (§5.10, §5.11). Le rejet de A3 (« amplitude d'une direction qui
n'en est pas une ») vaut pour une update, pas pour un run où seule la dérive cumulée compte et
où la moitié de chaque rollout n'entre jamais dans un gradient. Effet attendu sur le plafond :
réel mais modeste (l'équivalent gratuit d'un lot doublé), **hygiène du régime, pas explication
du plafond**. Retiré comme preuve : « les pas Adam successifs sont alignés par le momentum »
(mécanisme plausible, non mesuré ; le seul fait est la coupure à mi-rollout).

### 9.3 Le protocole ne peut pas voir l'effet qu'il cherche

Une graine par levier, une référence unique, jamais deux graines du même réglage ; erreur-type
d'une sonde 2,9 points, sondes voisines à ±5 par blocs corrélés, écart visé 5 points. Donc
**« `vf_coef` 0,3 réfuté » est un résultat nul dans le bruit** (S5 requalifié), et B6 jugé sur
une graine le sera aussi. Seuls S23 et S11 ont un verdict hors bruit, par destruction. Règle à
partir de maintenant : **tout levier à effet attendu < 10 points se juge sur deux graines**, et
un run d'exploration se lit à updates égales quand le régime change la cadence d'update.

Deux affirmations de la relecture retirées après contre-relecture : « P1 et P0 tous deux à
0,91 en holdout » (non vérifié : P0 = score robuste 0,868, P1 = holdout 0,907–0,910, métriques
différentes ; l'argument « holdout bots saturé » tient par les témoins entnorm à 0,875–0,879
qui font 22–28 % contre P0) ; « S23 était prévisible » (recul après coup ; la forme utile est
la règle : avant tout changement de λ ou γ, écrire ce qu'il fait à la CIBLE du critic).

### 9.4 Décision utilisateur (2026-09-14 soir) — le gate n'est pas le sujet

**« Plafonner vers 0,60 contre un adversaire figé de même architecture serait normal »
(lecture AlphaGo Zero à 55 %) : ÉCARTÉ.** P0 ne sait battre que les bots ; une politique
entraînée à l'exploiter doit pouvoir monter vers **0,90**. 0,65 est un seuil de **confirmation
de domination** posé bas exprès pour éviter la suradaptation, pas un objectif. Conséquence : si
même l'exploiteur meilleur cas (S25) plafonne vers 0,60, ce n'est pas le jeu qui plafonne, c'est
le **mécanisme d'apprentissage** qui n'extrait pas ce qui est là — et c'est dans le dispositif
exploiteur (100 % P0, déterministe, le plus lisible) que les leviers de mécanisme se jugent.
E2 / S18 restent clos ; G1 « limite normale » écarté.

### 9.5 Plan (ordre, coût, règle de lecture écrite avant)

1. **S27 — mesures statiques** (~1 h CPU, aucun code d'entraînement, lecture seule des
   modèles) : table siège × mode. Lecture : si P0 vs P0 argmax s'écarte de 0,50 par siège de
   plus de 5 points, le siège est une variable à équilibrer dans tout ce qui suit.
2. **S25 — exploiteur de P0, meilleur cas, UN bras** (~6 h) : lr 0,0005, P0 déterministe,
   siège 0,5, 100 % P0, 60 000 épisodes, sondes à 10 000. Règle : moyenne des 3 dernières
   sondes ; **≥ 0,68** → le défaut de P1 est dans l'écart de config, bissection en un run par
   variable (lr → déterminisme → siège → part de bots) ; **≥ 0,80** → la config P1 est le seul
   problème ; **< 0,62 plat** → goulot = mécanisme, passer au 3.
3. **Si goulot = mécanisme, dans le dispositif S25, un levier par run, deux graines quand
   l'effet attendu est < 10 points**, dans cet ordre : (a) exploration structurée S9
   (température de collecte, ratio corrigé) — contre un adversaire déterministe, une politique
   à p ≈ 0,99 ne peut pas DÉCOUVRIR l'exploit, c'est le levier le plus directement lié à la
   thèse « P0 est exploitable » ; (b) poids de l'issue vs façonnage (C2 : objectifs 62 %,
   issue ±150 ; contre un adversaire figé, l'issue est le signal exact de l'exploit et le
   façonnage peut le contredire) ; (c) deux λ acteur / critic ; (d) B6 (déjà codé) sur deux
   graines ; (e) S11b si les sondes de §5.11 désignent le proxy des kills ; (f) S14 tête Q ;
   (g) S15 recherche. Chaque run : règle de lecture écrite avant, jugé à updates égales,
   consigné ici ET dans `training.md`.
4. Seulement ensuite : transfert du régime gagnant dans `x1_lineage`, reprise de la lignée.

**Plomberie vérifiée pour S25** : E1 cible P3 (« ni init ni pool ne peuvent nommer une étape
qui n'a pas encore tourné », `_doc_ordre`), les surcharges d'étape sont interdites sur les
exploiteurs, `training_configs.lineage` impose `x1_lineage`, `opponent.deterministic` est
global, `EXPECTED_STAGES` (`tests/unit/ai/test_curriculum.py`) épingle champion et poids de
chaque étape. Donc pas de modification temporaire de la config x1 : **agent dédié**
`ArmageddonAgent_x1_expl` (copie de `config/agents/ArmageddonAgent_x1/`, curriculum réduit à
`order: [P0, E0]` avec E0 exploiteur `from:P0` ciblant P0, profil de lignée à lr 0,0005 et
siège 0,5, `opponent.deterministic: true`), même précédent que `ArmageddonAgent_x1_entnorm`.
Nécessite la copie de `model_ArmageddonAgent_x1_P0.zip` + pkl + contrat sous le nom du nouvel
agent (copie, pas modification — à faire ou autoriser par l'utilisateur). L'exploiteur s'arrête
seul à `win_rate_target` 0,70 par sa sonde de confirmation : à relever à 0,95 dans SA copie de
curriculum pour lire jusqu'où il monte.

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
