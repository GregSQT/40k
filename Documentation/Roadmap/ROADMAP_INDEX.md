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

| # | Sujets | Chantier | Fichier | Bloqueur |
|---|---|---|---|---|
| 1 | moteur+training | **P3-5** Pile-in / consolidation | [v11_chemin_critique.md#p3-5](v11_chemin_critique.md#p3-5) | [moteur.md#pile-in](moteur.md#pile-in) |
| 2 | training+moteur | **P3-6** Move-after-shooting + reactive move | [v11_chemin_critique.md#p3-6](v11_chemin_critique.md#p3-6) | — |
| 3 | training | **P3-8** Optionnels à statuer | [v11_chemin_critique.md#p3-8](v11_chemin_critique.md#p3-8) | — |
| 4 | training+moteur | **P4** Observation de support | [v11_chemin_critique.md#p4](v11_chemin_critique.md#p4) | — |
| 5 | training | **P5** Validation par tranche (profil manquant) | [v11_chemin_critique.md#p5](v11_chemin_critique.md#p5) | — |
| 6 | training | Mesure de référence `x1_long` | [v11_chemin_critique.md#mesure](v11_chemin_critique.md#mesure) | — |
| 7 | training+bot | Self-play §0.59 (livré, jamais exécuté) | [v11_chemin_critique.md#selfplay](v11_chemin_critique.md#selfplay) | — |

---

## J4 — Capacités

| Sujets | Chantier | Fichier |
|---|---|---|
| moteur+training | **06** Armageddon abilities — 0/6 passes | [capacites.md](capacites.md) |

---

## Suspendus — ne pas commencer avant leur jalon

| Sujets | Chantier | Fichier | Jalon |
|---|---|---|---|
| moteur | **P3-0** Cohérence 03.03 — choix joueur/agent | [moteur.md#p3-0](moteur.md#p3-0) | Prochain dégel `TOTAL_ACTION_SIZE` (attendu en J2) |
| moteur | **T7** Unification validation déploiement | [moteur.md#t7](moteur.md#t7) | Fix faux — re-analyser avant |
| moteur | **Phase B** Observation des niveaux | [moteur.md#phase-b](moteur.md#phase-b) | Phase A' validée + LoS 3D complet |
| training+bot | **É9** Second siège + second scénario | [training.md#e9](training.md#e9) | J4 — entraînement bot satisfaisant |
| training+bot | Validation qualitative §10.6 volet 2 | [bot.md#validation-externe](bot.md#validation-externe) | J5 — requis pour la démo |
| bot | MCTS à l'inférence §10.7 (plan B anti-coups-absurdes) | [bot.md#mcts-inference](bot.md#mcts-inference) | Après J3, seulement si la démo l'exige |

---

## Soutien — backlog hors jalons

### Prêt à démarrer

| Sujets | Chantier | Fichier |
|---|---|---|
| analyzer | Conformité moteur — 1 mort fantôme restant | [analyzer.md#conformite](analyzer.md#conformite) |
| analyzer | Champs manquants `step.log` L6→L28 | [analyzer.md#champs-step-log](analyzer.md#champs-step-log) |
| analyzer | Corpus de règles vérifiable | [analyzer.md#corpus-regles](analyzer.md#corpus-regles) |
| front | Tests front T2b/T3a/T7 + couches B/C | [front.md#tests](front.md#tests) |
| front | Validations navigateur en attente | [front.md#validations-nav](front.md#validations-nav) |
| security | Étapes 4, 5, 7, 8 | [security.md](security.md) |
| ✅ moteur | Pile-in/Overrun 12.06 par-figurine (prérequis P3-5) — livré 2026-08-18 | — |
| infra | Perf `generate_compact_formation` | [infra.md#perf-formation](infra.md#perf-formation) |
| infra | gzip/Brotli (avec Security étape 5) | [infra.md#gzip](infra.md#gzip) |

### Bloqués par une décision utilisateur

| Sujets | Chantier | Fichier |
|---|---|---|
| moteur | Replis `unit_by_id` (T0 = signature à décider) | [moteur.md#unit-by-id](moteur.md#unit-by-id) |
| moteur | Endless Duty (obstacles 3 et 7 à décider) | [moteur.md#endless-duty](moteur.md#endless-duty) |
| front | Scission `bcKey` géométrie/contrôle (écartée le 2026-08-12, à arbitrer) | [front.md#bckey](front.md#bckey) |

### À cadrer avant d'ouvrir

| Sujets | Chantier | Fichier |
|---|---|---|
| moteur | LoS 3D : tir à travers un mur depuis un étage (signalé 2026-08-11, jamais cadré) | [moteur.md#los-mur-etage](moteur.md#los-mur-etage) |

### Lourds — re-cadrer avant toute reprise

| Sujets | Chantier | Fichier |
|---|---|---|
| moteur | Preview de tir sans deepcopy | [moteur.md#preview-tir](moteur.md#preview-tir) |
| infra | Migration PostgreSQL | [infra.md#postgresql](infra.md#postgresql) |
| infra | MCTS adversaire d'entraînement | [infra.md#mcts](infra.md#mcts) |
| bot | Tranches 2-3 benchmark (PFSP, league, exploiters) — différées | [bot.md#league](bot.md#league) |

---

## Hygiène documentaire

| Sujets | Chantier | Fichier |
|---|---|---|
| doc | `obs_size` justification à mettre à jour | [doc.md#obs-size](doc.md#obs-size) |
| doc | Notes vitesse entraînement périmées | [doc.md#vitesse](doc.md#vitesse) |
| doc | Ancres de ligne périmées docs V11 | [doc.md#ancres](doc.md#ancres) |
| doc | Dette d'ancres G1/G2/G4 de V11_tranches §1bis | [doc.md#dette-tranches](doc.md#dette-tranches) |
| doc | Bandeaux périmés V11_agent_rework §0bis (assumés depuis 2026-07-20) | [doc.md#bandeaux-0bis](doc.md#bandeaux-0bis) |
| training | Note `bot_eval_freq_normal` à réécrire avec coût mesuré | [training.md#note-eval-freq](training.md#note-eval-freq) |
