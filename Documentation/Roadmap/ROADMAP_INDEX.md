# Roadmap Index — Ordre global du travail

> **Source unique de priorité.** Ce fichier tranche l'ordre, les fichiers sujets tranchent le contenu.
> Pour l'historique d'un sujet : `archives/<sujet>.md`.
>
> **Règles d'arbitrage :** Code > décision datée > priorité ici > tout autre doc.
> Conflit résiduel → demander à l'utilisateur.
>
> **Discipline.** Ouvrir = ajouter une ligne ici D'ABORD. Livrer = marquer ✅ ici + vider/archiver dans le fichier sujet, dans la même livraison.

---

## 🔄 En cours — ne rien casser

| Priorité | Sujets | Chantier | Fichier |
|---|---|---|---|
| 🔄 | training+bot | Étape 8 : run `x1_long --new` lancé le 2026-08-17 — résultats à valider avec `--test-only --step` | [bot.md#etape8](bot.md#etape8) |

---

## 1. Chemin critique vers la mesure de référence

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

## 2. Capacités

| Sujets | Chantier | Fichier |
|---|---|---|
| moteur+training | **06** Armageddon abilities — 0/6 passes | [capacites.md](capacites.md) |

---

## 3. Suspendus — ne pas commencer avant jalon explicite

| Sujets | Chantier | Fichier | Jalon |
|---|---|---|---|
| moteur | **P3-0** Cohérence 03.03 — choix joueur/agent | [moteur.md#p3-0](moteur.md#p3-0) | Prochain dégel `TOTAL_ACTION_SIZE` |
| moteur | **T7** Unification validation déploiement | [moteur.md#t7](moteur.md#t7) | Fix faux — re-analyser avant |
| moteur | **Phase B** Observation des niveaux | [moteur.md#phase-b](moteur.md#phase-b) | Phase A' validée + LoS 3D complet |
| training+bot | **É9** Second siège + second scénario | [training.md#e9](training.md#e9) | Entraînement bot satisfaisant |
| training+bot | Validation qualitative §10.6 volet 2 | [bot.md#validation-externe](bot.md#validation-externe) | Requis pour la démo |

---

## 4. Backlog

### Prêt à démarrer

| Sujets | Chantier | Fichier |
|---|---|---|
| training | Run `--new` x1 VÉRIFICATION (🔜 espace décision modifié) | [training.md#run-verif](training.md#run-verif) |
| analyzer | Conformité moteur — 1 mort fantôme restant | [analyzer.md#conformite](analyzer.md#conformite) |
| analyzer | Champs manquants `step.log` L6→L28 | [analyzer.md#champs-step-log](analyzer.md#champs-step-log) |
| front | Tests front T2b/T3a/T7 + couches B/C | [front.md#tests](front.md#tests) |
| front | Validations navigateur en attente | [front.md#validations-nav](front.md#validations-nav) |
| security | Étapes 4, 5, 7, 8 | [security.md](security.md) |
| moteur | Pile-in/Overrun 12.06 par-figurine (prérequis P3-5) | [moteur.md#pile-in](moteur.md#pile-in) |
| infra | Perf `generate_compact_formation` | [infra.md#perf-formation](infra.md#perf-formation) |
| infra | gzip/Brotli (avec Security étape 5) | [infra.md#gzip](infra.md#gzip) |

### Bloqués par une décision utilisateur

| Sujets | Chantier | Fichier |
|---|---|---|
| moteur | Replis `unit_by_id` (T0 = signature à décider) | [moteur.md#unit-by-id](moteur.md#unit-by-id) |
| moteur | Endless Duty (obstacles 3 et 7 à décider) | [moteur.md#endless-duty](moteur.md#endless-duty) |

### Lourds — re-cadrer avant toute reprise

| Sujets | Chantier | Fichier |
|---|---|---|
| moteur | Preview de tir sans deepcopy | [moteur.md#preview-tir](moteur.md#preview-tir) |
| infra | Migration PostgreSQL | [infra.md#postgresql](infra.md#postgresql) |
| infra | MCTS adversaire d'entraînement | [infra.md#mcts](infra.md#mcts) |
| bot | Tranches 2-3 benchmark (PFSP, league, exploiters) — différées | [bot.md#league](bot.md#league) |

---

## 5. Hygiène documentaire

| Sujets | Chantier | Fichier |
|---|---|---|
| doc | `obs_size` justification à mettre à jour | [doc.md#obs-size](doc.md#obs-size) |
| doc | Notes vitesse entraînement périmées (5 profils) | [doc.md#vitesse](doc.md#vitesse) |
| doc | Ancres de ligne périmées docs V11 | [doc.md#ancres](doc.md#ancres) |
| training | Note `bot_eval_freq_normal` à réécrire avec coût mesuré | [training.md#note-eval-freq](training.md#note-eval-freq) |
