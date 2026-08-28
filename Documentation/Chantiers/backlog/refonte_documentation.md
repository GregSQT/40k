# Refonte Documentation/ — décisions actées et phases restantes

> **Chantier ouvert le 2026-08-27** (P1 livrée le jour même). Ordre du travail :
> [`../../Roadmap/ROADMAP_INDEX.md`](../../Roadmap/ROADMAP_INDEX.md) ; état des phases :
> [`../../Roadmap/doc.md#refonte`](../../Roadmap/doc.md#refonte).

## 1. Pourquoi

Audit complet du corpus le 2026-08-27 (~200 fichiers, 8 lecteurs, affirmations croisées avec le
code). Cinq constats, tous prouvés :

1. **Trois index concurrents, deux morts** — `README.md` (7 liens morts, ignorait `Roadmap/`),
   `Documentation_audit.md` (figé au 2026-07-05), `ROADMAP_INDEX.md` (seul vivant).
2. **L'état des chantiers était tenu deux fois** — sur chaque chiffre échantillonné
   (`TOTAL_ACTION_SIZE`, `obs_size`, P3-8, T6), `Roadmap/` était à jour et les docs `1_Agent/`
   retardaient. 13 fichiers gardaient un lien de gouvernance mort vers l'ex-`ROADMAP.md`.
3. **`Implémenté/` mélangeait archive et référence** — 22 références vivantes (dont 11 citées
   par le code de production comme contrat) noyées parmi ~45 journaux datés.
4. **Seul ce qui est sous garde machine reste vrai** — les deux seuls chiffres partout exacts
   étaient ceux vérifiés par un test (`test_squad_obs_structure_doc.py`) ou par le checker
   (`obs_size`). Tout le reste avait dérivé, sous des bandeaux de correction empilés.
5. **Plus de la moitié du poids n'était pas de la documentation** — mémoire RNCP (24 Mo),
   pitchs, prompts consommés, état d'outil.

## 2. Architecture actée (arbitrages utilisateur : A / A / A)

Un document = un RÔLE, lisible dans son chemin :

| Zone | Rôle | Contenu |
|---|---|---|
| `Documentation/Reference/<domaine>/` | RÉFÉRENCE — décrit l'état actuel, doit rester vrai ; toute livraison qui la rend fausse la corrige dans la même livraison (T2) | domaines : `moteur/`, `training/`, `jeu/`, `outils/`, `infra/` |
| `Documentation/Roadmap/` | ÉTAT — source unique de priorité ET d'état des chantiers | inchangé (outillé : checker, porte de fusion, hook) |
| `Documentation/Chantiers/` | SPEC/CONCEPTION vivante | contrats permanents (`Replay.md`, `analyzer_couverture.md`) + `Bot_refactor.md` (exception actée) + `v11/` (specs V11) + `backlog/` (chantiers jamais commencés) |
| `Documentation/Archives/` | ARCHIVE — jamais maintenue, bandeaux datés | `chantiers/` (journaux livrés), `docs/` (docs morts), `prompts/` (prompts consommés) |
| `Documentation/40k_rules/`, `Review/`, `sql/` | inchangés | règles officielles ; état d'outil `review_plan.py` ; scripts SQL |
| `Memoire_RNCP/`, `Communication/` (racine dépôt) | hors documentation technique | mémoire académique (purgé des parasites) ; pitchs, profil GitHub |

Règles de vie :
- **L'état d'un chantier vit à UN endroit : `Roadmap/`.** Aucun « statut » tenu dans les docs de
  détail (bandeaux posés sur les 4 docs `v11/` en P1 ; suppression des strates en P3).
- **Un chiffre recopié dans une RÉFÉRENCE est sous garde machine ou n'existe pas** — sinon le
  doc dit *où lire* la valeur dans le code (garde : P2).
- **L'archivage fait partie de la clôture** — les ✅ descendent de l'index vers
  `Roadmap/archives/<sujet>.md` dans la même livraison.
- **Un sujet = un document** (décision utilisateur 2026-08-27) : avant de créer un fichier,
  chercher le document de sujet qui devrait l'absorber. Un chantier à venir adossé à un système
  existant vit comme section « À faire » du document du sujet (l'état reste dans `Roadmap/`) ;
  seul un chantier sans système derrière lui (ex. PostgreSQL, MCTS) a un doc backlog autonome.
- **Le nom d'un fichier dit son OBJET, jamais son histoire** : pas de numéros de série, pas de
  dates, pas de noms de versions/branches dans les noms de fichiers — l'histoire vit dans git et
  dans les archives. Une source absorbée part en `Archives/docs/` avec un bandeau
  « absorbé par … » ; le document absorbeur garde une table « Correspondance des sources ».

## 3. P2 — Garde machine étendue (✅ livré 2026-08-27)

Objectif : que le checker couvre la nouvelle arborescence ENTIÈRE, pas seulement les documents
d'entrée. Contenu :

- **Passe 4 (ancres) sur `Reference/`** — préalable : nettoyer les dizaines de
  `fichier.py:ligne` historiques des ex-docs racine (`entrainement.md` en tête, raison de son
  statut `VALUE_ONLY_DOCS`) ; étendre `ANCHOR_TREES` (`scripts/check_doc_references.py`).
- **Passe liens sur tout le corpus vivant** (`Reference/`, `Chantiers/`, `Roadmap/`, README) —
  les liens morts trouvés par l'audit échappaient au checker, qui ne contrôle que 12 docs.
- **VALUE_CHECKS étendus** : `TOTAL_ACTION_SIZE` (le bandeau d'`entrainement.md` affichait 1 139
  pour un réel de 1 389), formes d'obs (`K_ALLY_SLOTS`, largeurs de champs — le tableau d'intro
  d'`observation_et_actions.md` contredisait le bloc gardé par test).
- **Contrôle d'accumulation** : un seuil de lignes ✅ dans `ROADMAP_INDEX.md` au-delà duquel le
  checker exige l'archivage (la discipline existait, rien ne la vérifiait — 200 lignes ✅
  accumulées).

Critère de clôture : `check_doc_references.py` rouge si un lien du corpus vivant meurt, si une
valeur gardée dérive, ou si l'index accumule ; suite verte sur l'état livré.

## 3bis. P4 — Consolidation « un sujet = un document » (en cours)

Décidée le 2026-08-27 après le constat utilisateur : le rangement par rôle ne suffit pas si les
documents gardent leurs noms de chantiers et leurs périmètres éclatés. Un domaine = une
livraison ; chaque fusion re-vérifie ses affirmations contre le code (rédacteurs parallèles avec
liste de purge prouvée + sections citées par le code préservées avec table de correspondance).

**Avant d'écrire un lot** : recenser les gardes qui lisent les documents cibles PAR BASENAME et les
re-pointer dans la même livraison — `VALUE_ONLY_DOCS` et `VALUE_CHECKS` de
`scripts/check_doc_references.py`, la liste de `scripts/backup_select.py`, et tout test qui ouvre un
`.md` (`grep -rn "\.md\"" tests/ scripts/`). Un renommage seul laisse ces gardes muettes au lieu de
rouges : le lot training a trouvé `test_squad_obs_structure_doc.py` déjà cassé depuis P1, son chemin
`DOC` pointant vers un fichier supprimé par le déplacement — cinq tests rouges que personne n'avait
vus, donc un bloc de tailles non gardé pendant tout ce temps. Vérifier aussi les titres de sections
servant d'ancres à un test (`text.index("### …")`) : un titre francisé casse l'isolation du bloc.

- **moteur + backlog : ✅ livrés le 2026-08-28.** `Reference/moteur/` 16 → 9 documents aux noms
  d'objet : `tour_de_jeu` (ex-AI_TURN réécrit : squelette pédagogique et ~800 lignes de doublons
  purgés, matrices V11 réunies par phase, symboles morts corrigés, fausse « divergence 12.04 »
  rectifiée preuve code à l'appui), `architecture_moteur`, `geometrie_et_distances` (fusion de
  5 sources), `verticalite`, `ligne_de_vue`, `allocation_attaques`, `squad_multi_figurines`
  (statut PR4 faux purgé), `capacites` (fusion 01-04 + §À faire ex-06), `perf_move_pool`.
  Backlog : `endless_duty` (spec+état fusionnés, obstacles re-vérifiés par le signet — 1/3/5/6/7
  soldés), `migration_postgresql` (scope pré-V11 re-cadré sur `W40KEngine`/`StepLogger`),
  `mcts_adversaire` ; 20 sources archivées en `Archives/docs/` avec bandeau retour ;
  `V11_entity_encoder_pointer` et `move_action_space_spatial_rework` déplacés vers
  `Reference/training/` (fusion à venir).
