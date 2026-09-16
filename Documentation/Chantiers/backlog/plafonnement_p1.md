# Plafonnement de l'apprentissage — P1 contre P0 : causes, solutions, état

> **Chantier ouvert le 2026-09-13.** Sujet : [Roadmap/training.md](../../Roadmap/training.md).
> **Point de reprise sans contexte (2026-09-16) : [ÉTAT AU 2026-09-16](#etat-2026-09-16) — S9 terminé, décisions ouvertes, état de santé.** Précédent (2026-09-15) : [§9.9](#suite-2026-09-15) — verdict S25, S14 lancé, ORDRE DE LA SUITE FIGÉ.**
> Dossier de synthèse : il **relate** ce qui a été fait sur le plateau de la lignée P0 → P1 entre
> le 2026-09-11 et le 2026-09-13 (avec les antécédents P2 du 2026-09-04 → 09-08 qui ont fixé le
> régime de lignée), inventorie **toutes** les causes envisagées et **toutes** les solutions, et
> coche ce qui a été fait, testé, réfuté ou laissé ouvert. Il ne décide rien : la décision en
> attente est au §7. Toute nouvelle mesure s'ajoute ici **et** dans `training.md`.
>
> Légende des statuts : ☑ fait / mesuré · ◐ partiel · ☐ non fait · ✗ écarté (avec la raison) ·
> ⏳ proposé, en arbitrage.

---

## En clair — où on en est (lecture non technique, 2026-09-16 matin) {#en-clair-2026-09-16}

**Les mots.** *P0* : le premier champion, entraîné à partir de rien contre six programmes scriptés
(les « bots ») ; il les bat à 91 %. *P1* : l'étape suivante, qui repart des poids de P0 et doit le
battre 65 fois sur 100 pour être promue ; elle stagnait vers 60 %. *L'exploiteur* : un agent de
mesure qui repart de P0 et ne joue que contre P0, pour savoir jusqu'où on peut le battre. *S25* :
l'exploiteur de référence (14–15 septembre), plafonné à 68 %. *S9* : le même exploiteur avec la
**température**, un réglage qui rend ses choix plus variés pendant l'entraînement (il essaie son
second choix une fois sur onze au lieu d'une sur cent) et qui n'a aucun effet à l'évaluation.

**Ce que S9 a montré (15–16 septembre, 60 000 parties, §5.14).** Le score contre P0 est monté de
68 % à **78 %**, plat depuis 40 000 parties. Rien perdu contre les bots (90 %). Contre des
adversaires jamais affrontés, le gain se transfère à tout ce qui descend de P0 (P1 : 64 % contre
50 % pour S25) mais pas à un style étranger (71 %, comme S25 et P0) : l'agent apprend à battre la
famille de P0, pas mesurablement à mieux jouer. La température s'est éteinte d'elle-même : le
réseau a affûté ses préférences jusqu'à annuler la variété ajoutée, et la montée s'est arrêtée au
même moment. Une graine, un dispositif.

**La cause du plateau, telle qu'elle est mesurée aujourd'hui.** Un agent qui repart de son
champion est sûr de lui à 99 % : il ne tente plus rien d'autre et ne peut pas découvrir ce qui bat
P0. Sur la décision de charge il ne varie presque jamais (0,01 de variété) : il n'y apprend plus.
C'est un problème de **reprise**, pas du jeu ni des correctifs du moteur : sur le code actuel un
agent atteint 78 %, au-dessus du 71 % d'avant les correctifs. Tous les autres suspects (taille des
lots, vitesse d'apprentissage, poids du critique, horizon du crédit, récompense en espérance,
bonus de variété, tête de prédiction par action) ont été testés et écartés (§4).

**Ce qui est lancé le 16 au matin (§5.15).** Le régime d'apprentissage de S9 (température 2 et pas
d'apprentissage 0,0005, celui de la fin de P0) est transféré dans la lignée, et P1 est relancé
depuis P0. Règle écrite avant : promotion automatique à 30 000 parties si la moyenne de trois
sondes de 300 parties atteint 0,65 ; arrêt manuel à 60 000 sinon ; au gate, deux lectures
obligatoires : la matrice contre les adversaires jamais affrontés et le score par siège.

**Ce qui n'est pas sain, au-delà de la reprise.** Chaque verdict des dix derniers jours repose sur
une graine contre une graine ; il n'y a plus de juge de progrès général (les bots sont battus à
90 % par tout le monde, la lignée se mesure contre son propre ancêtre) ; la moitié de chaque paquet
d'expérience est jetée à chaque mise à jour ; la récompense est un substitut à 70 % (objectifs
64 %, pénalités non ventilées) ; le gate de lignée n'a plus été passé depuis le 10 septembre.

**Ce qui vient ensuite.** Le run de nuit se décide au résultat de B : P0 neuf à froid (le juge
indépendant qui manque) si B passe, seconde graine de S9 si B échoue. Puis, seulement si la
lignée plafonne sous l'objectif, un mécanisme d'exploration que l'optimiseur ne peut pas défaire,
comparé par écrit avant tout code (§10). Le P1 parti de zéro (100 000 parties, 16 h) reste en
réserve si la reprise échoue deux fois. Point de reprise détaillé : [ÉTAT AU 2026-09-16](#etat-2026-09-16).

---

## En clair — lecture non technique du 2026-09-13 soir (archive datée, dépassée par ce qui précède)

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

## 0. Résumé au 2026-09-13 (archive datée ; l'état courant est dans « En clair » ci-dessus et dans [ÉTAT AU 2026-09-16](#etat-2026-09-16))

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
| D6 | Moteur modifié pendant la lignée (35 commits entre les holdouts) | références invalidées | ☑ acté, pas une cause du plateau ; **complété §9.1 : le seuil 0,65 a été posé le 09-11 sur un jeu où P1 faisait 0,713** | P0 et P1 jouent le même moteur ; seules les comparaisons avant/après sont interdites — et la référence 0,713 (curriculum.log ligne 11, autre P0, autre observation) n'est PAS comparable au 0,60 actuel ; le seul point de référence valide est ce qu'un exploiteur atteint MAINTENANT (S25) |

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
| S14 | Avantage moyenné pour l'acteur : tête Q(s,a) dans PPO (A = Q − V, dés moyennés par régression) | C1 | ✗ **codée, centrée sous π, RÉFUTÉE le 2026-09-15 (§5.13.1) : pas de données contrefactuelles ; rejouable seulement SUR S9 si la mesure 2a de §9.9 est positive** | code IA (`adv_heads`, `advantage_source`, `q_coef`) | mesurable par la même sonde ; S13 a conclu « le bruit d'un pas noie le ΔQ restant, à lot fixe ni λ ni l'adversaire ne le réduisent » |
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

### 5.13 S14 — tête Q d'avantage attendu (2026-09-15, décision utilisateur de la nuit) — CODE LIVRÉ, RUN LANCÉ {#s14-2026-09-15}

**Décision (2026-09-15, 01:48, session `05a43ec2` dans le worktree `worktree-tete-q-avantage-espere`).**
Après la lecture de S25 à 20 000 (plateau naissant à 0,69 avec la même signature d'update que
P1 : coupure KL après 15 mini-lots sur 32, entropie plate), l'utilisateur a tranché : « on fait
cette implémentation et on teste ». C'est la ligne « avantage moyenné » désignée par S13 (§5.8) :
le gradient de politique est du bruit à 98 % parce que l'avantage GAE `r + γV(s′) − V(s)` porte
le jet de dés du pas (86 % de Var(δ) est Var(r), 96 % sur le tir). La normalisation d'avantage
n'y peut rien (signal et bruit divisés par la même constante) ; le critic ne retire que ce qui se
prédit depuis `s`, et le dé d'un tir décidé en `s` ne s'y prédit pas.

**Ce que fait S14.** Une seconde tête, `adv_heads` (`ai/pointer_policy.py::PointerHeadNets`), de
structure IDENTIQUE aux têtes de politique (mêmes noms, mêmes formes, même assemblage
`_action_logits` — un avantage par action lit exactement les mêmes entrées qu'un logit par
action) mais lue sur le tronc CRITIC (`latent_vf`) : elle rend `A(s, a)` pour toute action, et
`Q(s, a) = V(s).detach() + A(s, a)` est régressée sur le même retour λ que V (perte
`q_coef × MSE`). **V garde sa cible** (leçon de S23 : changer la cible du critic fait dériver la
politique). L'acteur PPO reçoit `A(s_t, a_t).detach()` à la place de l'avantage GAE — une
différence de deux espérances apprises sur des milliers de jets, recalculée par les réseaux
courants à chaque mini-lot. Initialisation à zéro des couches de sortie : une tête fraîche rend
`A = 0` partout, donc l'échauffement (`value_warmup_updates`, politique figée) la fait apprendre
d'abord, avec V ; `arm_value_warmup` ne le saute JAMAIS sur une tête jamais entraînée (lue sur le
CONTENU, couches de sortie exactement nulles — pas sur la provenance : un zip entraîné en `gae`
après S14 porte une tête présente mais inerte). Clés `model_params.advantage_source`
(`gae` = référence bit à bit | `q_head`) et `q_coef` (exigé avec `q_head`, interdit avec `gae`),
validées ensemble en `--new` comme en `--append`, sérialisées dans le zip.

**Livré.**
- Commit `bf1fcc7f2` (04:17) : `ai/pointer_policy.py` (+231), `ai/patched_ppo.py` (+271),
  `ai/train.py` (+37), `tests/unit/ai/test_q_head.py` (18 tests : mêmes têtes noms/formes,
  enregistrées en dernier, tête fraîche → avantage nul, `evaluate_actions_q` inchangé sur
  (values, log_prob, entropy), zip antérieur chargé avec états Adam alignés, échauffement = tête
  et V apprennent, politique figée au bit près, `gae` inchangé, clés validées ensemble),
  `Documentation/Reference/training/entrainement.md` (deux clés, trois tags).
- `/code-review` (04:18) : 2 findings, tous deux mesurés. (1) HIGH — `adv_heads` enregistré sur
  toute `PointerMaskablePolicy` : tout zip antérieur devenait inchargeable par `MaskablePPO.load`
  NU (`engine/pve_controller.py:115`, `ai/bot_evaluation.py:982` et `:1011`, snapshots du pool,
  replay), seul `PatchedMaskablePPO.set_parameters` tolérait l'absence — mesuré sur
  `model_ArmageddonAgent_x1.zip` : `Missing key(s) in state_dict: "adv_heads…"`. (2) MEDIUM —
  fraîcheur déduite de l'absence des clés : un zip entraîné en `gae` après S14 puis repris en
  `q_head` avec marqueur d'échauffement posé sautait l'échauffement et l'acteur lisait des
  avantages tous nuls (`policy_loss ≡ 0`). La correction était en cours au **reboot Windows de
  04:29:28** (arrêt propre de l'instance WSL par l'hôte, `journalctl -b -1`) ; reprise et finie
  le 2026-09-15 midi, commit `0ceaa86b0` : tolérance déplacée dans la politique
  (`PointerMaskablePolicy.load_state_dict` : seules les clés `adv_heads.*` peuvent manquer,
  tout autre écart lève comme avant) et dans son optimiseur (`lenient_optimizer_class` : état
  Adam étendu aux rangs de la tête, enregistrée en dernier), `_archive_architecture`
  (`ai/bot_evaluation.py`) ignore `adv_heads.*` dans la signature de compatibilité ;
  `PointerHeadNets.is_untrained()` remplace le drapeau ; 2 tests nouveaux (chemin
  `MaskablePPO.load` nu, tête présente mais jamais entraînée), rouges par mutation (tolérance
  retirée → 4 rouges ; `is_untrained` forcé faux → 4 rouges). 20 verts ; typage 0 erreur sur les
  5 fichiers.
- Seconde `/code-review` (13:45, sur la livraison complète) : 1 finding — `scripts/grad_signal_probe.py`
  construisait le terme policy sur les avantages GAE et sans terme Q, donc mesurait sur un
  checkpoint `q_head` un gradient que le run n'applique pas. Corrigé par un REFUS explicite
  (`refuse_q_head_model`, au chargement et au mini-lot ; test) : la sonde ne décompose que
  l'acteur GAE. Étendre la sonde à S14 demande d'abord de dire ce que « fraction de signal »
  veut dire quand l'avantage est une sortie de réseau et non un retour bruité — décision à
  prendre si S14 passe (§9.9, étape 4). Note de la même review : `test_phase2_sb3_pipeline.py`
  posait un attribut mort `_adv_heads_fresh` (retiré).
- Vrai chemin vérifié sur le zip P0 réel de l'agent expl (77 rangs Adam → 111, tête à zéro,
  `q_head` + `q_coef` 0,17 appliqués par le profil, échauffement 20 updates armé « tête Q jamais
  entraînée — jamais sauté »).
- Config (commit `a10adfdd9`) : `x1_lineage` de `ArmageddonAgent_x1_expl` porte
  `advantage_source: q_head`, `q_coef: 0.17` (= `vf_coef`, PREMIÈRE valeur, non calibrée — à
  lire sur `diag/grad_norm_q_mb0` contre `diag/grad_norm_policy_mb0` et
  `diag/grad_share_policy_mb0`, 0,62 sous `gae`). Le run est la MÊME étape E0 que S25 : P0,
  100 % P0 déterministe, siège 0,5, lr 0,0005, échauffement 20 ; seule la source d'avantage change.

