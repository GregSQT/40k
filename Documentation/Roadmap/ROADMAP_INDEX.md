# Roadmap Index — Ordre global du travail

> **Source unique de priorité.** Ce fichier tranche l'ordre, les fichiers sujets tranchent le
> contenu. Historique d'un sujet : `archives/<sujet>.md`. `archives/ROADMAP.md` est un FOSSILE
> gelé (l'ancien fichier monolithique) : ne pas le lire en session, ne plus le mettre à jour.
>
> **Règles d'arbitrage :** Code > décision datée > priorité ici > tout autre doc.
> Conflit résiduel → demander à l'utilisateur.
>
> **Discipline.** Ouvrir = ajouter une ligne ici D'ABORD. Livrer = marquer ✅ ici + vider/archiver
> dans le fichier sujet, dans la même livraison.
>
> **Outillage.** `python3 scripts/check_doc_references.py` contrôle ce fichier, les fichiers
> sujets et les deux contrats permanents (renvois, liens, valeurs recopiées, ancres, sortes),
> et vérifie qu'aucun chantier ouvert de `Documentation/Chantiers/backlog/` n'est devenu
> inatteignable depuis ce fichier — un document que plus aucun fichier sujet ne cite n'est plus
> priorisé, il est seulement stocké.
> La porte de fusion `scripts/check_roadmap_declared.py` (hook `prepare-commit-msg`, versionné
> dans `.githooks/`) : une fusion dans `main` est refusée quand **2** chantiers ont été livrés
> sans que ce fichier bouge. Se débloquer : écrire la ligne du chantier puis `git add` (l'index
> vaut déclaration) ; fusion hors chantier : `ROADMAP_GATE=off git commit`.
>
> **Contrats permanents** (jamais archivés, hors roadmap) :
> `Documentation/Chantiers/Replay.md` (contrat `step.log`, pipeline replay) et
> `Documentation/Chantiers/analyzer_couverture.md` (matrice règle → contrôle → champs de
> log) — relus à chaque livraison qui touche le journal.
>
> **Exceptions actées** (numérotées ici et nulle part ailleurs) : `Bot_refactor.md` vit à la racine de `Documentation/Chantiers/` au lieu de `backlog/` (chantier vivant, chemin demandé) ; `archives/v11.md` porte l'historique du programme V11 entier et sert d'archive au sujet `v11_chemin_critique.md`.
>
> **Pendant entraînement.** `⚡` = peut démarrer sans interrompre un run (ne touche pas
> `config/**/*.json`, ne modifie pas le moteur). `🚫` = ne pas démarrer : risque de biaiser le
> run ou conflit direct avec le processus d'entraînement.

---

## Direction — le fil

**CAP : la démo de financement** — un agent RL crédible sur les deux rosters retenus (Space
Marines / Orks, décision 2026-07-19), prouvé par une mesure quantitative (win-rate `x1_long`
contre le panel) et une validation qualitative par un joueur externe.

Tout chantier sert un jalon ci-dessous, ou attend. Les jalons sont séquentiels ; le soutien
(analyzer, security, infra, hygiène doc) avance en parallèle quand un jalon le réclame.

| Jalon | Contenu | Critère de sortie |
|---|---|---|
| **J1 — Pipeline prouvé, ligne de base** ✅ | Run `x1_long --new` terminé le 2026-08-20 ; ligne de base REJOUÉE le 2026-08-21 sur `robust_0.8463` (post-rupture §12.15) : combined agent `0,8567`, pire bot `attrition = 0,810` ; reference bots mesurés bot-contre-bot (balanced `0,168`, denial `0,155`, reactive `0,139`) ; `benchmark_floor` remis à `0,90` le 2026-08-20 (le `0,049` mélangeait les sémantiques) — gate RETIRÉ depuis, le 2026-08-22 | Critères de [training.md#run-verif](training.md#run-verif) verts ; ligne de base panel rejouée ✅ |
| **J2 — Le gym décide tout** ✅ | P3-5, P3-6, P3-8, P4, P5 livrés ; `TOTAL_ACTION_SIZE` 1159→1389, `obs_size` 16671→16703 ; ré-entraînement `--new` nécessaire | Plus aucune décision de jeu jouée par une heuristique à la place de l'agent, hors optionnels statués par mesure de regret ✅ |
| **J3 — Mesure de référence** | Curriculum R1→R3 (URGENCE), puis `x1_long` (~6 h) | LE chiffre officiel du projet — solde §0.14, §0.67 et le critère T6 (via §10.6) |
| **J4 — Dépasser la mesure** | Self-play §0.59 (ligne 7), capacités 06, É9 second scénario — priorisés selon ce que la mesure révèle | Win-rate au-dessus de la mesure de référence, reproductible |
| **J5 — Démo** | Validation qualitative §10.6 volet 2 (joueur externe), validations navigateur front soldées | Un externe joue contre l'agent et le trouve crédible ; le front tient la partie de bout en bout |

---

## 🔴 URGENCE — Curriculum : adversaires et étalons (décision 2026-08-21)

**Décision utilisateur du 2026-08-21 — passe devant les lignes J2.** Les instruments
d'évaluation sont saturés (reference_* battus 93-100 % dès 10k épisodes, `vs_tactical` à 1,00
dès 30k) : R0a/R0b se livrent AVANT le prochain run long, puis le curriculum R1→R3 enchaîne
(R2 = ligne 7 du chemin critique, R3 = chantier récompense). tactical reste gelé (§0.55/D10).
Détail : `Documentation/Chantiers/backlog/curriculum_adversaires_etalons.md`.

| # | Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|---|
| 3 | training | **R1→R3** Séquence des runs du curriculum (un levier par run) | [training.md#curriculum](training.md#curriculum) | 🚫 |

---

## J3 — Mesure de référence

| # | Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|---|
| 6 | training | Curriculum R1→R3 (un levier par run) — débloque la mesure | [training.md#curriculum](training.md#curriculum) | 🚫 |
| 7 | training | Mesure de référence `x1_long` (~6 h) | [v11_chemin_critique.md#mesure](v11_chemin_critique.md#mesure) | 🚫 |

---

## J4 — Self-play + Capacités

| # | Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|---|
| 8 | training+bot | Self-play §0.59 (livré, jamais exécuté) | [v11_chemin_critique.md#selfplay](v11_chemin_critique.md#selfplay) | 🚫 |
| 9 | moteur+training | **06** Armageddon abilities — 0/6 passes | [capacites.md#armageddon-06](capacites.md#armageddon-06) | 🚫 |

---

## Suspendus — ne pas commencer avant leur jalon

| Sujets | Chantier | Fichier | Jalon | ⚡/🚫 |
|---|---|---|---|---|
| moteur | **T7** Unification validation déploiement | [moteur.md#t7](moteur.md#t7) | Fix faux — re-analyser avant | 🚫 |
| moteur | **Phase B** Observation des niveaux | [moteur.md#phase-b](moteur.md#phase-b) | Phase A' validée + LoS 3D complet | 🚫 |
| training+bot | **É9** Second siège + second scénario — levier `agent_seat_p2_ratio` livré 2026-08-28, plus deux correctifs de suivi le même jour : `_resolve_seat_p2_ratio` et `get_seat_stats` retournent `None` en modes de siège fixes au lieu d'un `0.5` interne trompeur (`ai/env_wrappers.py`, `ai/train.py`, tests rouge→vert). Le second SCÉNARIO reste ouvert | [training.md#e9](training.md#e9) | J4 — entraînement bot satisfaisant | 🚫 |
| training+bot | Validation qualitative §10.6 volet 2 | [bot.md#validation-externe](bot.md#validation-externe) | J5 — requis pour la démo | ⚡ |
| bot | MCTS à l'inférence §10.7 (plan B anti-coups-absurdes) | [bot.md#mcts-inference](bot.md#mcts-inference) | Après J3, seulement si la démo l'exige | 🚫 |

---

## Soutien — backlog hors jalons

### Prêt à démarrer

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur+training | **Stratagèmes réactifs** — Fire Overwatch §15.08 + Heroic Intervention §15.11 ; **slots obs réservés avant R1** (`"charged"` UNIT_BIN + 2 types AGENT_DECISION) livrés 2026-08-25, implémentation J4 | [moteur.md#reactive-stratagems](moteur.md#reactive-stratagems) | 🚫 |
| front | Validations navigateur en attente | [front.md#validations-nav](front.md#validations-nav) | ⚡ |

### À cadrer avant d'ouvrir

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur | LoS 3D : tir à travers un mur depuis un étage (signalé 2026-08-11, jamais cadré) | [moteur.md#los-mur-etage](moteur.md#los-mur-etage) | 🚫 |
| bot+training | Chantier récompense distinct (relevé du chantier panel) | [bot.md#recompense](bot.md#recompense) | 🚫 |

### Lourds — re-cadrer avant toute reprise

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur | Preview de tir sans deepcopy | [moteur.md#preview-tir](moteur.md#preview-tir) | 🚫 |
| infra | **Accélération entraînement RL** — Phase 0 ✅ + Phase 1 ✅ **mesurée machine au repos 2026-08-26** (1.1–1.9 livrés ; **1.7 ✅ buffers numpy livrés (2026-08-26)** ; gain réel sur la QUEUE — P99 −44 %, wall −32 %, médiane −7 % sur 3+3 répétitions) ; bench_env_step ✅ **reproductible (2026-08-26)** ; **Phase 2 ✅ complète (2.1–2.4, 2026-08-26)** (GPU buffer, GPU metrics, inline masks ; +13–16 % fps mesuré run réel) ; **Phase 4 : 4.1 ✅ livré (2026-08-27)** — gate d'étape parallélisé, décision B actée et implémentée (B1–B7, unification du harnais checkpoint dans le harnais bot, parité confirmée 8-ép + tests) ; **4.2 ✅ livré (2026-08-27)** — pool persistant + jeton version `(model_path, mtime)`, rechargement seulement sur changement, `create_checkpoint_eval_pool`, `ExploiterProbeCallback._on_training_start/end` ; **4.3 ✅** `bot_eval_n_workers` → 2 (n=6 plus lent que n=2, F_6=1 293 s vs F_2=58 s, 2026-08-27) ; Phase 3 option A actée mais non lancée (chantier dédié hors run, porte le ×3-6) | [infra.md#perf-entrainement](infra.md#perf-entrainement) | ⚡ |
| infra | Noyau natif BFS move/empreintes — pool de move = 29 % d'une partie d'évaluation | [infra.md#noyau-natif](infra.md#noyau-natif) | ⚡ |
| infra | Migration PostgreSQL | [infra.md#postgresql](infra.md#postgresql) | ⚡ |
| infra | MCTS adversaire d'entraînement | [infra.md#mcts](infra.md#mcts) | 🚫 |
| bot | Tranches 2-3 benchmark — schedule P0→P10 + exploiters : code et tests livrés 2026-08-22 (`--etape`, `curriculum.json`, pool figé par-env, `ExploiterProbeCallback` sondage synchrone + `validate_exploiter_protocol` + `exploiter_config`, 24 tests verrou) ; restent les 14 runs (~260 h) | [bot.md#league](bot.md#league) | 🚫 |

---

## Hygiène documentaire

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| doc | 🟠 **Refonte Documentation/** — P1–P3 livrées (2026-08-27) ; P4 consolidation : moteur+backlog (16→9 docs, 20 sources archivées), training (7→5 docs, 7 sources archivées) et **jeu+outils** (jeu 3→3 noms d'objet, outils 7→4 dont fusion 5→1 `outils_conformite`, 11 sources archivées) livrés 2026-08-28 ; **v11** (5 renommages d'objet, strates §9.4 purges) et **infra** (3 renommages d'objet, corps re-vérifiés, gardes re-pointées) livrés 2026-08-28 — P4 complète, les 5 lots livrés ; correctif de suivi : slot `m` du dashboard de `metriques.md` réaligné sur `m_immediate_reward_ratio_mean` (l'ancien tag n'est plus émis) | [doc.md#refonte](doc.md#refonte) | ⚡ |
| doc | Dette d'ancres G1/G2/G4 de tranches_et_ruptures §1bis | [doc.md#dette-tranches](doc.md#dette-tranches) | ⚡ |
| doc | Bandeaux périmés index_v11 §0bis (assumés depuis 2026-07-20) | [doc.md#bandeaux-0bis](doc.md#bandeaux-0bis) | ⚡ |
| doc | §0.19 : les ✅ T2→T5 revérifiés par lecture seule | [doc.md#reverif-t2-t5](doc.md#reverif-t2-t5) | ⚡ |