- **training : ✅ livré le 2026-08-28** — `observation_et_actions.md` (fusion observation +
  encodeur partagé/tête pointeur + grille égocentrique de move), `entrainement.md` (journal daté
  extrait en `Roadmap/archives/training_journal.md`), `metriques.md`, `panel_bots.md` (fusion du
  chantier panel + son talon chiffré) ; 7 sources archivées en `Archives/docs/` avec bandeau
  retour ; gardes re-pointées par basename (`VALUE_ONLY_DOCS`/`VALUE_CHECKS`,
  `test_squad_obs_structure_doc`, `test_bot_panel_reference`, `backup_select`).
- **jeu + outils : ✅ livré le 2026-08-28** — `Reference/jeu/` : `armes.md`, `regles_unites.md`,
  `couverture_regles.md` ; `Reference/outils/` : `configuration.md`, `tests.md`, `tests_front.md`,
  `outils_conformite.md` (fusion des 5 docs conformité) ; 11 sources archivées en `Archives/docs/`.
- **infra : 🟡 à faire** — `deploiement_nas.md`, `securite.md`, `acces_utilisateurs.md`.
- **v11 : ✅ livré le 2026-08-28** — `index_v11` (état ouvert + pointeurs),
  `tranches_et_ruptures` (spec R1→R8 + T1→T7), `decisions_du_joueur` (Phase A' P1→P5),
  `strategie_evaluation` ; `lecons_de_methode` dans `Reference/training/` ; strates §9.4
  pts 5/6/8 mises à jour.

## 4. P3 — Contenu (✅ scission et passes unitaires livrées le 2026-08-27 ; la réécriture d'AI_TURN est absorbée par la P4 ci-dessus)

Un chantier par document, préalable : P2 livré (le checker est le filet).

- **Scission `index_v11.md`** (8 350 lignes, 667 Ko) : entrées ouvertes §0 → absorbées
  par `Roadmap/v11_chemin_critique.md` ; §0bis (leçons de méthode, copie canonique) → document
  de méthode autonome ; §0hist → `Archives/chantiers/`. Purger les strates d'état de
  `tranches_et_ruptures.md` (§T6 « EN COURS » périmé) et `decisions_du_joueur.md` (§9.4 optionnels livrés).
- **Réécriture `AI_TURN.md`** (3 501 lignes) : le doc le plus dégradé — vieux guide comme
  squelette, 5 matrices V11 dispersées, deux « Target Restrictions Logic » contradictoires, un
  titre CHARGE PHASE sur du contenu de tir, `los_visibility_min_ratio` cité (0 hit code).
- **Passes unitaires** (chacune à une correction près, preuves dans l'audit du 2026-08-27) :
  `Weapon_rules.md` (en-tête « INDIRECT_FIRE non implémentée » contredit par sa propre table et
  le code), `USER_ACCESS_CONTROL.md` (section Frontend pré-F12 ; 4 modes documentés sur 10 en
  base), `metriques.md` (3 bots décrits sur 7 réels), bandeau `entrainement.md` (espace
  d'action), `FIGHT_RESOLVER_CONVERGENCE.md` et `squad.md` (headers « non implémenté »/« en
  pause » faux), `Endless_duty.md` (slots spec ↔ code).

## 5. P1 — livrée le 2026-08-27 (référence)

166 renames + 25 suppressions ; scripts recâblés (`check_doc_references.py`,
`backup_select.py`), 4 tests fonctionnels re-pointés, CLAUDE.md et README régénérés/mis à jour,
~110 fichiers balayés pour les chemins, liens `../ROADMAP.md` (13 fichiers) et renvois relatifs
morts réparés, ✅ de l'index descendus en `archives/`, le doc du panel de bots renommé (collision
d'homonymes), `coherency_removal_choix_agent.md` reclassé backlog (rien de livré, reverté).