**Règle de lecture, écrite AVANT le lancement.** Instrument : sondes exploiteur (100 parties /
2 000 épisodes, argmax des deux côtés, holdout, sièges 50/50), comparées à S25 au même point
(`training_x1_expl_01-e00-s25.log` + reprise `_02-e00-s25-reprise.log`) ; `03_selfplay/P0`
(échantillonné) en second ; holdout bots en parallèle (S25 : 0,933 à 20 000).
- **Garde de destruction à 10 000** : moyenne des sondes 2 000–10 000 ≤ 0,45 (S25 : 0,536 ;
  S11 détruit : 0,473 à 20 000) → S14 tel que codé détruit la politique déterministe ; arrêt.
  Diagnostic AVANT tout rerun : `diag/grad_share_policy_mb0` < 0,4 (le terme Q étouffe la
  politique sur le tronc partagé) → UN second run à `q_coef` 0,05, sinon réfuté.
- **Verdict à 30 000** : moyenne des sondes 20 000–30 000 (6 sondes, 600 parties, erreur-type
  ~1,9 pt) contre **0,677** (S25). ≥ 0,72 (+4 pts, plus de deux erreurs-types) → S14 déplace le
  plateau : continuer à 60 000 et lire si la montée continue vers 0,90 (objectif §9.4) ; entre
  0,64 et 0,72 → S14 ne change pas le plateau : réfuté comme levier, passer à S9 ; ≤ 0,63 →
  régression, arrêt et diagnostic ci-dessus.
- **Mécanisme, lu à updates égales** (même horloge que S25) : `train/adv_q_abs_mean` et
  `train/q_loss` (la tête apprend-elle ? `q_loss` doit descendre sous `value_loss` après
  l'échauffement), position de la coupure KL `train/n_minibatches_done` (S25 : 15–16 sur 32 ; un
  avantage moins dispersé doit la déplacer), `train/entropy_loss` (S25 plat à −0,68), EV. Un
  score qui monte SANS que la signature d'update bouge serait une surprise à expliquer avant
  d'y croire.
- Jugement à graine unique : un effet < 10 points exige une seconde graine (§9.5) avant de
  transférer le régime dans `x1_lineage` de `ArmageddonAgent_x1`.

#### 5.13.1 S14c — centrage de la tête Q sous π (2026-09-15, décision utilisateur de l'après-midi) {#s14c-2026-09-15}

