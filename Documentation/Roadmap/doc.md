# Hygiène documentaire — Tâches ouvertes

---

## Refonte Documentation/ — architecture par rôle {#refonte}

**Décisions actées le 2026-08-27** (audit complet du corpus, arbitrages utilisateur A/A/A) :
arborescence par RÔLE — `Documentation/Reference/<domaine>/` (décrit l'état actuel, doit rester
vrai), `Documentation/Chantiers/` (vivant : contrats permanents, `v11/`, `backlog/`),
`Documentation/Archives/` (mort : `chantiers/`, `docs/`, `prompts/`) ; `Roadmap/`, `Review/`,
`40k_rules/`, `sql/` inchangés ; mémoire RNCP → `Memoire_RNCP/` et pitchs → `Communication/`
(racine du dépôt). Détail des décisions et des phases restantes :
`Documentation/Chantiers/backlog/refonte_documentation.md`.

- **P1 structure** : ✅ livrée le 2026-08-27 — déplacements, mise à jour des scripts, des tests
  et de CLAUDE.md, README régénéré, purge des ✅ de l'index, liens réparés.
- **P2 garde machine étendue** : ✅ livrée le 2026-08-27 — passe LIENS corpus vivant, `ANCHOR_TREES` étendu à `Reference/` (23 ancres fichier:ligne purgées d'`entrainement.md`), `VALUE_CHECKS` étendus (`TOTAL_ACTION_SIZE`, dimensions `allies_cont/allies_bin`), accumulation ROADMAP ≤ 20 ✅ ; 51 fragments morts #s0.X retirés de tranches_et_ruptures/phaseA/eval_strategy.
- **P3 contenu** : ✅ livrée le 2026-08-27 — scission `index_v11.md` (§0bis → doc de
  méthode, §0hist → archive) + passes unitaires sur 11 docs (`USER_ACCESS_CONTROL`,
  `metriques.md`, bandeau `entrainement.md`… — les noms de fichiers 40k_rules restant inchangés).
- **P4 consolidation « un sujet = un document »** (décision utilisateur 2026-08-27 : noms d'objet,
  fusion des fragments, corps re-vérifiés contre le code) :
  - **moteur + backlog** : ✅ livrés le 2026-08-28 — `Reference/moteur/` ramené de 16 fichiers à
    9 documents aux noms d'objet (`tour_de_jeu`, `architecture_moteur`, `geometrie_et_distances`,
    `verticalite`, `ligne_de_vue`, `allocation_attaques`, `squad_multi_figurines`, `capacites`,
    `perf_move_pool`) ; backlog : `endless_duty.md` (spec+état fusionnés), `migration_postgresql.md`,
    `mcts_adversaire.md`, chantier 06 absorbé en §À faire de `capacites.md` ; 20 sources archivées
    en `Archives/docs/` avec bandeau retour.
  - **training** : ✅ livré le 2026-08-28 — `Reference/training/` ramené de 7 fichiers à 5
    documents aux noms d'objet (`observation_et_actions` fusionnant observation + encodeur
    partagé/tête pointeur + grille égocentrique, `entrainement`, `metriques`, `panel_bots`
    absorbant le talon de référence) ; journal daté du training extrait en
    `archives/training_journal.md` ; 7 sources archivées en `Archives/docs/` avec
    bandeau retour ; gardes re-pointées (`VALUE_CHECKS`/`VALUE_ONLY_DOCS` du checker,
    `test_squad_obs_structure_doc`, `test_bot_panel_reference`).
  - **jeu + outils** : ✅ livré le 2026-08-28 — `Reference/jeu/` : `armes.md`, `regles_unites.md`,
    `couverture_regles.md` ; `Reference/outils/` : `configuration.md`, `tests.md`, `tests_front.md`,
    `outils_conformite.md` (fusion des 5 docs conformité) ; 11 sources archivées en `Archives/docs/`
    avec bandeau retour ; références dans le code, les tests et le corpus vivant re-pointées.
  - **infra** : ✅ livré le 2026-08-28 — `Reference/infra/` : `deploiement_nas.md`, `securite.md`,
    `acces_utilisateurs.md` (ex `Deployment_Synology`, `Security`, `USER_ACCESS_CONTROL`) ;
    corps re-vérifiés contre le code (AuthPage.tsx, api_server.py modes, PBKDF2-SHA256) ; gardes
    re-pointées (DEFAULT_DOCS du checker, tests services, security_check.sh, README).
  - **v11** : ✅ livré le 2026-08-28 — `index_v11` (état ouvert + pointeurs), `tranches_et_ruptures`
    (spec R1→R8 + T1→T7), `decisions_du_joueur` (Phase A' P1→P5), `strategie_evaluation` ;
    `lecons_de_methode` dans `Reference/training/` ; strates §9.4 pts 5/6/8 mises à jour.

---

## Ancres de ligne périmées docs V11 {#ancres}

**Traitement au fil de l'eau** (décision 2026-08-10) — tout doc modifié voit ses ancres de ligne corrigées dans la même livraison.

Le solde du 2026-08-25 (sept symboles corrigés dans 4 docs) est archivé dans
[archives/doc.md](archives/doc.md).

**Convention** : citer `def <symbole>` ou un `grep` reproductible, jamais un numéro de ligne. La passe 5, `def check_symbol_kinds` (`scripts/check_doc_references.py`), vérifie le genre déclaré ; la passe 2, `def check_links` (`scripts/check_doc_references.py`), contrôle les liens morts.

**Couverture du script** : `check_doc_references.py` passe 4 (ANCRES) couvre `Documentation/Roadmap/`, les contrats permanents, le corpus chantiers (`Documentation/Chantiers/` + `Documentation/Archives/chantiers/`) et désormais `Documentation/Reference/` (P2 livré le 2026-08-27). Passe LIENS sur tout le corpus vivant également active depuis P2.

