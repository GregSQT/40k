# Curriculum — adversaires et étalons d'évaluation (R0→R3)

> **Décision utilisateur du 2026-08-21 — PRIORITÉ HAUTE.** Le curriculum démarre maintenant :
> R0a et R0b se livrent AVANT le prochain run long et passent devant les lignes J2 du chemin
> critique. Séquencement des runs : un levier par run (règle du chantier panel, maintenue).

---

## 1. Constat fondateur — mesuré, jamais supposé

Sources : courbes TensorBoard `run_20260821-031413` (x1_long 50k, 2026-08-21), `bot_ranking`
1 728 épisodes seed 5 (2026-08-21), matrice bot-contre-bot du 2026-08-20 (étape 8).

- **Panel doctrine** : discrimine encore mais approche la saturation — combined
  0,483@10k → 0,706 → 0,744 → 0,878 → 0,917@50k ; par bot 0,83-0,94 en éval finale.
- **reference_*** : saturés depuis la PREMIÈRE éval — balanced 1,00 / denial 0,967 /
  reactive 0,933 à 10k épisodes (l'agent perdait encore contre le panel : combined 0,483),
  1,00 partout ensuite. **Ils n'ont jamais rien mesuré côté agent.**
- **tactical** (témoin scellé §0.55) : resaturé — 0,633@10k → 1,00 dès 30k. Déjà dé-saturé une
  fois le 2026-08-04 (0,89 → 0,72 via `w_objective` 0,5 → 2,0), re-mangé en deux semaines.
- **Gate `benchmark_floor` 0,90** : inerte (references à 1,00, le gate ne peut pas mordre).
- **Signal encore vivant** : siège p2 (0,67-0,92@50k contre p1 saturé à ~1,00),
  attrition/scorer/racer (0,83-0,86).
- **Bot-contre-bot** : reference_balanced 0,172 / denial 0,151 / reactive 0,120 (2026-08-21,
  6 ép./appariement) — cohérent avec 0,168/0,155/0,139 (2026-08-20, 20 ép.). Panel doctrine
  mutuel ~0,5 : le panel est sain, c'est l'agent qui l'a dépassé.

**Verdict.** Aucun bot scripté fixe ne peut servir d'étalon de FORCE sur la durée — deux
précédents mesurés dans ce dépôt : la refonte « tactical joue pour gagner » (9,5× le coût,
0,431 contre des bots ordinaires, supprimée le 2026-08-12) et la désaturation de tactical
(2026-08-04) re-mangée en deux semaines. Les rôles se séparent donc :

| rôle | instrument | saturation |
|---|---|---|
| couverture par style + régression | 6 bots doctrine (inchangés) | acceptée — l'info est dans la CHUTE |
| généralisation (mécanisme jamais vu) + gate | reference_* RÉPARÉS (R0a) | acceptée une fois le gate re-posé |
| force relative sur la durée | échelle de checkpoints `robust_*` (R0b) | jamais — se renforce avec l'agent |
| témoin anti-optimisation | tactical GELÉ (§0.55) | assumée — c'est un témoin, pas une mesure |

## 2. Décisions actées le 2026-08-21

1. **Priorité haute** : R0a + R0b avant le prochain run long.
2. **tactical n'est PAS renforcé** — gels §0.55 (profil témoin) et D10 (`evaluation_bots.py`,
   pas une ligne) maintenus. La piste « faire de tactical LE holdout à la place des
   reference_* » (proposée par un autre agent) est **écartée** : prémisses fausses — les
   reference_* ne sont pas des variantes de poids doctrine (élection d'intention
   `_elect_intent`, mémoire de plan inter-tours `_update_plan`) et tactical décide tout sur le
   proxy de dégâts faux (`get_max_melee_damage > get_max_ranged_damage` en charge,
   `squad_expected_damage` : 0 occurrence dans `evaluation_bots.py`) — plus la saturation
   ci-dessus. Elle ne se ré-instruit que par la mesure C.4 (prompt lancé le 2026-08-21) ;
   sa conclusion se consigne ici.
3. **Un levier par run** : R1 = rien ne bouge, R2 = self-play seul, R3 = récompense seule.
4. **Périmètre bots** : les 6 doctrine (`bot_doctrines.py`) et les gelés d'`evaluation_bots.py`
   ne bougent pas dans ce chantier.

---

## 3. R0a — Réparer la couche déplacement/intention des reference_*