**`run_20260915-134839` (log `training_x1_expl_03-e00-s14.log`) est la version NON CENTRÉE : il
ne juge pas S14.** Il court jusqu'à la garde de 10 000 puis est arrêté par l'utilisateur ; le
code centré n'est mergé qu'à cet arrêt (les workers d'évaluation rechargent le code de `main`).

**Cause, mesurée.** Audit sur 978 états du checkpoint
`ppo_checkpoint_20260915-134841_5767944_steps.zip` : **98 % de Var(A(s, a_jouée)) est une
constante par état** — écart-type 0,222 pour l'offset `Σ_a π(a|s)·A(s, a)` contre 0,027 entre
actions d'un même état. Rien dans `Q = V.detach() + A` ne distingue `V + A` de `(V − c) + (A + c)` :
la tête absorbait le biais de V dans un terme qui ne dépend que de `s`. Pour l'acteur, ce terme
est un gradient NUL en espérance (une baseline) mais, après `normalize_advantage` (par mini-lot,
pas par état), c'est lui qui fixe l'écart-type : le signal entre actions sortait à ~0,12
d'écart-type. L'acteur recevait un terme à variance 1 dont 98 % est un bruit d'espérance nulle,
persistant d'un mini-lot à l'autre — pire que le GAE. À réconcilier à la relecture : le run
loggue `train/adv_q_abs_mean` 0,055–0,076 sur ses mini-lots quand l'audit mesure sd 0,222 sur
ses 978 états ; un facteur ~4 entre E|A| et sd(A) exige une queue lourde (quelques familles
d'états à |offset| ~1) ou une distribution d'états différente ; la part de 98 % est un ratio,
robuste à ça. L'argument `q_loss − value_loss` (+0,0032 après l'échauffement, −0,0022 pendant,
lu sur les 85 premières updates) n'est PAS la justification et n'a pas à être prouvé.

**Correctif (worktree `tete-q-centrage-sous-pi`).** `ai/pointer_policy.py::center_under_policy` :
`A_c = A − Σ_a π(a|s)·A(s, a)` sur les probabilités MASQUÉES de la politique courante
(`MaskableCategorical` pose −1e8 hors légales : probs exactement nulles), π DÉTACHÉE (la perte Q
ne déplace pas la politique par le centrage) ; `evaluate_actions_q` rend cinq valeurs
(values, log_prob, entropy, `A_c(s, a_t)`, offset). Pourquoi π et non la moyenne uniforme :
`a_t ~ π`, donc `V = E_π[Q]` exactement et le biais de V est orthogonal au sous-espace de
moyenne nulle sous π — il reste à la charge de V. π courante et non celle du rollout : le
buffer ne garde que `old_log_prob` de l'action jouée ; l'écart est borné par le clip et la
coupure KL. `ai/patched_ppo.py::train` : `q_loss = MSE(retour λ, V.detach() + A_c)`, acteur sur
`A_c.detach()` ; tags `train/adv_q_offset_abs_mean` (offset retiré), `train/q_loss_mb0` et
`train/value_loss_mb0` (premier mini-lot AVANT tout pas d'Adam, V brute : la seule comparaison
hors échantillon par construction — `train/q_loss` mélange in-sample et hors-sample selon la
coupure KL, et dès le mini-lot 1 les retours λ de pas voisins déjà ajustés se recouvrent).
`is_untrained` et l'init à zéro inchangés : tête fraîche → A = 0, offset = 0, A_c = 0.
Tests `tests/unit/ai/test_q_head.py` : Σ π·A_c = 0 par ligne, invariance à une constante par
état, colonnes illégales sans effet, formes refusées, `evaluate_actions_q` = gather de A_c avec
offset = Σ π·A brut et (values, log_prob, entropy) inchangés, tags publiés en `q_head` et NaN
en `gae` (sauf `value_loss_mb0`, valide sous toute source) ; centrage retiré par mutation →
3 rouges.

**Lecture attendue, à ne pas prendre pour une régression.** Un offset à 0,222 d'écart-type
signifie que V est hors de ~0,2 dans certains états et que la tête le rapiéçait ; après
centrage ce biais retombe sur `value_loss` : EV peut fléchir au démarrage, c'est le critic qui
reprend sa charge.

**Règle du rerun, écrite AVANT relance — UN SEUL rerun S14 centré, pas de troisième version.**
Relance par l'utilisateur après merge : `python3 ai/train.py --agent ArmageddonAgent_x1_expl
--training-config x1_lineage --scenario bot --etape E0` (reprend P0, tête à zéro, échauffement
20 rejoué « jamais entraînée — jamais sauté »), log `training_x1_expl_04-e00-s14c.log`.
- Critère MÉCANISME : `train/q_loss_mb0 − train/value_loss_mb0 < 0` après l'échauffement, lu sur
  une fenêtre d'au moins 10 updates (erreur-type ~0,001 par update sur un mini-lot) = la tête
  centrée prédit une part du résidu de V sur des retours qu'elle n'a pas vus.
  `train/adv_q_offset_abs_mean` doit rester petit devant `train/adv_q_abs_mean` (le centrage
  retire l'offset AVANT la perte : une tête sous contrainte n'a plus de raison d'en produire).
- Critère SCORE : §5.13 inchangé — garde 10 000 (moyenne des sondes 2 000–10 000 ≤ 0,45 →
  arrêt), verdict 30 000 sur la moyenne 20 000–30 000 contre 0,677 : ≥ 0,72 oui ; 0,64–0,72
  réfuté ; ≤ 0,63 régression.
- Trois issues : (i) gap < 0 ET score monte → S14 tient, continuer à 60 000 (§9.9 étape 1,
  « si oui ») ; (ii) gap < 0 ET score plat → l'acteur n'exploite pas ce que la tête sait :
  jonction avec S9 (§9.9 étape 2 SUR S14) ; (iii) gap ≥ 0 → mémorisation résiduelle (capacité
  de la tête, un échantillon par (s, a), malédiction du vainqueur : l'acteur sélectionne sur les
  erreurs positives de A) → UNE variante S14c autorisée, choisie sur les tags et non les trois :
  régularisation de `adv_heads` (weight decay propre) / lr propre à la tête / mélange A_c–GAE.

**Instrument non bloquant** : `scripts/q_head_structure_probe.py` (test
`tests/unit/scripts/test_q_head_structure_probe.py`) décompose `q_loss − value_loss` en part
offset `E[c² − 2·c·R]` et part centrée `E[A_c² − 2·A_c·R]` sur un checkpoint `q_head`, collecte
sans entraînement (contexte de `grad_signal_probe.py::build_probe_context`, puis sa propre garde
`require_q_head_model` — miroir de `refuse_q_head_model`, qui reste à la sonde de gradient),
jackknife par rollout. À lancer sur le dernier checkpoint du run non centré quand le GPU est
libre : il documente le point de départ (part d'offset attendue ~0,98) et sert de référence au
tag `adv_q_offset_abs_mean` du rerun. Il ne conditionne ni le code ni la relance.

**Exécution (2026-09-15, 15:30 → 15:53).**
- **Garde à 10 000 NON déclenchée** : sondes 2 000–10 000 du run non centré 0,46 / 0,42 / 0,53 /
  0,50 / 0,51 → moyenne **0,484** > 0,45 (S25 au même point : 0,536, soit −5 pts). L'audit
  annonçait qu'elle tomberait ; elle ne tombe pas. Le run est arrêté à 10 150 **sur décision**
  (version disqualifiée par construction, GPU nécessaire à la version centrée), pas par la
  règle ; dernier checkpoint `ppo_checkpoint_20260915-134841_6487944_steps.zip` (59 118 cumulés).
- **Sonde de structure sur ce checkpoint** (6 rollouts, 48 960 pas, P0 déterministe,
  `logs/q_head_structure_s14_noncentre_10000.json`) : gap `q_loss − value_loss` = **+0,00408**
  [+0,0025, +0,0056] = offset **+0,00365** + centré **+0,00042** [+0,0002, +0,0006] + croisé 0,00001.
  **Part de Var(A) qui est l'offset : 0,941 [0,932, 0,950]** — la mesure de l'audit (0,98) est
  reproduite en ordre de grandeur. sd(A jouée) 0,087 ; sd(offset) 0,085 ; sd intra-état sous π
  0,0095 (rapport 8,9). E|A| 0,057 = le tag `train/adv_q_abs_mean` du run (0,055–0,076) :
  l'incohérence « sd 0,222 » venait du script jetable de l'audit (états ou normalisation
  différents), pas du run ; la part de 94 % tient. Référence pour le rerun :
  E|offset| 0,056 sur la tête non centrée.
- **Ce que la sonde ajoute au débat** : les DEUX parts sont positives hors échantillon — l'offset
  (mémorisation par état, +0,0037) ET la part centrée (+0,0004, sd(A_c) 0,02). Sur cette tête,
  la structure entre actions ne prédit rien du résidu non plus. Ça ne réfute pas le centrage
  (cette tête a dépensé sa capacité dans l'offset ; seule la version contrainte répond), mais
  ça donne son poids à l'issue (iii) de la règle : si `q_loss_mb0 − value_loss_mb0` reste ≥ 0
  sur le rerun, c'est la capacité / le bruit mémorisé, pas l'offset.
- Merge `5288f3921` (worktree `tete-q-centrage-sous-pi`, laissé en place : verrou d'une autre
  session vivante). **Rerun S14c lancé à 15:53** : `run_20260915-155352`, log
  `training_x1_expl_04-e00-s14c.log`, prologue « Echauffement critic + tête Q : 20 updates, tête
  Q jamais entraînée — jamais sauté ». Lecture par la règle ci-dessus : garde à 10 000 (~17:20),
  verdict à 30 000 (~20:30).

**Verdict S14c (2026-09-15, 19:10) — RÉFUTÉ, issue (iii), garde déclenchée.** Run
`run_20260915-155352` (`training_x1_expl_04-e00-s14c.log`). Sondes 2 000 → 20 000 : 0,53 / 0,49 /
0,31 / 0,23 / 0,25 / 0,27 / 0,42 / 0,41 / 0,51 / 0,45. **Garde à 10 000 déclenchée** (moyenne
2 000–10 000 = **0,362** ≤ 0,45) à 17:20 — **non lue à temps par l'agent**, run arrêté à
20 000 (19:10) au lieu de 10 000 : deux heures de GPU perdues, sans conséquence sur le verdict.
Dernier checkpoint `ppo_checkpoint_20260915-155353_7687944_steps.zip` (20 000 d'étape).

Mécanisme, 283 updates (TensorBoard `run_20260915-155352`) :
- `q_loss_mb0 − value_loss_mb0` **≥ 0 sur toute la durée** (+0,0002 à +0,0018 par tranche de
  20 updates, jamais négatif) → la tête centrée ne prédit rien du résidu de V hors échantillon :
  **issue (iii)** de la règle.
- `adv_q_abs_mean` **0,006** (l'avantage centré de l'action jouée est ~0 : c'est l'action
  dominante, centrée sur elle-même) ; sortie brute en dérive libre (`adv_q_offset_abs_mean`
  0,12 → 0,17, retiré avant la perte, sans effet sur l'acteur).
- `normalize_advantage` ramène ces ~0 à variance 1 : les rares coups non dominants, dont A_c est
  une estimation à UN échantillon, reçoivent des poussées de pleine force. Signature : entropie
  **0,71 → 0,28 nat** (S25 plate à 0,68), coupure KL après **6 mini-lots sur 32** (S25 : 15–16),
  part policy du gradient 0,90, `policy_gradient_loss` −0,015. La courbe échantillonnée fait la
  même vague que la sonde (0,49 → 0,32 → 0,50 → 0,34) : une politique qui s'aiguise à toute
  vitesse sur des avantages à un échantillon, puis oscille quand ils changent de signe
  (malédiction du vainqueur, exactement le mécanisme anticipé en §5.13.1).
- Ce n'est PAS la provenance de P0 (hypothèse utilisateur, écartée) : S25 a repris le même zip
  (copie identique), même profil, même échauffement, même adversaire, et est monté de 0,43 à
  0,73 ; la seule différence est `advantage_source`.

**Diagnostic.** Le centrage a fait ce qu'il devait (l'offset ne pousse plus l'acteur) et a révélé
le problème de fond : une tête Q(s, a) n'apprend les alternatives que si on les JOUE. Avec une
politique à p_max 0,66–0,99, elle n'a presque aucune donnée contrefactuelle ; ce qu'elle « sait »
des coups rares est le bruit d'un jet. Ce n'est pas un défaut de code : c'est un manque de
données d'exploration. **La variante S14c prévue par l'issue (iii) (régularisation / lr de
tête / mélange A_c–GAE) est ÉCARTÉE sans run** : aucune ne crée de données contrefactuelles ;
un mélange A_c–GAE redonnerait S25 plus du bruit. L'agent 2 avait raison sur le mécanisme,
l'agent 1 sur le défaut de construction ; les deux étaient nécessaires pour arriver ici.

**Ce qui départagerait S14 sans payer un run (≈ 30 min, décision utilisateur du 2026-09-15
soir).** Avec le code S9 (température de collecte), depuis le checkpoint S25 à 40 000
(`ppo_checkpoint_20260915-123207_10087944_steps.zip`, sans tête Q → tête à zéro, échauffement
jamais sauté) : profil `q_head` + `logits_temperature` 2 + `value_warmup_updates` 40 → la
politique reste FIGÉE (mode échauffement), la collecte se fait à T = 2 (coups exploratoires
joués), seules V et la tête Q apprennent ; lire `q_loss_mb0 − value_loss_mb0` sur les 20
dernières updates du régime. Règle : moyenne < −2 erreurs-types (≈ −0,002) → la tête sait
apprendre des alternatives quand on les lui joue, S14-SUR-S9 mérite un run plus tard ; sinon
S14 est mort dans ce dispositif, quoi qu'on fasse, et ne sera plus relancé. C'est le test qui
aurait dû précéder le run du matin.

### 5.14 S9 — température de collecte T = 2 (2026-09-15 soir, décision utilisateur) — CODE LIVRÉ, RÈGLE ÉCRITE {#s9-2026-09-15}

**Décision (2026-09-15, 19:40).** S14 réfuté faute de coups contrefactuels (§5.13.1) ; étape 2 de
l'ordre figé (§9.9). Question posée par l'utilisateur au passage : pourquoi P0 atteint 0,90
contre les bots quand P1 plafonne à 0,65 contre P0 — réponse consignée : ce n'est pas la même
échelle (P1 fait 0,907–0,933 sur le holdout bots), l'adversaire est d'une autre nature (une
copie de soi, parité à 0,50 par construction, avantage de siège 21 pts mesuré en S27) et la
seule différence de régime P0 → P1 jamais testée est l'**exploration** : P0 a appris sous
`ent_coef` 0,1 → 0,01 depuis une politique naïve, P1 reprend une politique à p ≈ 0,99 sous 0,01
constant. S9 est ce levier.

**Ce que fait S9.** `logits_temperature` (clé `model_params`, régime de run hors zip) :
`π_T = softmax(logits / T)` dans `PointerMaskablePolicy._distribution_from`, AVANT le masquage,
donc partout où l'apprenant construit une distribution — collecte dans les workers (politique
transportée par `_serialize_policy_for_workers`), ratio PPO et entropie dans `train`. Collecte
et ratio sous la même π_T : on-policy, PPO optimise π_T. Un zip rechargé repart à T = 1 :
sondes, holdout, adversaires figés du pool et PvE jouent la politique à T = 1 (l'argmax est
invariant à T). Propriété `PatchedMaskablePPO.logits_temperature` qui écrit sur la politique
(`--new` par le constructeur, `--append` par `_PLAIN_CURRICULUM_KEYS`), exclue du zip ; refus
d'une valeur non flottante > 0 et d'une politique qui ne tempère pas. T = 2 : sur des têtes
courtes à p ≈ 0,99 (écart de logits ≈ 4,6), l'alternative se joue ~1 fois sur 11 au lieu de
1 sur 100. Première valeur, non calibrée.

**Livré** (worktree `s9-temperature-collecte`) : `ai/pointer_policy.py`, `ai/patched_ppo.py`,
`ai/train.py`, `tests/unit/ai/test_logits_temperature.py` (8 tests : softmax(logits/T) sur les
légales, argmax invariant, collecte et ratio sous la même π_T, constructeur / profil / zip /
workers, refus ; division retirée par mutation → 2 rouges) ; profil `x1_lineage` de l'agent
expl : `advantage_source: gae`, `logits_temperature: 2.0`, `_doc` des deux clés ;
`Documentation/Reference/training/entrainement.md`.

**Limite connue, à lire AVANT le verdict.** Rien n'empêche le réseau d'absorber T en doublant
l'échelle de ses logits ; seul `ent_coef` 0,01 s'y oppose. L'exploration apportée par T peut
donc être transitoire.

**Règle de lecture, écrite AVANT le lancement (= §9.9 étape 2b).**
- **2a — mesure préalable (~30 min)** : checkpoint S25 40 000
  (`ppo_checkpoint_20260915-123207_10087944_steps.zip`, sans tête Q → tête à zéro) + profil
  transitoire `q_head` / `q_coef` 0,17 / `value_warmup_updates` 40 / T = 2 : politique FIGÉE
  (échauffement), collecte à T = 2, seules V et la tête Q apprennent. Lire
  `train/q_loss_mb0 − train/value_loss_mb0` sur les updates 20–40 : moyenne < −0,002 → la tête
  sait apprendre des alternatives quand on les lui joue, S14-SUR-S9 rejouable après S9 ;
  sinon S14 mort dans ce dispositif. Profil remis à `gae` après la mesure (édition transitoire,
  non commitée).
- **2b — run S9** : `--etape E0` depuis P0 (échauffement 20 rejoué), log
  `training_x1_expl_05-e00-s9.log`. **Juge = sonde exploiteur argmax + holdout bots ;
  `03_selfplay/P0` N'EST PAS un juge** (agent échantillonné, plus aléatoire sous T = 2 par
  construction : cette courbe sera plus basse que S25 sans rien dire de la politique apprise).
  Garde à 10 000 : moyenne des sondes 2 000–10 000 ≤ 0,45 → arrêt. Verdict à 30 000 : moyenne
  20 000–30 000 contre 0,677 (S25) ; ≥ 0,72 oui ; 0,64–0,72 réfuté ; ≤ 0,63 régression.
  **Absorption** : `train/entropy_loss` (entropie de π_T) par tranche de 2 000 — elle doit
  partir nettement au-dessus de S25 (0,68 nat) ; si elle y retombe avant 20 000, S9 est réfuté
  PAR ABSORPTION (distinct de « l'exploration ne sert à rien ») et le levier suivant n'est pas
  un T plus grand mais un mécanisme que l'optimiseur ne peut pas défaire — à arbitrer alors,
  pas maintenant. `family_entropy_probe` sur le checkpoint 30 000 contre S25 pour nommer les
  têtes qui ont gardé de l'entropie.
- Si oui : garder T ; si 2a positif, S14 SUR S9 (un run, règle §5.13.1) ; sinon étape 3.

**Résultat 2a (2026-09-15, 19:42 → 20:33, `run_20260915-194206`, log
`training_x1_expl_mesure2a-q-head-T2.log`) — NÉGATIF : S14 est mort dans ce dispositif.** Reprise
du checkpoint S25 40 000 (compteur 90 084, d'où le départ à 90k sur TensorBoard : c'est S25
prolongé, politique figée, PAS le run S9), échauffement 40 updates (KL = 0 sur les 40), collecte
à T = 2 : entropie sous π_T **1,04 nat** (0,68 à T = 1), `adv_q_abs_mean` **0,03** (0,006 sur
S14c : les coups joués sont 5 fois plus variés — la tête AVAIT des données contrefactuelles).
`q_loss_mb0 − value_loss_mb0` sur les updates 20–40 : **+0,00250 ± 0,00098** (2 erreurs-types),
même signe et même ordre que sur S14c (+0,0002 à +0,0018) ; en in-sample (`train/q_loss` contre
`train/value_loss`) le gap est nul à 10⁻⁴ près : la tête n'améliore la prédiction du retour ni
hors ni dans l'échantillon. `03_selfplay/P0` à 0,53 contre 0,65 : effet du seul échantillonnage à
T = 2 (politique figée), confirmation que cette courbe n'est pas un juge sous T. **Conclusion :
une tête Q(s, a) régressée sur le retour λ, même nourrie de coups alternatifs, ne prédit rien de
plus que V dans ce jeu — le résidu R − V est du dé, pas de la structure (s, a) apprenable à un
échantillon par pas. S14 ne sera plus relancé, ni seul ni sur S9.** Ce qui reste de S14 : le code
(désactivé, `gae`), `q_head_structure_probe.py`, et une conclusion mesurée qui vaut pour toute
variante « avantage appris par régression » — S15 (recherche : moyenne les dés par SIMULATION,
pas par régression) n'est pas touché par ce verdict.

**Run S9 lancé à 20:34** : `run_20260915-203437`, log `training_x1_expl_05-e00-s9.log`, E0
depuis P0 (50 000), échauffement critic 20, `advantage_source: gae`, `logits_temperature` 2,0.
Lecture par la règle 2b ci-dessus : garde 10 000, absorption sur `train/entropy_loss`, verdict
30 000 contre 0,677.

**Lecture à 18 000 (2026-09-16, 00:05) — garde passée, absorption EN COURS, plateau non tranché.**
Sondes 2 000 → 18 000 : 0,53 / 0,59 / 0,56 / 0,66 / 0,68 / 0,62 / 0,67 / 0,76 / 0,67. Garde :
moyenne 2 000–10 000 **0,604** (S25 : 0,536, +7 pts) → passée. 12 000–18 000 : 0,68 (S25 : 0,68) —
départ plus rapide, même niveau ensuite ; `a_vp_diff` meilleur que S25 (lecture utilisateur, à
chiffrer sur `01_VP/a_vp_diff`). Mécanisme à updates égales (262 premières updates, S25 sur
les mêmes) : entropie de π_T **1,16 → 0,80 nat** par huitième (S25 à T = 1 : 0,80 → 0,74) —
au-dessus du seuil d'absorption (0,68) à 18 000, mais en descente rapide : T est absorbé
progressivement, pas encore entièrement ; à relire à 20 000 et 30 000 (retour à 0,68 =
réfuté par absorption). Coupure KL **32 → 16,7** mini-lots (S25 : 28,9 → 13,6) : à KL égal
(0,009), S9 apprend sur plus de mini-lots par update. EV 0,84 → 0,87. Utilisateur (00:10) :
« il vient de franchir les 70 % » — sonde 20 000 attendue ; **rien n'est arrêté**, verdict à
30 000 par la règle.

**Lecture à 20 000 (2026-09-16, 00:45) — sonde 0,80, absorption ARRÊTÉE à 0,80 nat, holdout bots en
recul.** Lecture à épisodes égaux : correspondance épisode → pas par `config/discount_factor` (un point
par épisode sur l'axe des pas), `train/*` moyennés sur les updates de chaque tranche de 2 000 (26–29
updates par tranche), S25 = `run_20260914-215728` (+ reprise) aux mêmes tranches.
- **Sonde 20 000 : 0,80** (S25 au même point : 0,68) — première des six sondes du verdict
  (20 000 → 30 000 inclus, moyenne contre 0,677). Arithmétique de la règle : les cinq sondes
  restantes doivent faire ≥ 0,704 en moyenne pour atteindre 0,72 ; S25 y faisait 0,677.
- **Absorption : arrêtée, pas achevée.** Entropie de π_T par tranche (2 000 → 22 000) :
  1,07 / 0,95 / 0,91 / 0,88 / 0,85 / 0,81 / 0,80 / 0,80 / 0,79 / 0,80 ; S25 (π à T = 1) aux mêmes
  tranches : 0,78 / 0,76 / 0,75 / 0,74 / 0,74 / 0,70 / 0,68 / 0,65 / 0,68 / 0,68. La descente
  s'est arrêtée à 14 000 ; l'écart S9 − S25 est passé de 0,29 nat (2 000–4 000) à 0,12 et n'a plus
  bougé sur les quatre dernières tranches. 0,68 n'est pas atteint → **pas de réfutation par
  absorption** ; le surplus d'entropie restant (0,12 nat) est ce que `ent_coef` 0,01 retient.
- Coupure KL : **15,8 puis 16,5** mini-lots sur 32 (S25 : 13,8 / 15,2) à KL égal
  (0,0086 / 0,0084) ; EV 0,87–0,88 des deux côtés ; `policy_gradient_loss` −0,010 (S25 −0,007).
- Courbes échantillonnées (PAS des juges — l'agent S9 y joue à T = 2) : `01_VP/a_vp_diff`
  **+8,0 / +8,8** sur 18 000–22 000 (S25 : +4,1 / +4,4), `01_VP/d_objectives_held_diff` +0,18 / +0,23
  (S25 : +0,02 / +0,04), `03_selfplay/P0` 0,667 / 0,673 (S25 : 0,634 / 0,630). Contrairement à
  l'attente écrite en 2b (« plus basse que S25 par construction »), la courbe échantillonnée est
  au-dessus de S25 malgré l'échantillonnage à T = 2.
- **Holdout bots (second juge de la règle) : combiné 0,897 à 10 000 → 0,848 à 20 000, pire bot
  0,85 → 0,80** (`bot_eval/combined`, `bot_eval/worst_bot_score`) ; S25 : 0,887 → 0,933 → 0,923 à
  30 000, pire bot 0,83 → 0,85 → 0,89. S9 gagne contre P0 et recule contre les bots ; à 20 000 il
  est sous P0 lui-même (combiné 0,910 au meilleur robuste de P0). Aucun score robuste enregistré
  (`robust=NA` sur toute la barre ; S25 affichait 0,9094 dès 20 000). **À relire à 30 000** avec
  le holdout de 30 000 : sonde qui passe ET holdout qui continue de baisser = spécialisation
  contre P0, exactement ce que le gate 0,65 + holdout de la lignée est fait pour attraper ; la
  règle 2b ne tranche que sur la sonde, le holdout est consigné à côté et pèsera au transfert
  (étape 4).
- Rien n'est arrêté ; verdict à 30 000 (≈ 02:15 au rythme mesuré de 5 400 épisodes/h) par la règle.

**VERDICT À 30 000 (2026-09-16, sonde à 01:57, lecture 02:25) — OUI : S9 DÉPLACE LE PLATEAU, le run
continue à 60 000.** Sondes 20 000 → 30 000 (six, bornes incluses, même convention que S25) :
0,80 / 0,72 / 0,69 / 0,68 / 0,71 / **0,78** → moyenne **0,730** contre **0,677** (S25, même fenêtre) et
0,683 (S25, 30 000–40 000) ; règle 2b : ≥ 0,72 → oui. Moyenne des trois dernières 0,723 (S25 au
même point : 0,647). Bruit, consigné et non rediscuté : erreur-type d'une moyenne de six sondes à
100 parties ≈ 1,9 pt, d'un écart de deux fenêtres ≈ 2,7 pts → +5,3 pts ≈ 2 σ ; §9.3 (deux graines
sous 10 pts) s'applique au transfert, pas à la lecture. Rien n'est arrêté : E0 s'arrête seul à
`budget_cap` 60 000.
- **Holdout bots (second juge) : 0,893 à 30 000** (0,897 → 0,848 → 0,893 ; `bot_eval/combined`),
  pire bot 0,85, siège 1 0,977 / siège 2 0,827, scénarios 0,967 / 0,967 / 0,787 / 0,853 ; S25 à 30 000 :
  0,923 ; P0 : 0,910. Le creux de 20 000 était un creux, pas une pente. S9 tient le niveau de P0
  contre les bots (3 pts sous S25, n = 300 → ±2,5) et n'y progresse pas pendant qu'il gagne +5 pts
  contre P0 ; les bots sont saturés (0,86–0,99, D2) : ce juge ne voit plus un progrès, seulement une
  chute — il n'y en a pas.
- **Absorption, pente 20 000–30 000** : entropie de π_T par tranche 0,80 / 0,80 / 0,79 / 0,75 / 0,76 →
  ≈ −0,04 nat par 10 000 (S25 : 0,68 / 0,68 / 0,67 / 0,67 / 0,70) ; 0,68 non atteint. Coupure KL
  **revenue au niveau S25** : 16,5 → 15,1 mini-lots sur 32 (S25 15–16) ; KL 0,008–0,009 (une tranche à
  0,016 : 22 000–24 000, pic ponctuel) ; EV 0,87–0,88 ; `policy_gradient_loss` −0,011 → −0,008 (S25
  −0,008 / −0,009). L'avantage de mini-lots des 20 000 premiers épisodes a disparu ; la signature
  d'update est redevenue celle de S25 alors que la sonde continue de monter.
- Courbes échantillonnées (T = 2, pas juges) : `a_vp_diff` +8,8 → **+10,5** (S25 +4,4 → +4,1),
  `d_objectives_held_diff` +0,23 → +0,31 (S25 +0,04 → +0,03), `03_selfplay/P0` 0,673 → 0,710 (S25
  0,630 → 0,633) : la marge se construit sur les objectifs tenus.
- **Sonde par famille** (`scripts/family_entropy_probe.py`, A = checkpoint S9
  `ppo_checkpoint_20260915-203439_8887944_steps.zip` ≈ 30 000, qui échantillonne à T = 1 puisqu'un zip
  rechargé repart à T = 1 ; B = checkpoint S25 `..._20260914-215730_8887944_steps.zip` = 30 000 ; 6
  épisodes, 1 454 décisions, `nice`) — **à T = 1, S9 est PLUS pointue que S25 sur toutes les grandes
  têtes** : move_cell H **1,47 contre 2,23** nat (p_max 0,53 / 0,36), choice 0,73 / 0,81, activate 0,31 /
  0,34, shoot_slot 0,34 / 0,45, charge 0,07 / 0,14 ; plus haute seulement sur deploy 0,20 / 0,14,
  shoot_weapon_sel 0,79 / 0,74, oath 0,30 / 0,23, fight_slot 0,48 / 0,15 (n = 8). Argmax différents :
  move **72 %**, shoot 61 %, activate 54 %, choice 36 %, deploy 37 % — une politique substantiellement
  différente, pas S25 avec du bruit. Réponse à la question de la règle (« quelles têtes ont gardé de
  l'entropie ») : **aucune des grandes**. Le réseau a absorbé T en affûtant ses logits (π à T = 1 plus
  pointue que S25) ; le surplus d'exploration qui a fait le résultat ne vit que dans π_T, la politique
  de collecte (0,76 nat contre 0,70 pour S25 à T = 1) — l'argmax évalué en a profité. Conséquence pour
  le transfert (étape 4) : T se règle comme un paramètre de collecte, et « pas d'absorption » ne se lit
  pas sur `train/entropy_loss` seul mais sur cette sonde à T = 1.

**Règle pour la suite du run, écrite le 2026-09-16 à 02:30, AVANT les données.** À 40 000 : moyenne
des six sondes 30 000–40 000 (30 000 incluse, 0,78) ; **≥ 0,76** → la montée continue ; **0,70–0,76**
→ plateau déplacé et tenu, acquis, transfert préparé ; **< 0,70** → l'écart de 30 000 était du bruit,
seconde graine obligatoire avant tout transfert (§9.3). Même lecture à 60 000 sur 50 000–60 000, plus
holdout bots (≥ 0,88 attendu, sinon spécialisation) et `family_entropy_probe` sur le checkpoint
final. Après 60 000, ordre §9.9 : « garder T ; 2a négatif → étape 3 » (C2 puis B6 seconde graine,
SOUS T) puis étape 4 (transfert, relecture lr / `target_kl` / `ent_coef` sous T) — le prompt de reprise
du 2026-09-16 lisait « étape 4 directement » ; la lecture de la montée à 60 000 précède ce choix,
qui appartient à l'utilisateur.

**Matrice d'adversaires tenus hors entraînement (2026-09-16, 02:25 → 03:20) — « à 70 %, l'agent
apprend-il encore à jouer ou se spécialise-t-il contre le champion ? » (question utilisateur).**
Instrument : `scripts/seat_matrix_probe.py` (celui de S27), lecture seule, 300 parties par cellule,
argmax des deux côtés, sièges 50/50 (`x1_lineage`), graine tirée au hasard, 8 workers sous `nice`
pendant que S9 tourne (≈ 10 min par cellule). Évalués : les checkpoints 30 000 de S9 et de S25 (ceux
de la sonde par famille). Adversaires que NI S9 NI S25 n'ont jamais affrontés (100 % P0 à
l'entraînement) : P1 de lignée `robust_0.9078` (entraîné contre P0 à 70 % + bots), témoin entnorm
`20260913-040721` (à froid contre les bots seuls, 22–28 % contre P0), et l'autre exploiteur.
**Règle posée au lancement (02:25), avant les données** : S9 ≥ S25 + 5 pts sur les adversaires
tenus hors → le gain contre P0 GÉNÉRALISE ; S9 ≈ S25 hors de P0 avec +5 sur P0 → spécialisation.
Le holdout bots ne peut plus trancher cette question : bots saturés (D2), il ne voit qu'une chute.

| évalué → archive figée | score (n = 300) |
|---|---|
| P0 → P1 (S27, déduit de P1 → P0 = 0,642) | 0,36 |
| **S25 (30 000) → P1** | **0,50** (150/300) |
| **S9 (30 000) → P1** | **0,62** (186/300) |
| **S9 (30 000) → S25 (30 000)** | **0,68** (204/300, 1 nul) |
| P0 → témoin entnorm (§5.5, complément du 0,28 mesuré le 2026-09-13) | ≈ 0,72 |
| **S25 (30 000) → témoin entnorm** | **0,70** (211/300, 1 nul) |
| **S9 (30 000) → témoin entnorm** | **0,68** (205/300, 1 nul) |

JSON et journal : `logs/matrix_heldout_20260916/` (ignoré par git).

Lecture (deux cellules) : S9 gagne **+12 pts** sur S25 contre un adversaire tenu hors (erreur-type
d'une cellule 2,8 pts, de l'écart ≈ 4 pts → ≈ 3 σ) contre **+5 pts** sur P0 (sondes) : le gain
n'est pas confiné à P0, il est même plus grand hors de P0. Au même instrument, S25 (0,50) avait déjà
généralisé une partie de ses +9 pts sur la lignée (P0 : 0,36). À 30 000, S9 apprend à jouer contre
cette famille de politiques ; « spécialisation contre le champion » est réfutée sur P1. Réserve :
P1 descend de P0 (même lignée, même observation) ; les cellules entnorm (autre origine, aucune
parenté) complètent la réponse. Ce que la matrice ne dit pas : si S9 est lui-même exploitable
(cycle pierre-feuille-ciseaux) — cela se mesure en entraînant un exploiteur CONTRE S9 (~5,5 h), et
c'est ce que le gate de lignée (battre le champion ET chaque membre du pool, `evaluate_pool_decision`)
protège à partir de P2 ; en P1, pool à un membre (D1), rien ne le protège.

**Lecture complète (03:10, cinq cellules).** S9 bat directement l'autre exploiteur de P0 : S9 → S25
**0,68**. Contre le témoin entnorm (aucune parenté avec P0 : à froid contre les bots seuls, 40 000
épisodes) : S9 0,683, S25 0,703, écart −2 pts dans le bruit (±3,7 sur un écart de cellules) ; P0
lui-même fait ≈ 0,72 contre ce témoin. Lecture : le gain de S9 est réel et transférable, mais **à
l'intérieur de la famille de P0** — +5 sur P0, +12 sur P1 (élève de P0), 0,68 sur S25 (exploiteur de
P0) — et **nul hors de cette famille** : contre un style sans parenté, S25, S9 et P0 sont à 0,70 /
0,68 / ≈ 0,72, tout dans ±3 pts, aucun gain ni aucune perte après 30 000 épisodes joués à 100 %
contre P0. Ce n'est donc ni une spécialisation contre le seul champion (réfutée sur P1 et S25) ni
un progrès général au jeu mesurable (rien contre un style étranger, rien contre des bots saturés) :
à 30 000, l'exploiteur a appris à battre ce que P0 a façonné. Règle posée au lancement (S9 ≥ S25 + 5
hors de P0) : tenue sur P1, non tenue sur entnorm, consigné tel quel. Conséquence pour la lignée : le
juge de progrès GÉNÉRAL manque — holdout bots saturé, P1 et tout futur membre descendent de P0 ;
un second champion sans parenté (contrôle P0 à froid, option C de l'arbitrage du 2026-09-16) et le
témoin entnorm gardé comme cellule fixe de toute matrice future sont les seuls instruments qui
distingueront « apprend le jeu » de « apprend la famille ».

**Lecture à 40 000 (2026-09-16, sonde à 03:47, lecture 04:05) — LA MONTÉE CONTINUE, à la borne exacte
de la règle.** Sondes 30 000 → 40 000 (six, bornes incluses) : 0,78 / 0,73 / 0,75 / 0,75 / 0,76 / **0,79**
→ moyenne **0,760** (4,56 / 6, exactement le seuil « ≥ 0,76 → la montée continue » écrit à 02:30 ;
appliqué tel quel, l'écart au seuil est nul et l'erreur-type de la moyenne 1,9 pt). Fenêtre précédente
0,730 (+3,0 pts) ; S25 sur la même fenêtre : 0,683 (+7,7 pts pour S9) ; moyenne des trois dernières
0,767. **Holdout bots à 40 000 : 0,907** (0,897 → 0,848 → 0,893 → 0,907), pire bot 0,86, siège 1 0,977 /
siège 2 0,851 ; P0 : 0,910 — aucune dégradation contre les bots pendant que la sonde monte.
Mécanisme 30 000–40 000 : entropie de π_T 0,76 / 0,75 / 0,76 / 0,76 / 0,73 (S25 : 0,71 / 0,70 / 0,68 /
0,69 / 0,70) — plate puis un cran plus bas sur la dernière tranche, 0,68 non atteint ; coupure KL
15,5–17 mini-lots (S25 15,5–16,4, identique) ; EV 0,87–0,89 ; courbes échantillonnées `a_vp_diff` +11,6
→ +11,9 (S25 +4,6 → +5,9), `03_selfplay/P0` 0,727 → 0,735 (S25 0,634 → 0,654), objectifs tenus +0,36 /
+0,37 (S25 +0,04 → +0,10). La signature d'update est celle de S25 depuis 20 000 ; ce qui diffère est la
politique de collecte à T = 2 et la politique apprise (sonde par famille du 30 000). Lecture suivante à
60 000 (fin de budget E0, vers 07:30) par la règle du 02:30 : moyenne 50 000–60 000, holdout ≥ 0,88,
`family_entropy_probe` sur le DERNIER `ppo_checkpoint` (le canonique de fin de run est l'instantané
holdout, pas les poids finaux — §9.6 R2).

**Lecture finale à 60 000 (2026-09-16, sonde à 07:11, budget E0 atteint : « plafond 60000 episodes
atteint sans franchir 95% ») — LE PLATEAU EST DÉPLACÉ DE ~0,68 À ~0,78, ET IL EST PLAT DEPUIS 40 000.**
Sondes 40 000 → 60 000 : 0,79 / 0,79 / 0,81 / 0,80 / 0,77 / 0,74 / 0,73 / 0,78 / 0,78 / 0,80 / 0,77.
Fenêtres de six : 20 000–30 000 **0,730** · 30 000–40 000 **0,760** · 40 000–50 000 **0,783** ·
50 000–60 000 **0,767** (S25 : 0,677 puis 0,683, arrêté à 40 084). Règle du 02:30 sur 50 000–60 000 :
0,767 ≥ 0,76 → « la montée continue » par la lettre ; lecture de fond : −1,6 pt sur la fenêtre
précédente, onze sondes à 0,778 de moyenne depuis 40 001 — **un plateau à 0,77–0,78**, +10 pts sur
S25 (0,68), +14 pts sur la lignée P1 à sièges égaux (0,642, S27), 12 pts sous l'objectif de §9.4
(~0,90). Moyenne des trois dernières 0,783.
- **Holdout bots : 0,897 → 0,848 → 0,893 → 0,907 → 0,922 à 50 000** (pire bot 0,86) ; instantané
  robuste **0,9072** sauvé à 05:37 (= canonique `model_ArmageddonAgent_x1_expl.zip`, §9.6 R2 : le
  canonique est l'instantané holdout, PAS les poids finaux — les poids finaux sont
  `ppo_checkpoint_20260915-203439_12247944_steps.zip`, copiés dans `logs/matrix_heldout_20260916/s9_final_ckpt/`).
  S25 : 0,933 maximum, robuste 0,9094. Évaluation finale à 60 000 en cours à l'heure de la lecture (résultat : 0,902 puis 90,3 % sur 1 800 parties, « Clôture S9 » ci-dessous).
- **Absorption, achevée lentement** : entropie de π_T par tranche 40 000 → 60 000 : 0,73 / 0,72 / 0,71 /
  0,73 / 0,72 / 0,71 / 0,71 / 0,73 / 0,72 / 0,73 — soit 1,07 → 0,80 (à 14 000) → 0,76 (à 30 000) → 0,72
  (à 60 000), contre 0,69 pour la π de S25 à T = 1 à 40 000 : le surplus d'exploration à la collecte
  est passé de 0,29 nat à ~0,03 nat. La sonde a cessé de monter à 40 000, quand ce surplus était à
  ~0,05 nat. Corrélation consignée, pas causalité prouvée ; elle est cohérente avec la limite écrite
  avant le run (« rien n'empêche le réseau d'absorber T ») et avec la sonde par famille du 30 000
  (π à T = 1 déjà plus pointue que S25). Coupure KL 14–16 mini-lots (S25 15–16), EV 0,87–0,89,
  `a_vp_diff` échantillonné plat à +12 (S25 +6), `03_selfplay/P0` plat à 0,75, objectifs tenus +0,38.
- En cours à la lecture : `family_entropy_probe` sur les poids finaux contre le checkpoint S25 de
  40 000, matrice hors entraînement des poids finaux (P1, S25 30 000, témoin entnorm), ligne de
  clôture E0 dans `curriculum.log` — consignés dans « Clôture S9 » ci-dessous (08:00).

**Ce que S9 établit et ce qu'il n'établit pas.** Établi : le mécanisme d'apprentissage extrait plus de
P0 quand la collecte explore (une seule graine, +10 pts, ≈ 4 σ sur une fenêtre de six sondes contre
S25) ; le gain se transfère à la famille de P0 (matrice du 30 000) et ne coûte rien contre les bots.
Non établi : que 0,90 soit atteignable par ce levier — l'effet s'éteint avec l'absorption de T, et un
T plus grand n'est pas le levier suivant (règle 2b) : c'est un mécanisme d'exploration que l'optimiseur
ne peut pas défaire (plancher d'entropie ou coefficient d'entropie adaptatif par famille, mélange
ε avec ratio corrigé, contrainte sur l'échelle des logits), à arbitrer avec la suite (§9.9 étape 3
sous T, étape 4 transfert, ou contrôle P0 à froid — arbitrage soumis à l'utilisateur le 2026-09-16).

**Clôture S9 (2026-09-16, processus terminé à 07:54) — mesures des poids finaux.** `curriculum.log`
ligne 17 : E0, 60 000 épisodes, budget censuré (« > 60000 », seuil 95 % non atteint), pas de gate
(exploiteur). Holdout bots à 60 000 : **0,902** (pire bot 0,86, siège 1 0,951 / siège 2 0,863) ;
évaluation finale sur 1 800 parties : **90,3 %** (alpha 89,0 · attrition 89,7 · decapitation 92,0 ·
endgame 95,7 · racer 86,0 · scorer 89,3 ; écart Space Marines − Orks +10,1 pts). Série holdout
complète : 0,897 / 0,848 / 0,893 / 0,907 / 0,922 / 0,902 ; canonique = instantané robuste 0,9072 du
50 000 (S25 : 0,9094).

Matrice hors entraînement des POIDS FINAUX (`ppo_checkpoint_20260915-203439_12247944_steps.zip`,
copie dans `logs/matrix_heldout_20260916/s9_final_ckpt/` ; même instrument, 300 parties, argmax,
sièges 50/50, GPU libre : ~200 s par cellule) :

| évalué → archive figée | S9 à 30 000 | **S9 à 60 000** | S25 à 30 000 | P0 |
|---|---|---|---|---|
| → P1 de lignée `robust_0.9078` | 0,62 | **0,64** (191/300, 2 nuls) | 0,50 | 0,36 |
| → S25 (30 000) | 0,68 | **0,69** (208/300) | — | — |
| → témoin entnorm (sans parenté) | 0,68 | **0,71** (214/300, 1 nul) | 0,70 | ≈ 0,72 |
| → P0 (sonde, fenêtre de six) | 0,730 | **0,767** | 0,677 | — |

Lecture : de 30 000 à 60 000, +1 à +3 pts sur chaque adversaire tenu hors (dans ±2,6 par cellule)
pour +4 pts sur P0 ; la conclusion du 30 000 tient : le gain sur S25 est propre à la famille de P0
(P1 +14, S25 +19 en direct) et **nul contre le style sans parenté** (0,71 contre 0,70 pour S25 et
≈ 0,72 pour P0). Sonde par famille des poids finaux contre le checkpoint S25 de 40 000 (T = 1, 6
épisodes, 1 421 décisions, `logs/matrix_heldout_20260916/family_entropy_s9final_vs_s25_40000.txt`) :
S9 reste plus pointue sur mouvement (1,80 contre 2,16 nat), activation (0,26 / 0,30) et déploiement
(0,17 / 0,21), mais est désormais plus plate sur cible de tir (0,42 / 0,32), choix d'arme (0,70 /
0,61), oath (0,30 / 0,05) et wait (0,67 / 0,50) ; charge effondrée des deux côtés (0,010 / 0,023) ;
argmax différents : mouvement **84 %**, oath 75 %, cible de tir 64 %, activation 52 %, charge 0 %.
Nuance par rapport au 30 000 (où S9 était plus pointue sur toutes les grandes têtes) : à 60 000,
l'exploration résiduelle de T (0,03 nat sur π_T) s'est logée dans les têtes de tir et d'oath, pas
dans le mouvement ni la charge. Les états sont ceux que S9 visite : famille rare = peu de lignes.
Le GPU est libre depuis 07:54 ; rien n'est lancé sans décision (arbitrage du 2026-09-16 : étape 3
sous T / étape 4 transfert / contrôle P0 à froid ; mécanisme d'exploration non absorbable à
arbitrer ensuite).

**Bilan complet S9 (2026-09-16, 08:30) — mesures de jeu par bloc de 10 000 épisodes, courbes
échantillonnées (S9 joue à T = 2 pendant l'entraînement : les valeurs absolues sont abaissées de ~2 pts
par rapport à la sonde argmax ; les écarts S9 − S25 sur la MANIÈRE de gagner restent lisibles).**
Blocs 40 000–50 000, S9 / S25 : VP de l'agent **48,7 / 47,8**, VP de P0 **36,4 / 41,3** — la marge
(+12 contre +6,5) vient du DÉNI des points de P0, pas d'un gain propre ; objectifs tenus 2,52 / 2,42 ;
victoires quand l'agent se déploie lui-même (90 % des épisodes) **0,78 / 0,68**, quand le moteur le
déploie (10 %) 0,49 / 0,45 → l'avantage se construit au déploiement et à la tenue d'objectifs. Combat
identique : ratio de valeur détruite / perdue 1,77 / 1,76, figurines tuées 0,53 / 0,50, figurines
perdues **0,31 / 0,26** (S9 échange plus), charges 4,8 / 4,9 par partie à 0,36 / 0,38 de réussite, tir
0,53 / 0,50 de participation à 0,63 / 0,62 de précision, avance 0,28 / 0,21, fuite 0,016 / 0,016, durée
116 / 121 pas. Siège (cumul depuis le départ, échantillonné) : S9 premier joueur 0,72 / second 0,59
(20 000–30 000 : 0,64 / 0,54) contre S25 0,66 / 0,66 (0,59 / 0,58) — S9 gagne surtout en jouant
premier ; holdout bots par siège à 60 000 : 0,951 / 0,863 (S25 à 10 000 : 0,947 / 0,839). Récompense :
marge de VP 73 / 32, issue ±150 → +76 / +44, bonus de combat 198 / 197, pénalités −111 / −112, total
par épisode 256 / 180. Réserves détruites au tour 3 : 0,009 / 0,000 par épisode (effet mineur de
l'échantillonnage à T = 2 sur les refus d'arrivée). Aucune action invalide. Durée : 20:34 → 07:09
pour 60 000 épisodes (10 h 34, ~5 700 épisodes/h), évaluation finale jusqu'à 07:54.

### 5.15 B — transfert du régime S9 dans la lignée : P1 depuis P0 sous température (2026-09-16, décision utilisateur) — RÈGLE ÉCRITE, RUN LANCÉ {#b-2026-09-16}

**Décision (2026-09-16, 09:30).** « OK pour B avec les deux clés. » Le profil `x1_lineage` de
`ArmageddonAgent_x1` reçoit le régime d'apprentissage mesuré sur S9 — `learning_rate` 0,001 →
**0,0005** (valeur finale de la rampe de P0 ; §9.2 : 0,001 reprenait au double du pas où la
politique avait convergé) et **`logits_temperature` 2,0** — et rien d'autre : le dessin d'adversité
de la lignée est conservé (70 % des parties en second, 30 % de bots, P0 tirant ses coups au sort,
gate sur trois sondes de 300 parties). Pourquoi les deux clés et non la seule température : la
combinaison T = 2 avec 0,001 n'a jamais été mesurée (la température adoucit les mises à jour, le pas
doublé les durcit, effet net inconnu) ; on transfère la configuration qui a produit 0,78, on n'en
invente pas une troisième. Coût assumé : si ça passe, l'attribution entre les deux clés n'est pas
faite dans la lignée (S9 contre S25 l'a faite chez l'exploiteur ; la lignée à 0,001 sans
température a échoué six fois). Livré : `config/agents/ArmageddonAgent_x1/ArmageddonAgent_x1_training_config.json`
(clés + `_normal` + `_doc`), `tests/unit/ai/test_training_config_par_etape.py` (valeurs épinglées,
rouge sur l'ancien profil / vert sur le nouveau, 172 tests verts sur les quatre fichiers touchés),
merge `3ef821284`. Vérifié avant : la clé s'applique à toute étape reprise par `_PLAIN_CURRICULUM_KEYS`
(`ai/train.py`), la source d'avantage vaut « gae » par défaut.

**Ce que B cherche à savoir.** Le gain de l'exploiteur passe-t-il en lignée ? Quatre différences
avec S9 peuvent le manger : siège 0,7 (S9 gagne surtout en premier : 0,72 / 0,59 cumulés), bots
30 %, P0 échantillonné, gate à 50/50 sur trois sondes. Le plafond de S9 (0,78) laisse 13 points au
gate (0,65) : c'est la marge mesurable.

**Règle de lecture, écrite AVANT le lancement.**
- Juge : les sondes de pool de la lignée (`pool_eval/vs_P0_3ep`, argmax, 300 parties, sièges
  50/50) et la décision automatique `evaluate_pool_decision`. `03_selfplay/P0` n'est PAS un juge
  (échantillonné à T = 2, abaissé de ~2 pts par construction).
- Verrou de parité à l'ouverture (argmax, insensible à T) : hors [0,40, 0,60] le run se refuse
  seul ; rien à lire.
- Garde de destruction automatique : moyenne < 0,50 après 20 000.
- **Promotion automatique à 30 000** si la moyenne de trois sondes ≥ 0,65 → transfert CONFIRMÉ,
  P2 enchaîne sous le même régime. Entre 0,60 et 0,65 à 30 000 → laisser courir ; **arrêt manuel à
  60 000** si toujours sous 0,65 (budget d'étape 200 000 = 33 h, sans cette borne le run tourne pour
  rien) → verdict « le protocole de lignée perd le gain », suite : D (seconde graine de S9) puis
  bissection siège → bots → P0 échantillonné, un run par variable. Sous 0,55 à 30 000 → arrêt,
  même verdict.
- Au gate, deux lectures obligatoires (20 min, lecture seule) sur le P1 promu :
  `scripts/seat_matrix_probe.py` contre le témoin entnorm `20260913-040721`, S9 final
  (`logs/matrix_heldout_20260916/s9_final_ckpt/`) et S25 30 000 (« bat la famille » ou « joue
  mieux » : S9 valait 0,64 / 0,69 / 0,71 sur P1 / S25 / entnorm) ; score par siège avec les profils
  `x1_seat_p1` / `x1_seat_p2` de l'agent expl (tables identiques).
- Mécanisme à consigner à 20 000 et au gate : `train/entropy_loss` (entropie de π_T ; S9 : 1,07 →
  0,80 à 14 000 → 0,72 à 60 000), `train/n_minibatches_done` (S9 : 30 → 16 ; P1 à 0,001 : 11–16),
  `01_VP/a_vp_diff` et `01_VP/c_vp_bot` (S9 gagnait par le déni des points de P0).
- Le run de nuit se décide au gate : B passe → C (P0 neuf à froid, juge indépendant) ; B échoue →
  D (seconde graine de S9).

**Lancement** : `python3 ai/train.py --agent ArmageddonAgent_x1 --training-config x1_lineage
--scenario bot --etape P1`, log `training_x1_06-p01-s9.log`, canonique précédent archivé
automatiquement en `_pre_resume_<horodatage>`. Prologue à vérifier dans le log : « continuité :
… (learning_rate 0.0005 -> 0.0005) » ou absence de la ligne de changement de pas, température
appliquée, échauffement critic 20 (zip P0 sans marqueur), parité d'ouverture dans [0,40, 0,60].

## ÉTAT AU 2026-09-16 08:45 — POUR REPRENDRE SANS CONTEXTE {#etat-2026-09-16}

**Où on en est.** S9 (exploiteur de P0 sous température T = 2 à la collecte, §5.14) est terminé :
plateau contre P0 déplacé de ~0,68 (S25) à ~0,78, plat depuis 40 000 ; la température a été absorbée
(variété de collecte 1,07 → 0,72 nat, S25 à 0,69) et la montée s'est arrêtée quand le surplus a
disparu (coïncidence sur une graine, pas une preuve). Contre les bots : 0,90 (P0 0,91), aucune perte.
Matrice hors entraînement : S9 bat tout ce qui descend de P0 (P1 0,64, S25 0,69) et ne gagne rien
contre le témoin sans parenté entnorm (0,71, comme S25 0,70 et P0 ≈ 0,72) → il apprend à battre la
famille de P0, pas mesurablement à mieux jouer. GPU libre depuis 07:54, rien lancé.

**Réponses aux trois questions de l'utilisateur du 2026-09-16 (00:10).**
1. *Refaire un P0 pour voir s'il plafonne ?* P0 ne plafonne pas contre les bots : score robuste
   0,695 → 0,779 → 0,868 à 30 000 / 40 000 / 50 000 (`training_x1_01-p00.log`), encore en montée au
   bout du budget (7 h 54). Pas la même échelle que 0,70 contre une copie de soi. Un P0 neuf répond
   à une autre question — le pipeline actuel (obs 18 204, récompense marge, moteur du 16) apprend-il
   encore à froid ? aucun run `--new` depuis le témoin entnorm du 13, jamais sous la récompense marge —
   et fournit le juge indépendant qui manque (voir ci-dessous).
2. *Le plafond vient des commits entre le 0,713 et le 0,563 ?* Trois changements simultanés entre le
   8 et le 11 septembre (§9.1) : observation 17 091 → 18 204, P0 réentraîné (75 001 → 50 000 épisodes),
   moteur corrigé (57 armes à zéro dégât, OC par figurine). Bissection : un P0 (8 h) + un P1 (5 h 30)
   par point, une graine, anciens zips inchargeables. **S9 affaiblit l'hypothèse** : sur le code et le
   P0 actuels, un agent atteint 0,78 > 0,713 ; le jeu permet de dépasser 0,70, ce qui manquait était
   l'exploration en reprise. Aucune action code.
3. *Les améliorations vont dans le bon sens, le plafond a une autre cause ?* Oui, avec mesure : rien
   n'indique qu'une amélioration ait nui ; la cause mesurée est l'absence d'exploration d'une politique
   reprise à p ≈ 0,99 (charge 0,01 nat de variété : plus aucune donnée, plus aucun apprentissage sur
   cette tête). Tous les autres suspects ont été testés et écartés (§4) ; seul le levier touchant la
   collecte a bougé le plateau.

**Décisions ouvertes (utilisateur), avec ce que chaque option cherche à savoir.**
- **GPU.** A : exploiteur sous T + poids de la victoire changé (C2 ; aucune valeur écrite, effet
  inconnu ; T s'éteint après ~20 000, on retesterait surtout dans le régime S25). B : T dans le profil
  de lignée + P1 relancé depuis P0 vers le gate 0,65 — c'est le but du chantier. **Risque de
  transfert, vérifié dans `config/agents/ArmageddonAgent_x1/` le 16** : la lignée joue 70 % en second
  (exploiteur 50 %), 30 % contre les bots (0 %), lr 0,001 (0,0005), P0 échantillonné (déterministe) ;
  or S9 gagne surtout en premier (0,72 / 0,59 cumulés). Le 0,78 est un meilleur cas ; ce que la lignée
  en garde n'est pas mesuré. C : P0 neuf à froid (8 h, aucun code, agent dédié à créer par copie
  comme `ArmageddonAgent_x1_expl`) : régression du pipeline + second champion sans parenté. D :
  seconde graine de S9 (5 h 30 jusqu'à 30 000) — la règle §9.3 exige deux graines sous 10 pts d'effet,
  l'effet vaut 10 pts, à la limite ; c'est ce qui rendrait le transfert solide. L'agent a recommandé
  C puis B ; c'est un jugement de valeur d'information, pas une mesure ; B ou D d'abord se défendent
  autant par les faits. Risque métier commun : promouvoir un P1 qui bat la famille de P0 sans mieux
  jouer (lignée qui tourne en rond) — mesurable par la matrice, contenu par un juge indépendant, pas
  éliminé.
- **Mécanisme d'exploration non absorbable** (règle 2b : pas un T plus grand). Deux candidats, à
  comparer PAR ÉCRIT avant tout code. (i) Mélange à la collecte : une fois sur 10–20 un coup légal
  uniforme, ratio corrigé par la distribution de collecte. Hypothèses non vérifiées : le gain de S9
  vient des coups variés et non de l'objectif adouci (PPO optimisait π_T : les deux ne sont pas
  isolés) ; un tirage uniforme sur ~200 cases de déplacement joue des coups absurdes là où T
  explorait les seconds choix (deux leviers ont détruit la politique ce mois-ci) ; correction simple
  avec les têtes à pointeur masquées. (ii) Température autorégulée : T ajusté à chaque update pour
  tenir la variété de collecte à une cible (ex. 1,0 nat) ; garde les seconds choix, compense
  l'affûtage du réseau ; risque : T sans borne, objectif de plus en plus adouci. Aucun des deux n'est
  testé ni codé ; les règles 40k n'interviennent pas dans ce choix.

**Ce qui est sain (mesuré).** Zéro action invalide, zéro troncature, contrats vérifiés, gardes
d'arrêt opérantes, règle-avant-lecture tenue, critic à 0,88, holdout bots stable.

**Ce qui ne l'est pas (mesuré, avec renvoi).** Exploration absente en reprise (§5.14, sonde par
famille) ; une graine contre une graine sur tous les verdicts (§9.3 ; S9 ≈ 4 σ, les réfutations à
5 pts ne valent rien) ; plus de juge de progrès général (bots saturés D2, lignée auto-référente ; la
matrice du 16 est le premier instrument) ; moitié de chaque rollout jetée par la coupure KL
(15–16 / 32, §5.4, tous les runs) ; récompense à ~70 % de substitut (objectifs 64 %, pénalités −112
non ventilées, C5 ouvert) ; gate de lignée jamais passé depuis le 10 septembre (six relances).

**Estimation honnête.** Cause cernée, un levier à +10 pts ; pas de lignée qui progresse. Chemin :
mécanisme non absorbable conçu, codé, testé (1–2 j) → deux graines (1 j) → transfert lignée (1 j)
→ juge indépendant (8 h). Si tout marche : 4–5 jours pour savoir si la lignée passe 0,65 de façon
reproductible. 0,78 est le meilleur cas mesuré ; 0,90 : aucune mesure ne dit s'il est atteignable.

**Artefacts.** Logs : `training_x1_expl_05-e00-s9.log` ; TensorBoard `run_20260915-203437` ;
poids finaux `ppo_checkpoint_20260915-203439_12247944_steps.zip` (copie dans
`logs/matrix_heldout_20260916/s9_final_ckpt/`) ; canonique expl = instantané holdout 0,9072 (50 000) ;
`curriculum.log` ligne 17 ; matrice et sondes par famille : `logs/matrix_heldout_20260916/*.json`,
`family_entropy_s9_vs_s25_30000.txt`, `family_entropy_s9final_vs_s25_40000.txt` ; instruments :
`scripts/seat_matrix_probe.py`, `scripts/family_entropy_probe.py`. Config inchangée : le profil
`x1_lineage` de l'agent expl porte toujours `logits_temperature: 2.0` et `advantage_source: gae`.
Commits du 16 : `975ebc91c` → `8ba5473dc` (lectures 18 000 → clôture, une par lecture).

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
- [x] Température d'exploration (S9) — jouée les 2026-09-15/16 : **OUI** (fenêtres 0,730 / 0,760 / 0,783 / 0,767 contre 0,677 ; plateau déplacé à ~0,78, plat depuis 40 000 ; §5.14).
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
| 11 | P1 | **x1_lineage, from:P0** | 30 008 | **0,713** | run du 09-08 12:03 → 15:49 (autre session : `tb_run.json`, zip `OLD/ArmageddonAgent_x1_P1.zip`) |
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
faisait 0,71, et n'a jamais été confronté au jeu actuel.** Réserve : le P0 de la ligne 11 n'est
pas le P0 actuel (75 001 épisodes contre 50 000, autre observation), donc « même adversaire »
n'est pas acquis et le 0,713 n'est **pas** une référence comparable. **Conclusion sur les
commits du 09-10 : aucune action code ; la seule référence valide est ce qu'un exploiteur
atteint maintenant (S25).** Ce que ces commits ont changé pour le joueur (qui tient un
objectif, adversité des bots) ne se lit pas dans le code, il se lit dans les parties : S27.


**Complément d'une troisième session (2026-09-14 soir, vérifié par elle dans les zips et `git log -p`) :**
le run à 0,713 tournait déjà avec **exactement le profil actuel** (lr 0,001 constant, ent_coef
0,01, n_steps 8 160, batch 1 020, n_epochs 4, vf_coef 0,17, λ 0,95, target_kl 0,015, pool P0 à
0,7, bots 0,3, mêmes récompenses hors B6). Ce qui diffère du run à 0,563 : l'**observation**
(grille 9 → 12 canaux : obscuring, los_exposure, occupant_level ; +20 scalaires OC live/secured,
mots-clés, split-fire, Ld, siège — commits du 09-08 17:18 au 09-09 19:07, d'où le P0 neuf),
l'**adversaire** (P0 de 75 001 épisodes sur l'ancienne observation contre 50 000 sur la nouvelle)
et le **moteur** (les quatre commits du 09-10, move réactif bloqué au contact, verticalité).
Conséquences : (1) A3 (lr de reprise) perd l'essentiel de son poids — le même lr a extrait 0,71 en
30 000 épisodes sur l'ancien jeu ; hygiène, pas cause. (2) Le suspect qui touche directement
l'extraction de signal est l'observation : plus grande à réseau et lr égaux, et les bits de tir
fractionné y pèsent 85 à 640 fois moins que leur étalon (ROADMAP_INDEX, mesure du 09-11) —
régression par l'observation en tête de l'étape 3 si S25 plafonne. (3) Réserve honnête : une part
du 0,713 a pu être l'exploit d'un défaut du moteur corrigé depuis (OC non sommée par figurine,
57 armes à dégât nul) — le 0,713 ne prouve pas que 0,90 soit atteignable sur le jeu actuel ; c'est
S25 qui le mesure. Le zip 0,713 ne se charge plus (obs_size 17 091 → 18 204).

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
   siège 0,5, 100 % P0, 60 000 épisodes, sondes exploiteur de 100 parties tous les 2 000 épisodes
   (log seulement, cf. §9.6 A3). Règle : moyenne des 3 dernières sondes ; **≥ 0,68** → le défaut de P1 est dans l'écart de config, bissection en un run par
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

### 9.6 Exécution autonome (2026-09-14 soir →) — arbitrages pris, contre-relus par un sous-agent {#arbitrages-2026-09-14}

Décision utilisateur : dérouler S27 → S25 → leviers sans attendre ; chaque arbitrage est analysé,
contre-relu par un sous-agent indépendant (lecture seule du dépôt, preuves fichier:ligne), la
solution de consensus appliquée et notée ici.

**Livré (merge `9bd6de90b`)** : agent dédié `ArmageddonAgent_x1_expl` (`config/agents/ArmageddonAgent_x1_expl/`,
copie de la config x1 ; curriculum `order [P0, E0]`, E0 exploiteur `from:P0` ciblant P0 à 100 %,
`opponent.deterministic true`, `win_rate_target 0,95`, `budget_cap 60000` ; `x1_lineage` à lr 0,0005
et siège 0,5 ; profils de mesure `x1_seat_p1` / `x1_seat_p2`) ; copies identiques (`cmp`) de P0 zip /
pkl / run_state / contrat sous `ai/models/ArmageddonAgent_x1_expl/` ; contrat courant de l'agent =
contrat P0 (0 écart, même empreinte de table `7470725e7d0095b8`) ; `scripts/seat_matrix_probe.py`
(+ 5 tests) : `evaluate_against_checkpoints` tel quel, plateau déduit du suffixe `_x<N>`.

| # | arbitrage | analyse | contre-relecture | appliqué |
|---|---|---|---|---|
| A1 | S25 tourne sous la table **B6** (marge de VP), pas sous la récompense de référence de P1 | l'ancienne récompense d'objectif a été supprimée du code le 09-14 (0 hit `objective_reward_factor` hors doc) ; le run de référence n'est plus rejouable sur main ; `value_warmup_updates 20` reste actif (zip P0 sans marqueur → régime joué) | CONFIRMÉ (`engine/reward_calculator.py:921-952`, `ai/train.py:3928-3935`, `:363-368`) | S25 = meilleur cas **sous B6** ; la bissection contre la config P1 se fera sous B6 (le « run marge » P1 devient le bras de comparaison) |
| A2 | cellules « P0 échantillonné vs P0 argmax » et « P0 argmax vs P0 argmax » de S27 | le script impose `deterministic=True` (`ai/bot_evaluation.py:2568`) ; la première se lit sur `03_selfplay/P0` de S25 **pendant le warmup** (politique figée au bit près, ~500–1 440 épisodes d'étape) ; la seconde devait venir de la parité d'ouverture | CONTESTÉ sur la seconde : **un exploiteur n'a pas de sonde de parité** (`ai/train.py:6946` monte `ExploiterProbeCallback` seul, `:6996` réserve `PoolEarlyStoppingCallback` aux non-exploiteurs) — donc aucun garde-fou d'appariement zip/pkl sur S25 | P0 vs P0 mesuré par le script sur les deux sièges forcés AVANT S25, lu comme verrou de parité [0,40, 0,60] |
| A3 | lecture de S25 : sondes exploiteur 100 parties / 2 000 épisodes (pas 10 000 comme écrit en §9.5), confirmation 500 à ≥ 0,95, pas de bloc early_stop, budget en épisodes d'étape | | CONFIRMÉ (`ai/training_callbacks.py:3050-3088`, `:2760`, `ai/curriculum.py:1088`) ; **les sondes exploiteur ne sont PAS publiées dans TensorBoard**, seulement dans le log (`🔬 Sonde exploiteur`) et `curriculum.log` à la clôture | verdict sur la moyenne glissante de 3 sondes calculée depuis le log (300 parties, ±2,9 pts) + `03_selfplay/P0`, `win_rate_overall`, `seat_aware/*` (100 % des épisodes contre P0) |
| A4 | lr 0,0005, un seul bras | bras 0,001 seulement si S25 ≥ 0,68 | CONFIRMÉ (`ai/train.py:296-304`, `ai/patched_ppo.py:260`, rampe non montée sur scalaire `:4602`) | |
| A5 | `opponent.deterministic` global atteint l'exploiteur | | CONFIRMÉ (`ai/train.py:5266` → `ai/training_utils.py:154-329` → `ai/env_wrappers.py:445`, `:1199`) | |
| R1 | **bug attrapé** : `seat_matrix_probe.py` ne posait pas `W40K_BOARD_PATH` → plateau x5 en silence (grille à taille fixe, aucun refus) | | signalé par la contre-relecture (`config/config.json:8`, `engine/spatial_grid.py:547-563`) | corrigé avant toute mesure : `board_path_for_agent`, test ; la sonde de fumée à 8 parties faite avant ce correctif est **jetée** |
| R2 | le canonique de fin de S25 (`model_ArmageddonAgent_x1_expl.zip`) sera le meilleur instantané **holdout bots** (`save_best_robust`), pas les poids finaux de l'exploiteur ; `_close_exploiter_stage` ne promeut aucun `_E0.zip` | | signalé (`ai/train.py:1538-1559`) | toute mesure a posteriori sur l'exploiteur vise le dernier `ppo_checkpoint` (rotation 3) ; noté, pas modifié |
| R3 | S27 : seuls les profils forcés mesurent un siège, ils n'existent que dans l'agent expl | | signalé (`ai/bot_evaluation.py:2650-2660`) | toutes les cellules S27 passent `--agent ArmageddonAgent_x1_expl` (tables identiques), y compris P1 `robust_0.9078` |

### 9.7 S27 — mesures statiques par siège (2026-09-14, 21:47 → 21:56) {#s27-2026-09-14}

`scripts/seat_matrix_probe.py`, agent `ArmageddonAgent_x1_expl` (tables identiques à x1), profils
`x1_seat_p1` / `x1_seat_p2`, 300 parties par cellule, argmax des deux côtés, holdout, graine tirée
au hasard, 12 workers à 1 thread (139 à 145 s par cellule ; la première tentative sans limite de
threads n'avait pas fini une cellule en 63 min, cf. §9.6). JSON dans le scratchpad de session.

| modèle évalué | siège 1 | siège 2 | moyenne (siège 0,5) |
|---|---|---|---|
| **P0 (`model_..._expl_P0.zip`, copie identique) vs P0** | **0,610** (183/300) | **0,403** (121/300) | **0,507** |
| **P1 (`robust_0.9078`) vs P0** | **0,690** (207/300, 1 nul) | **0,593** (178/300) | **0,642** |

Lecture.
- **Verrou de parité tenu** : 0,507 dans [0,40, 0,60] — les copies zip / pkl de P0 sont appariées,
  S25 peut partir (la sonde de parité n'existe pas pour un exploiteur, §9.6 A2).
- **L'avantage du premier joueur vaut 21 points dans le miroir** (0,61 contre 0,40, argmax contre
  argmax, dés seuls). C'est la part structurelle du jeu dans tout score contre P0 : un exploiteur
  à siège 0,5 doit gagner les deux sièges pour dépasser 0,65, et le siège 2 seul plafonne
  mécaniquement plus bas.
- **P1 gagne +8 points sur P0 en siège 1 et +19 en siège 2** : la lignée a surtout appris à jouer
  second (70 % des épisodes de P1 en siège 2), et sa moyenne à sièges égaux (0,642) est exactement
  ce que les sondes du run de référence rendaient (0,59–0,66) — la sonde de curriculum joue bien
  50/50, elle ne biaise pas vers le siège faible.
- Ce que ça ne dit pas : si 0,90 est atteignable. C'est S25.

### 9.8 S25 — run lancé le 2026-09-14 à 21:57 {#s25-run}

`run_20260914-215728` (`tensorboard/x1_lineage_ArmageddonAgent_x1_expl/`), log
`training_x1_expl_01-e00-s25.log`, commande `python3 ai/train.py --agent ArmageddonAgent_x1_expl
--training-config x1_lineage --scenario bot --etape E0`. Prologue vérifié dans le log : reprise à
50 000 épisodes, 24 envs, `n_steps` 340 × 24, lr **0,0005** appliqué, ent 0,01, siège 0,50, pool
P0 1,00 (part de bots 0), VecNormalize chargée, **échauffement critic 20 updates** (table
`7470725e7d0095b8`, jamais échauffée). Fin attendue vers 04:00 (60 000 épisodes d'étape). Lecture
par la règle §9.5 sur les sondes exploiteur du log (100 parties / 2 000 épisodes) et `03_selfplay/P0`.

**Lecture à 20 000 épisodes d'étape (2026-09-15, 01:35).** Sondes exploiteur (100 parties, argmax
contre argmax, holdout, sièges 50/50) à 2 000 / 4 000 / … / 20 000 : 0,43 · 0,55 · 0,58 · 0,49 ·
0,63 · 0,66 · 0,67 · **0,73** · 0,66 · **0,68** — moyenne des trois dernières **0,69**. Référence P1
(`run_20260912-065925`) au même point : sonde 0,533, moyenne 0,540. `03_selfplay/P0` (agent
échantillonné, 10 % d'épisodes déployés par le moteur, fenêtre 500) par tranche de 2 000 : 0,477 →
0,498 → 0,526 → 0,573 → 0,580 → 0,593 → 0,598 → 0,605 → 0,641, sans plateau (référence sur
[10 000, 20 000) : 0,571). Déploiement actif 0,665 contre **0,41 en déploiement moteur, en baisse** :
l'avantage construit passe par le déploiement de l'agent. **Holdout bots à 10 000 : combined 0,887,
pire bot 0,83, siège 1 0,947 / siège 2 0,839** — 0 % de bots à l'entraînement et la généralité
tient (P0 : 0,863–0,910 ; P1 : 0,907). Santé : EV 0,87, KL 0,010, coupure après 15–25 mini-lots
sur 32 (11–16 sur P1), `train/entropy_loss` −0,82 → −0,65, soit une entropie qui **baisse** de 0,82 à 0,65 nat (politique qui se resserre — l'inverse de S11 où elle s'aplatissait, −0,78 → −0,85 ; erreur de signe corrigée le 2026-09-15 à 02:30),
lr 0,0005 (les trois premières updates du warmup affichent 0,001 dans `train/learning_rate`,
politique figée alors — à vérifier, sans effet mesurable). Le run continue jusqu'à 60 000 ; la
branche « ≥ 0,68 → bissection » est déjà la plus probable.

**Règle complétée par l'utilisateur à 28 000 (2026-09-15, 03:10), écrite avant lecture.** Sondes
16 000 → 28 000 : 0,73 / 0,66 / 0,68 / 0,71 / 0,73 / 0,64 / 0,69, moyenne glissante entre 0,68 et
0,71 — plateau naissant vers 0,69, non prouvé à n = 100. Objectif : **≥ 0,70 sur la moyenne
glissante de trois sondes** (300 parties, erreur-type 2,6 pts, même instrument que le gate),
pour établir que la méthode extrait au-delà de tout ce que la lignée a rendu, et non qu'elle
repousse le plateau de quelques points. **Stagnation** = à 40 000, moyenne des sondes de
30 000–40 000 supérieure de moins de 3 points à celle de 20 000–30 000 → verdict « le mécanisme
plafonne même dans le meilleur cas », leviers de mécanisme (étape 3) dans ce dispositif. Le juge
est la sonde argmax, pas `03_selfplay/P0` (échantillonné, 10 % d'épisodes déployés par le moteur
à 0,41). Holdout bots lu en parallèle contre la suradaptation.

**Lecture à 30 000 (2026-09-15, 03:50).** Sondes 20 000 → 30 000 : 0,68 / 0,71 / 0,73 / 0,64 /
0,69 / **0,61**, moyenne de fenêtre **0,677**, moyenne des trois dernières 0,647. `03_selfplay/P0`
par 4 000 : 0,489 → 0,549 → 0,586 → 0,602 → 0,634 → 0,645 → 0,649 → **0,633** — plat à 0,63–0,65
depuis 18 000. Sièges (échantillonné) 0,60 / 0,59 ; déploiement actif 0,66 / moteur 0,44 ;
`a_vp_diff` 4,8 → 4,1. **Holdout bots à 20 000 d'étape : combined 0,933, pire bot 0,85, siège 1
0,989 / siège 2 0,89** — au-dessus de P0 (0,863–0,910) et de P1 (0,907) : zéro suradaptation à P0,
la généralité MONTE avec 0 % de bots à l'entraînement. Santé : entropie plate à −0,68 depuis
15 000, EV 0,88, KL 0,009, **coupure après 15–16 mini-lots sur 32** — la même signature que le
plateau de P1 (761/761 coupées, ~15 pas). Lecture : le meilleur cas a gagné ~9 points sur P1 au
même instrument, puis s'est posé au même régime d'update ; verdict de stagnation à 40 000 selon la
règle ci-dessus.

**Bissection préparée (config seule, agent dédié), à lancer après S25 — un GPU, donc en série.**
S25 diffère du régime P1 par quatre variables : lr 0,0005 / 0,001 ; P0 déterministe / stochastique ;
siège 0,5 / 0,7 ; 100 % P0 / 70 % P0 + 30 % bots. La récompense B6 est commune à tout ce qui
suit (§9.6 A1). Ordre : (1) **P1 sous B6** = le « run marge » de l'autre session (référence
comparable, à lancer par elle ou ici) ; (2) **H1** = S25 + {P0 stochastique, 30 % bots}
(adversité de P1, régime de S25) ; (3) **H2** = S25 + {lr 0,001, siège 0,7} (régime de P1,
adversité de S25) ; puis une variable dans la paire désignée. Jugement à 30 000 sur la moyenne
des trois dernières sondes, comparée à S25 au même point ; écart < 10 points → deuxième graine.


**Lecture à 40 000 (2026-09-15, 13:32) — verdict.** Sondes 32 000 → 40 000 : 0,63 / 0,75 / (reprise
34 104 : 0,68) / 0,62 / 0,77 / 0,72. Fenêtre 30 000–40 000 (0,61 / 0,63 / 0,75 / 0,62 / 0,77 /
0,72) : **0,683** contre 0,677 → +0,6 pt, sous le seuil de +3 : **stagnation**. Fait à ne pas
cacher : les deux dernières sondes sont les plus hautes du run et la moyenne glissante de trois
(0,62 / 0,77 / 0,72) touche **0,703**, l'objectif « ≥ 0,70 » du 03:10 — mais de 0,3 pt avec une
erreur-type de 2,6 pts, et la moyenne de fenêtre (600 parties) ne bouge pas : c'est le bruit de
l'instrument, pas une montée. Run arrêté à 40 084 (SIGINT, 13:33) ; dernier checkpoint
`ppo_checkpoint_20260915-123207_10087944_steps.zip` (90 084 cumulés), reprenable par
`--resume-from` si l'on veut un jour lire 60 000. Suite : §9.9.

### 9.9 Journée du 2026-09-15 — verdict S25, reboot, S14 lancé, ORDRE DE LA SUITE FIGÉ {#suite-2026-09-15}

**Verdict S25 (règle du 2026-09-15 03:10, §9.8) : STAGNATION.** Sondes exploiteur 30 000 → 40 000 :
0,61 / 0,63 / 0,75 / 0,62 / 0,77 / 0,72 → moyenne de fenêtre **0,683** contre 0,677 pour
20 000–30 000 (+0,6 pt, seuil +3). Le meilleur cas (100 % P0 déterministe, siège 0,5, lr
0,0005, B6) a gagné ~9 points sur P1 au même instrument puis s'est posé à 0,64–0,69 avec la
signature d'update de P1 (coupure KL 15–16 sur 32, entropie plate −0,68) : **le mécanisme
d'apprentissage plafonne même dans le meilleur cas** ; le gate (§9.4) n'est pas le sujet, la
bissection de config (§9.8) est SANS OBJET tant que le mécanisme n'a pas bougé. Run arrêté à
40 084 d'étape (pas de 60 000 : la branche stagnation ne l'exige pas). Lecture : sondes du log
`training_x1_expl_01-e00-s25.log` (2 000 → 34 000) et `training_x1_expl_02-e00-s25-reprise.log`
(34 104 → 40 084).

**Incident.** Reboot Windows le 2026-09-15 à 04:29:28 (arrêt propre de l'instance WSL par l'hôte,
`journalctl -b -1` ; ni OOM ni traceback) : S25 tué à 35 320 d'étape, repris à 12:32 depuis
`ppo_checkpoint_20260914-215730_9367944_steps.zip` (84 104 cumulés = 34 104 d'étape) par
`--resume-from` + `--etape E0` (`run_20260915-123205`, échauffement sauté par le marqueur, compteur
d'étape ancré sur l'archive P0 : `ai/train.py::stage_origin`). Perte : ~1 200 épisodes. Le
canonique 0,9094 (holdout bots) écarté en `_pre_resume_20260915-123142` ; copie
`ArmageddonAgent_x1_expl_12345_robust_0.9094.zip`. La même nuit, la session S14 (worktree
`worktree-tete-q-avantage-espere`) mourait en pleine correction de review — reprise et finie à
midi (§5.13).

**Décisions du jour (utilisateur).**
1. Reprendre S25 depuis le checkpoint plutôt que juger sur 3 sondes (12:30).
2. Ordre des leviers : « S9 puis S14 » (13:00), pris sur une prémisse fausse de l'agent (S9
   décrit comme config seule ; c'est du code, §4 ligne S9) et sans savoir que S14 était codé
   à 90 % depuis la nuit → **re-tranché à 13:15 : option A, S14 d'abord** (décision de la nuit
   confirmée), S9 seulement si S14 est réfuté.
3. Le dossier fixe l'ORDRE DE LA SUITE ci-dessous pour ne plus retrancher.

**ORDRE DE LA SUITE — figé le 2026-09-15, à ne rouvrir que sur un fait nouveau mesuré.**

| étape | levier | dispositif | règle de lecture | si oui | si non |
|---|---|---|---|---|---|
| 1 | ~~S14 tête Q centrée sous π~~ — **RÉFUTÉ le 2026-09-15 (§5.13.1)** : garde déclenchée (0,362 à 10 000), `q_loss_mb0 − value_loss_mb0` ≥ 0 partout, entropie 0,71 → 0,28 : la tête n'a pas de données contrefactuelles (politique à p_max 0,66–0,99). Variante S14c écartée sans run (aucune ne crée ces données). | — | — | — | → étape 2 sous **GAE** |
| 2 | **S9 exploration structurée** — **OUI, TERMINÉ À 60 000 le 2026-09-16** (`run_20260915-203437` : fenêtres 0,730 / 0,760 / 0,783 / 0,767 contre 0,677 pour S25 ; plateau déplacé de ~0,68 à ~0,78, plat depuis 40 000, T absorbé à 60 000 ; holdout bots 0,922 ; §5.14) ; **mesure 2a NÉGATIVE** (+0,0025 ± 0,001 : S14 mort, ni seul ni sur S9) (§5.14 : règle complète, absorption, juge = sonde argmax, pas `03_selfplay`) : température T = 2 des logits à la collecte ET dans le ratio (`_distribution_from`, attribut de régime hors zip, transporté aux workers), T = 1 en évaluation (les sondes sont argmax : invariantes à T, l'effet ne passe que par l'apprentissage) | S25 sous **GAE** (`advantage_source: gae`), depuis P0, E0 | **2a — mesure préalable (~30 min, §5.13.1)** : checkpoint S25 40 000 + `q_head` + T = 2 + échauffement 40, politique figée, lire `q_loss_mb0 − value_loss_mb0` sur les 20 dernières updates : < −0,002 → S14-SUR-S9 rejouable plus tard ; sinon S14 mort. **2b — run S9** : garde 10 000 (≤ 0,45), verdict 30 000 sur la moyenne 20 000–30 000 contre 0,677 ; ≥ 0,72 oui ; 0,64–0,72 réfuté ; ≤ 0,63 régression ; lecture mécanisme : `train/entropy_loss` (entropie de π_T, attendue plus haute), `family_entropy_probe` sur le checkpoint 30 000, coupure KL | garder T ; si 2a positif, S14 SUR S9 (un run, règle §5.13.1) ; sinon étape 3 | réfuté ; étape 3 |
| 3 | **C2 issue vs façonnage** : poids de l'issue ±150 contre les 62 % d'objectifs (config seule) puis **B6 seconde graine** | S25 | idem, un run par variable, deux graines si effet < 10 pts | garder | — |
| 4 | **Transfert** du régime gagnant dans `x1_lineage` de `ArmageddonAgent_x1` : relire lr / `target_kl` / `ent_coef` / `vf_coef` sur `n_minibatches_done` et `grad_share_policy` SOUS le nouvel estimateur (réglages mesurés sous GAE, §5.4, non transférables), puis reprise de la lignée P1 → gate 0,65 | lignée | règle §7 | lignée relancée | — |
| 5 | **S11b** (espérance sur les dégâts seuls, kills au jet) seulement si les sondes de §5.11 désignent le proxy des kills ; **S15** recherche en dernier recours | — | — | — | — |

Ce qui est CLOS et ne se rouvre pas : gate 0,65 (§9.4), λ court / lot ×4 (S23, §5.9), `vf_coef`
(§5.10), S11 tel que codé (§5.11), entnorm (§5.5), « plateau normal » (§9.4), bissection de
config avant le mécanisme (§9.8, suspendue : elle ne se justifie que si le mécanisme retenu
remonte le meilleur cas).

## 10. Comparaison écrite — quelle exploration l'optimiseur ne peut pas défaire ? (2026-09-16, rédigée pendant B, AVANT tout code) {#exploration-2026-09-16}

**Pourquoi ce document.** S9 (§5.14) a montré que l'exploration à la collecte déplace le plateau
(+10 pts), et que la température s'éteint : le réseau affûte ses préférences jusqu'à annuler la
variété ajoutée (variété de collecte 1,07 → 0,72 nat en 40 000 parties ; à T = 1 la politique de
S9 est plus pointue que S25), et la montée s'arrête quand le surplus disparaît. La règle 2b
disait : le levier suivant n'est pas un T plus grand mais un mécanisme non absorbable. Quatre
options, dont « rien de plus » ; aucune n'est codée ni testée ; les règles du jeu (40k_rules)
n'interviennent pas. Ce que S9 n'a PAS isolé et qui pèse sur le choix : la température changeait
AUSSI l'objectif appris (PPO optimisait π_T, une version adoucie de la politique) ; la part du gain
qui vient des coups variés et celle qui vient de l'adoucissement ne sont pas séparées.

**Option 0 — rien de plus : la température rejouée à chaque étape.** T est un régime de run, pas
un poids sauvegardé : chaque étape reprise repart avec une fenêtre d'exploration neuve d'environ
40 000 parties, et le plafond sous T (0,78) dépasse le gate (0,65). *Gain* : zéro code, zéro
risque nouveau, c'est ce que B mesure. *Coût* : plafonne là où T s'éteint ; ne vise pas 0,90.
*Critère de choix* : si B et P2 passent leur gate, cette option suffit pour la lignée ; les trois
autres ne se justifient que pour dépasser ~0,78 ou si le gain se perd en lignée.

**Option 1 — mélange aléatoire à la collecte, ratio corrigé.** Les workers jouent
μ = (1 − ε)·π + ε·uniforme(légales), ε ≈ 0,05–0,10 ; le ratio PPO et l'avantage sont corrigés par
π_old(a)/μ(a) (borné par 1/(1 − ε)). Site : `_distribution_from` (`ai/pointer_policy.py`) côté
collecte, ratio dans `train` (`ai/patched_ppo.py`). *Ce qu'il change* : les coups joués, pas
l'objectif. *Absorbable* : non (indépendant des logits). *Risque de destruction* : RÉEL — un
tirage uniforme sur ~200 cases de déplacement joue des coups absurdes là où T explorait les
seconds choix ; deux leviers ont détruit la politique ce mois-ci (S11, S14c) ; à mesurer par la
garde à 20 000 et le holdout bots. *Hypothèses non vérifiées* : le gain de S9 vient des coups
variés (non isolé, voir ci-dessus) ; la correction est simple avec les têtes à pointeur masquées
(le buffer garde `old_log_prob` de π, il faudrait aussi log μ). *Code* : moyen (workers, buffer,
ratio) + tests rouge/vert sur la correction.

**Option 2 — température autorégulée sur la variété de collecte.** T ajusté à chaque update
pour tenir `train/entropy_loss` (entropie de π_T) à une cible, par exemple 1,0 nat (S9 à 2 000) :
si le réseau affûte, T monte ; si la politique est déjà variée, T redescend vers 1. Site :
propriété `logits_temperature` déjà existante (`ai/patched_ppo.py`), une boucle de réglage par
update, transport aux workers déjà en place. *Ce qu'il change* : la distribution de collecte ET
l'objectif (comme S9), de façon contrôlée. *Absorbable* : non (compensé). *Gain* : garde les
seconds choix plausibles, réutilise le mécanisme qui a marché, code léger. *Risque* : T sans
borne si le réseau affûte sans fin (borner T ≤ 4 et journaliser) ; un objectif de plus en plus
adouci, dont l'effet sur l'argmax évalué n'est pas mesuré au-delà de T = 2. *Hypothèse non
vérifiée* : que maintenir la variété prolonge la montée au-delà de 40 000 (corrélation d'une
graine). *Code* : faible.

**Option 3 — remise à neuf partielle des couches de décision (warm-start de la littérature :
« shrink and perturb », Ash et Adams 2020 ; réinitialisations, Nikishin et coll. 2022).** À la
reprise, garder le tronc de perception et le critique, rétrécir (× 0,5) et bruiter — ou remettre
à neuf — les têtes de politique (`PointerHeadNets`, `ai/pointer_policy.py`), rejouer la rampe
d'exploration du départ à froid (bonus de variété 0,1 → 0,01) et GELER le tronc pendant la phase
de reconstruction (le gel de l'extracteur existe déjà pour l'échauffement du critique,
`ai/patched_ppo.py` ~476–486). *Ce qu'il change* : le point de départ, pas le mécanisme
d'apprentissage ; c'est un départ à froid de la décision sur une perception acquise. *Absorbable* :
sans objet (la dynamique du départ à froid est celle qui a marché pour P0). *Gain* : répond à la
cause telle qu'elle est mesurée (reprise trop sûre d'elle) au prix de quelques milliers de parties
au lieu de 100 000. *Risque* : la dynamique du 4 septembre (P2 détruit quand la rampe a été
rejouée SANS gel du tronc : 0,118 contre P1, bots 0,91 → 0,69) ; le critique doit réapprendre
sous une politique redevenue aléatoire (échauffement à rejouer). *Hypothèses non vérifiées* : que
le tronc porte l'essentiel du savoir ; que la reconstruction des têtes ne redécouvre pas la même
politique. *Code* : moyen (chirurgie des poids à la reprise + gel + rampe), tests sur l'identité du
tronc et la remise à neuf des têtes.

**Ce qui départagerait sans coder (mesures, 1 h de CPU).** (i) Sur les checkpoints S9 à 30 000 et
60 000 : rejouer 300 parties argmax contre P0 avec les logits divisés par 2 et par 4 À
L'ÉVALUATION (argmax invariant → contrôle nul attendu) puis en échantillonnant à T = 1 et T = 2 :
dit si la politique apprise sous T « veut » encore explorer ou si tout est dans la collecte.
(ii) `family_entropy_probe` sur les checkpoints S9 à 10 000 / 20 000 / 40 000 : la trajectoire de
l'absorption tête par tête (laquelle s'affûte en premier) fixe la cible de l'option 2 et les
têtes candidates de l'option 3. (iii) Le résultat de B (§5.15) tranche l'option 0.

**Recommandation provisoire, à confirmer par B et par (i)–(ii).** Option 0 si B et P2 passent.
Sinon **option 2** d'abord (code faible, mécanisme éprouvé, risque borné), et option 3 si la
lignée reste sous l'objectif après deux graines : c'est la seule qui traite la cause à sa racine,
mais elle rejoue la dynamique qui a détruit P2 le 4 septembre et exige le gel du tronc. Option 1 en
dernier : c'est celle dont le risque de destruction est le moins maîtrisé.

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
