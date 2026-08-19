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
> et vérifie qu'aucun chantier ouvert de `Documentation/Implémentation/A_faire/` n'est devenu
> inatteignable depuis ce fichier — un document que plus aucun fichier sujet ne cite n'est plus
> priorisé, il est seulement stocké.
> La porte de fusion `scripts/check_roadmap_declared.py` (hook `prepare-commit-msg`, versionné
> dans `.githooks/`) : une fusion dans `main` est refusée quand **2** chantiers ont été livrés
> sans que ce fichier bouge. Se débloquer : écrire la ligne du chantier puis `git add` (l'index
> vaut déclaration) ; fusion hors chantier : `ROADMAP_GATE=off git commit`.
>
> **Contrats permanents** (jamais archivés, hors roadmap) :
> `Documentation/Implémentation/Replay.md` (contrat `step.log`, pipeline replay) et
> `Documentation/Implémentation/analyzer_couverture.md` (matrice règle → contrôle → champs de
> log) — relus à chaque livraison qui touche le journal.
>
> **Exceptions actées** (numérotées ici et nulle part ailleurs) : `Bot_refactor.md` vit à la racine d'`Documentation/Implémentation/` au lieu d'`A_faire/` (chantier vivant, chemin demandé) ; `archives/v11.md` porte l'historique du programme V11 entier et sert d'archive au sujet `v11_chemin_critique.md`.
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
| **J1 — Pipeline prouvé, ligne de base** 🔄 | Run `x1_long --new` du 2026-08-17 (en cours) | Critères de [training.md#run-verif](training.md#run-verif) verts sur ses courbes ; ligne de base du panel rejouée (`--test-only --step`) |
| **J2 — Le gym décide tout** | Chemin critique lignes 1–4 (P3-5, P3-6, P3-8, P4) ; le dégel de `TOTAL_ACTION_SIZE` qu'elles ouvrent embarque P3-0 | Plus aucune décision de jeu jouée par une heuristique à la place de l'agent, hors optionnels statués par mesure de regret |
| **J3 — Mesure de référence** | Chemin critique lignes 5–6 : profil de validation P5, puis `x1_long` (~20 h) | LE chiffre officiel du projet — solde §0.14, §0.67 et le critère T6 (via §10.6) |
| **J4 — Dépasser la mesure** | Self-play §0.59 (ligne 7), capacités 06, É9 second scénario — priorisés selon ce que la mesure révèle | Win-rate au-dessus de la mesure de référence, reproductible |
| **J5 — Démo** | Validation qualitative §10.6 volet 2 (joueur externe), validations navigateur front soldées | Un externe joue contre l'agent et le trouve crédible ; le front tient la partie de bout en bout |

---

## J1 🔄 En cours — ne rien casser

| Priorité | Sujets | Chantier | Fichier |
|---|---|---|---|
| 🔄 | training+bot | Run `x1_long --new` lancé le 2026-08-17 — à la fin : critères pipeline ([training.md#run-verif](training.md#run-verif)) puis ligne de base panel (`--test-only --step`) | [bot.md#etape8](bot.md#etape8) |

---

## J2–J4 — Chemin critique vers la mesure de référence

Ordre imposé — ne pas réorganiser sans décision explicite.

| # | Sujets | Chantier | Fichier | Bloqueur | ⚡/🚫 |
|---|---|---|---|---|---|
| 1 | moteur+training | **P3-5** Pile-in / consolidation | [v11_chemin_critique.md#p3-5](v11_chemin_critique.md#p3-5) | P5 à trancher ([v11_chemin_critique.md#p5](v11_chemin_critique.md#p5)) | 🚫 |
| 2 | training+moteur | **P3-6** Move-after-shooting + reactive move | [v11_chemin_critique.md#p3-6](v11_chemin_critique.md#p3-6) | — | 🚫 |
| 3 | training | **P3-8** Optionnels à statuer | [v11_chemin_critique.md#p3-8](v11_chemin_critique.md#p3-8) | — | 🚫 |
| 4 | training+moteur | **P4** Observation de support | [v11_chemin_critique.md#p4](v11_chemin_critique.md#p4) | — | 🚫 |
| 5 | training | **P5** Validation par tranche (profil manquant) | [v11_chemin_critique.md#p5](v11_chemin_critique.md#p5) | — | 🚫 |
| 6 | training | Mesure de référence `x1_long` | [v11_chemin_critique.md#mesure](v11_chemin_critique.md#mesure) | — | 🚫 |
| 7 | training+bot | Self-play §0.59 (livré, jamais exécuté) | [v11_chemin_critique.md#selfplay](v11_chemin_critique.md#selfplay) | — | 🚫 |

---

## J4 — Capacités

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur+training | **06** Armageddon abilities — 0/6 passes | [capacites.md#armageddon-06](capacites.md#armageddon-06) | 🚫 |

---

## Suspendus — ne pas commencer avant leur jalon

| Sujets | Chantier | Fichier | Jalon | ⚡/🚫 |
|---|---|---|---|---|
| moteur | **P3-0** Cohérence 03.03 — choix joueur/agent | [moteur.md#p3-0](moteur.md#p3-0) | Prochain dégel `TOTAL_ACTION_SIZE` (attendu en J2 ; celui du 2026-08-17 est passé sans lui) | 🚫 |
| moteur | **T7** Unification validation déploiement | [moteur.md#t7](moteur.md#t7) | Fix faux — re-analyser avant | 🚫 |
| moteur | **Phase B** Observation des niveaux | [moteur.md#phase-b](moteur.md#phase-b) | Phase A' validée + LoS 3D complet | 🚫 |
| training+bot | **É9** Second siège + second scénario | [training.md#e9](training.md#e9) | J4 — entraînement bot satisfaisant | 🚫 |
| training+bot | Validation qualitative §10.6 volet 2 | [bot.md#validation-externe](bot.md#validation-externe) | J5 — requis pour la démo | ⚡ |
| bot | MCTS à l'inférence §10.7 (plan B anti-coups-absurdes) | [bot.md#mcts-inference](bot.md#mcts-inference) | Après J3, seulement si la démo l'exige | 🚫 |

---

## Soutien — backlog hors jalons

### Prêt à démarrer

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| analyzer | ✅ PROJ.1.4 double_pile_in corrigé (2026-08-18) — overrun 12.06 loggué \"OVERRUN PILED IN\", faux positifs éliminés | — | ⚡ |
| analyzer | ✅ models_segment capturé après commit_move (2026-08-18) — faux positifs pile-in éliminés (fight_handler + w40k_core) | — | ⚡ |
| analyzer | ✅ Réserves PvP 04b tests code-review corrigés (2026-08-18) — symétrie garde, formule sentinelle, commentaire xdist | — | ⚡ |
| analyzer | ✅ Borne vert-vacant calculate_hex_distance (2026-08-18) — métrique cohérente avec charge_check_eligibility | — | ⚡ |
| analyzer | ✅ alloc_model_unknown HAZARDOUS/DE (2026-08-19) — grammar 6 + hazardDetails→target_model_id ; alloc_model_id lit [ALLOC_MODEL:] au lieu du legacy ordered_living_mids[0] ; 4 occurrences éliminées | — | ⚡ |
| analyzer | ✅ step_logger [DESPERATE ESCAPE] vs [HAZARDOUS] séparés (2026-08-18) — roll_hazard_for_unit tag distinct 09.07/24.15 | — | ⚡ |
| analyzer | ✅ analyzer_core branche [DESPERATE ESCAPE] (2026-08-18) — _apply_damage_and_handle_death appelée, HP/kill tracking opérationnel ; constante HAZARD_CONTEXT_DESPERATE_ESCAPE partagée | — | ⚡ |
| analyzer | ✅ test_analyzer_hazardous verrou [DESPERATE ESCAPE] vs [HAZARDOUS] (2026-08-18) — test rouge/vert sur branche DESPERATE ESCAPE + seuil source inspect corrigé | — | ⚡ |
| analyzer | ✅ analyzer overrun PILED IN regex (2026-08-18) — handle_fight_move matche OVERRUN PILED IN, faux positifs double_pile_in éliminés | — | ⚡ |
| analyzer | ✅ HAZARDOUS branche action_unit_id stale (2026-08-18) — _hz_unit_id = _dmg_actor_id or action_unit_id ; damage + lookup armurerie sur l'unité de la ligne, pas le header | — | ⚡ |
| analyzer | ✅ analyzer_core _hz_unit_id code mort supprimé + verrou HAZARDOUS unité morte (2026-08-18) — ligne 1702 dupliquée retirée ; test rouge/vert HAZARDOUS→unité morte→damage_missing_unit_hp | — | ⚡ |
| moteur+analyzer | ✅ step_logger event [DEAD] + pré-capture [MODELS:] tir/move (2026-08-19) — destroy_model émet un event dead dans action_logs pour toute raison ; [MODELS:] SHOOT/MOVE pré-capturés avant effets (hazardous, etc.) | — | ⚡ |
| tests | ✅ _charge_budget_subhex unit= optionnel (2026-08-19) — paramètre unit= rendu optionnel, perf micro | — | ⚡ |
| tests | ✅ couverture deploy_squad_destinations + select_rule_choice (2026-08-19) — tests humain pour ces deux paths | — | ⚡ |
| tests | ✅ simplification fixture deploy_game (2026-08-19) — retrait assertion vacuuse | — | ⚡ |
| step_logger+analyzer | ✅ hazardous 0-MW no raise (2026-08-19) — wounds=0 (aucun dé raté) → [NO ALLOC] sans require_key ; analyzer saute _apply_damage si mw==0 (HAZARDOUS + DESPERATE ESCAPE) | — | ⚡ |
| moteur+analyzer | ✅ dead events step.log + pré-capture tir protégée (2026-08-19) — _build_step_log_details mappe model_id/reason ; _emit_squad_shoot_log try/except ConfigurationError ; is None strict | — | ⚡ |
| analyzer | Champs manquants `step.log` L6→L28 (17 restantes après livraison L14/L19/L22/L25/L27/L28 le 2026-08-18) | [analyzer.md#champs-step-log](analyzer.md#champs-step-log) | ⚡ |
| analyzer | Corpus de règles vérifiable | [analyzer.md#corpus-regles](analyzer.md#corpus-regles) | ⚡ |
| front | ✅ Tests front T7+T8–T13 livrés (2026-08-19) — 82 tests vitest verts (Couche B : utils/DOM/hook), Playwright config+E2E Couche C, orchestration front_test_all.sh, fuzzing étendu+snapshots | [front.md#tests](front.md#tests) | ⚡ |
| front | Validations navigateur en attente | [front.md#validations-nav](front.md#validations-nav) | ⚡ |
| training+bot | ✅ Benchmark floor gate §4.D livré (2026-08-18) — 3 bots de référence (balanced/denial/reactive) sur 4 scénarios holdout_regular ; seuil 0.90 après mesure ; `model_gating_enabled` sur x1_long | [v11_chemin_critique.md#benchmark-gate](v11_chemin_critique.md#benchmark-gate) | |
| training+bot | ✅ scenario_bench-01..04 dupliqués supprimés (2026-08-18) — fichiers byte-for-byte identiques aux scenario_bot-01..04, glob fallback ramassait 8 scénarios au lieu de 4, épisodes/scénario divisés par 2 sans contrepartie | — | |
| moteur | ✅ Fix §11.04 budget charge par-figurine gym (2026-08-19) — `_attempt_charge_to_destination` rejetait pas les destinations roll+extra ; verrou + test rouge/vert | — | ⚡ |
| moteur+services | ✅ Fix review-findings (2026-08-18) — surface refus moteur squad, wsgi leading-comma, message vide | — | |
| security | ✅ Chantier clos (2026-08-19) — F1–F15 résolues, validation navigateur OK, doc déplacé dans Implémenté/ | [archives/security.md](archives/security.md) | ⚡ |
| infra | Perf `generate_compact_formation` | [infra.md#perf-formation](infra.md#perf-formation) | ⚡ |
| infra | ✅ gzip + Brotli livrés (2026-08-18) — stage `brotli-builder`, `load_module` contexte main, directives server | [archives/infra.md](archives/infra.md) | ⚡ |

### Bloqués par une décision utilisateur

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur | Replis `unit_by_id` (T0 = signature à décider) | [moteur.md#unit-by-id](moteur.md#unit-by-id) | 🚫 |
| moteur | Endless Duty (obstacles 3 et 7 à décider) | [moteur.md#endless-duty](moteur.md#endless-duty) | 🚫 |
| front | Scission `bcKey` géométrie/contrôle (écartée le 2026-08-12, à arbitrer) | [front.md#bckey](front.md#bckey) | ⚡ |

### À cadrer avant d'ouvrir

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur | LoS 3D : tir à travers un mur depuis un étage (signalé 2026-08-11, jamais cadré) | [moteur.md#los-mur-etage](moteur.md#los-mur-etage) | 🚫 |
| bot+training | Chantier récompense distinct (relevé du chantier panel) | [bot.md#recompense](bot.md#recompense) | 🚫 |

### Lourds — re-cadrer avant toute reprise

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| moteur | Preview de tir sans deepcopy | [moteur.md#preview-tir](moteur.md#preview-tir) | 🚫 |
| infra | Noyau natif BFS move/empreintes — pool de move = 29 % d'une partie d'évaluation | [infra.md#noyau-natif](infra.md#noyau-natif) | ⚡ |
| infra | Migration PostgreSQL | [infra.md#postgresql](infra.md#postgresql) | ⚡ |
| infra | MCTS adversaire d'entraînement | [infra.md#mcts](infra.md#mcts) | 🚫 |
| bot | Tranches 2-3 benchmark (PFSP, league, exploiters) — différées | [bot.md#league](bot.md#league) | 🚫 |

---

## Hygiène documentaire

| Sujets | Chantier | Fichier | ⚡/🚫 |
|---|---|---|---|
| doc | `obs_size` justification à mettre à jour | [doc.md#obs-size](doc.md#obs-size) | ⚡ |
| doc | Notes vitesse entraînement périmées | [doc.md#vitesse](doc.md#vitesse) | ⚡ |
| doc | Ancres de ligne périmées docs V11 | [doc.md#ancres](doc.md#ancres) | ⚡ |
| doc | Dette d'ancres G1/G2/G4 de V11_tranches §1bis | [doc.md#dette-tranches](doc.md#dette-tranches) | ⚡ |
| doc | Bandeaux périmés V11_agent_rework §0bis (assumés depuis 2026-07-20) | [doc.md#bandeaux-0bis](doc.md#bandeaux-0bis) | ⚡ |
| doc | §0.19 : les ✅ T2→T5 revérifiés par lecture seule | [doc.md#reverif-t2-t5](doc.md#reverif-t2-t5) | ⚡ |
| training | ✅ Note `bot_eval_freq_normal` réécrite (2026-08-18) — d_bot_eval_seconds=98s, 5h54 pour 50k épisodes | — | |