Fichier unique : `ai/benchmark_bots.py` (+ ses tests). Paramètres **hardcodés** — §4.C.3 :
jamais `bot_movement_weights.json` ; les PRIMITIVES moteur sont autorisées (les doctrine s'en
servent déjà, c'est le fichier de réglage partagé qui est interdit, pas le moteur).

### 3.1 Élection d'intention au niveau ARMÉE (le cœur)

Aujourd'hui chaque escouade élit son intention localement : personne ne « marque d'abord » et
toutes visent la même zone. Nouveau : à chaque tour, AVANT les intentions doctrinales, une
passe d'assignation :

- une escouade **RÉCLAMANTE** par objectif non tenu par le camp (assignation gloutonne
  objectif libre ↔ escouade la plus proche, chaque escouade au plus une fois) ;
- les réclamantes jouent SCORE **vers leur objectif assigné** (pas « le plus proche global ») ;
- les autres reçoivent l'intention doctrinale : balanced → KILL/PRESERVE (élection actuelle),
  denial → DENY (score actuel avec +10 porteurs), reactive → plan courant (KILL/CONTEST/SCORE).

Mémoire : marqueur `(episode_number, turn)`, patron `DecapitationBot._focus_turn` — les
instances sont PARTAGÉES (pool de 100, §1.2.c du chantier panel), tout état est marqué par
épisode. Rupture : réclamante morte ou hors table → réassignation à la lecture suivante du tour.

C'est cette passe qui rend aux doctrines denial/reactive une base qui marque : dans ce format
(5 tours, VP d'objectifs chaque tour dès le tour 2, cumulés), « nier sans marquer » accumule un
retard irrattrapable — mécanisme mesuré qui a tué `standoff` (supprimé le 2026-08-11). Le déni
devient un comportement EN PLUS d'une base qui marque, plus jamais À LA PLACE.

### 3.2 Prime de tenue

Une destination située dans une zone d'objectif reçoit un bonus de tenue (constante hardcodée,
point de départ 3 hexes × w_obj, à mesurer) : sans lui, le score de destination fait sortir une
escouade d'une zone qu'elle contrôle pour un hex marginalement « meilleur ». Position courante
lue PAR FIGURINE (`unit_is_within_objective`), candidates par ancre — même heuristique assumée
que `_select_destination` côté doctrine.

### 3.3 Anti-empilement résiduel

Pour les NON-réclamantes : pénalité `w_crowd_bench × surplus d'OC allié` par zone, lue via
`objective_control_contributions` du moteur (motif `_surplus_oc_by_zone` de `bot_doctrines`).
L'assignation 3.1 règle l'empilement des réclamantes ; ce terme règle celui des autres.
Précédent mesuré (2026-08-12, bots doctrine avant `w_crowd`) : 2,6-3,0 escouades par zone,
1,7 zone couverte sur 5, 27,2 VP contre 53,8.

### 3.4 Géométrie par aire

Remplacer `_objective_anchors` (hex de plus petites coordonnées, distance ancre-à-ancre) par
`objective_distance_maps` (cartes de distance par AIRE, mémoïsées, 14.02) dans
`_score_destinations_weighted`. Le bot qui sert d'étalon doit mesurer la même géométrie que
l'agent qu'il évalue.

### 3.5 Ensuite seulement : constantes d'intention

`_VP_LEAD` (8), multiplicateur ×12 de `_elect_intent`, `_VALUE_LOSS_THRESHOLD` (3) : balayage
UN paramètre par run, `bot_ranking` graine fixe, les autres bots en contrôle (dérive 0,000
exigée), justification datée à côté de la constante — protocole des `_justification` de
`bot_movement_weights.json`. **Interdit avant 3.1-3.4** : un réglage pris sur une géométrie qui
change est périmé d'avance (leçon décapitation §12.9). Risque documenté à lever par la mesure :
si `s_kill ≥ s_score` presque toujours, « balanced » est un bot KILL déguisé — trois intentions
sur le papier, une en pratique.

### 3.6 Mesure et critère de sortie

- Avant/après : `bot_ranking`, `W40K_BOARD_PATH=board/44x60x1`, `--scenario-pool holdout`,
  seed fixe, résolution écrite à côté du chiffre.
- **`--episodes 6` pour le franchissement de §3.1-§3.4, `--episodes 20` réservé au réglage fin
  de §3.5** (décision utilisateur 2026-08-21). Le critère de sortie est une FOURCHETTE large
  ([0,40 ; 0,60]) : 6 épisodes la tranchent, et les deux mesures de référence le montrent —
  0,172/0,151/0,120 à 6 ép. (2026-08-21) contre 0,168/0,155/0,139 à 20 ép. (2026-08-20), soit
  moins de 0,02 d'écart. 20 épisodes coûtent 1 h 03 de temps mural (7 200 parties, 16 workers)
  contre ~20 min à 6 : ce budget appartient au balayage de constantes §3.5, où l'on départage
  des valeurs voisines, pas au franchissement d'une fourchette.
- Référence AVANT rejouée le 2026-08-21 dans les conditions exactes ci-dessus (20 ép., seed 42,
  board/44x60x1) : balanced **0,156**, denial **0,169**, reactive **0,140** ; panel doctrine
  attrition 0,724 / scorer 0,708 / racer 0,694 / decapitation 0,692 / alpha 0,653 /
  endgame 0,545, tactical 0,479.
- **Mesure APRÈS §3.1-§3.4 — 2026-08-21**, conditions exactes ci-dessus (6 ép., seed 42,
  board/44x60x1, pool holdout, 432 ép./bot, `--training-config x1`) :
  balanced **0,248** (avant 0,172), denial **0,269** (avant 0,151),
  reactive **0,264** (avant 0,120) ; panel doctrine attrition 0,699 / scorer 0,674 /
  racer 0,669 / decapitation 0,648 / alpha 0,590 / endgame 0,495, tactical 0,384.
  **Gain réel (+0,08 à +0,14 par bot), critère de sortie NON franchi** : les trois restent sous
  0,40. Contrôle de dérive : le classement est à somme constante (4,94 après contre 4,96 avant)
  et le gain reference_* (+0,316 cumulé) est exactement compensé par la perte des sept autres
  (−0,336) — la baisse des doctrine est le transfert de victoires, pas une dérive propre. Le
  contrôle strict exigerait la mesure AVANT des doctrine à 6 ép., qui n'a pas été conservée.
  **→ §3.5 s'ouvre** (le verrou « interdit avant 3.1-3.4 » est levé).
- **SORTIE** : moyenne bot-contre-bot de CHAQUE reference_* dans **[0,40 ; 0,60]** ; les six
  doctrine sans dérive (contrôle). ⛔ Non atteint au 2026-08-21 — voir la mesure ci-dessus.
- Puis SEULEMENT une fois la fourchette atteinte, re-poser
  `model_gating_min_benchmark_floor` depuis une mesure AGENT (`--test-only`,
  100 ép./bot) : plancher mesuré − marge documentée, **sémantique win-rate agent** (le 0,049 de
  J1 venait d'un score bot-contre-bot — mélange de sémantiques ; le 0,90 actuel, remis le
  2026-08-20, date d'avant la réparation). Config touchée ENTRE deux runs (relue à chaud).
- Tests : assignation (une réclamante par objectif libre, marqueur de tour, rupture sur mort),
  prime de tenue et anti-empilement en rouge/vert par mutation, aire vs ancre.

## 4. R0b — Échelle de checkpoints figés (éval)

But : l'étalon de force non saturable — win-rate du modèle courant contre ses archives
`robust_*`.

- Adversaire = policy chargée depuis une archive `*_robust_*.zip` + **SON**
  `_vec_normalize.pkl` (jamais celui du modèle courant) ; réutiliser le chemin adverse
  self-play (`env_wrappers`, `self_play_snapshot_*`) côté `bot_evaluation`.
- Archive d'architecture incompatible (pré-`charge_pair_net`, commit `d5ddffb5`) → ignorée
  avec message explicite nommant la rupture (§12.15) ; jamais un crash ni un silence.
  1/28 archives chargeables au 2026-08-22 (5 pré-`charge_pair_net` lèvent `RuntimeError Missing
  key(s)` au chargement et sont skippées §12.15) ; l'échelle se peuple à chaque run.
- Publication : `bot_eval/vs_ckpt_<score>` par barreau + agrégat `00_critical/` (min, moyenne).
- **Hors sélection et hors gate au départ** : nouvelle famille dans `bot_registry`
  (`CHECKPOINT_OPPONENT_KEYS` ou équivalent), exclue de `SELECTION_BOT_KEYS` et de
  `benchmark_floor`. Indicateur d'abord ; promotion en critère = décision utilisateur.
- **SORTIE** : un `--test-only` publie `vs_ckpt` pour ≥1 barreau ; test unitaire
  chargement + skip incompatible.

C'est la première marche de la league ([bot.md#league](../../Roadmap/bot.md#league)) : les
tranches 2-3 (PFSP, exploiters) restent différées post-démo.

## 5. R1 — Run de référence du curriculum

`x1_long --new`, APRÈS R0a + R0b, **rien d'autre ne bouge**. Produit : la ligne de base du
curriculum (panel + references réparées + `vs_ckpt`) et un nouveau barreau d'échelle.

## 6. R2 — Mix self-play (un levier)

= exécution de la ligne 7 du chemin critique (§0.59, livré jamais exécuté — câblage vérifié vif
dans `train.py`/`env_wrappers.py` le 2026-08-21). Profil dérivé de `x1_long` ; les clés
`self_play_*` de l'ancien `x1_selfplay` (purgé par `18dc8599`) se récupèrent au git.
Parts PROPOSÉES NON MESURÉES : ~55-60 % doctrine / 25-30 % self-play / 15 % random — à trancher
au chantier. Justification du mix : la part self-play casse la stationnarité (source de
l'exploitation apprise), la majorité doctrine garde les ancres de style (polyvalence).
Sortie : panel, references réparées, `vs_ckpt(R1)`, profils D.4, écart p1/p2.

## 7. R3 — Levier récompense

= [bot.md#recompense](../../Roadmap/bot.md#recompense), cadre acté : le proxy `max(NB×DMG)`
connu faux vit encore dans `reward_mapper` ; D.4 nomme les fautes d'abord ; **jamais dans le
même run que R2**.

## 8. Hors périmètre

- League PFSP/exploiters : post-démo ([bot.md#league](../../Roadmap/bot.md#league)).
- tactical : témoin gelé, aucun changement (§2 pt 2) ; le prompt « témoin resaturé » lancé le
  2026-08-21 tranche son affichage, pas son profil.
- Prompt C.4 (complémentarité, lancé le 2026-08-21) : indépendant ; sa conclusion se consigne
  ici et peut rouvrir la question du nombre de benchmarks — sur chiffres, pas avant.
