# Hygiène documentaire — chantier du 2026-08-10 ✅ LIVRÉ

> **Rôle.** Compte rendu du chantier de réorganisation de `Documentation/Implémentation/` mené le
> **2026-08-10**. Il explique **pourquoi** les dossiers, les bandeaux et les liens sont ce qu'ils
> sont aujourd'hui — ce que `git log` ne raconte pas.
>
> **Ce fichier ne porte aucun ordre de travail.** Il vivait dans `ROADMAP.md` §5, où il occupait
> 90 lignes sur 249 sans jamais dire par quoi commencer ; extrait ici le 2026-08-10 en application
> de la règle que le ROADMAP s'impose à lui-même (« un chantier livré passe son doc en
> `Implémenté/` »). Ordre du travail : [`../ROADMAP.md`](../ROADMAP.md).
>
> ⚠️ Ce qui **reste vif** de ce chantier n'est PAS ici mais dans `ROADMAP.md` §5 : le **contrôle
> réutilisable des liens** (à relancer après tout déplacement de doc) et la liste des
> **incohérences factuelles restantes**.

---

## Dissolution de `2_Various/`

Le dossier mélangeait 5 chantiers livrés et 1 ouvert, et sa numérotation `01_`→`06_` laissait
croire à une séquence vive. Il est **supprimé** : les 5 livrés sont en `Implémenté/`, le 06 en
`A_faire/`. Les noms de fichiers sont inchangés — les renvois « chantier 0X » du texte restent
valides. Chacun des 6 porte désormais un bandeau de statut vérifié contre le code.

Restent trois dossiers aux rôles disjoints, plus la racine (références transverses) : tableau en
tête du [ROADMAP](../ROADMAP.md).

## 497 liens relatifs morts réparés

Découvert en vérifiant les déplacements ci-dessus : **497 des 1171 liens** de
`Documentation/Implémentation/` ne pointaient nulle part. Cause unique et mécanique —
l'extraction des sections §1→§10 en sous-docs le **2026-07-28** a descendu les fichiers d'un
niveau **sans re-profondir les chemins relatifs** ; `V11_agent_rework.md` a subi le même effet en
entrant dans `1_Agent/`. Les plus touchés : `V11_agent_rework.md` (253), `V11_tranches.md` (91),
`LoS_unique_source_of_truth.md` (55), `V11_phaseA.md` (39), `squad_audit.md` (36).

Réparé par transformation déterministe (un lien n'est réécrit que si la nouvelle cible **existe**).
Vérifié le 2026-08-10 : **0 lien réellement mort** sur les 1171.

> 🔴 **La leçon, et elle vaut pour ce fichier même** : déplacer un doc d'un niveau casse
> silencieusement TOUS ses liens relatifs. Le contrôle qui le détecte est en `ROADMAP.md` §5 —
> le relancer fait partie du déplacement, pas de la passe d'après.

## `1_Agent/` n'est plus un point d'entrée concurrent

`V11_agent_rework.md` §0 s'intitulait « **À LIRE EN PREMIER** » et porte une colonne « Ordre » :
deux documents se déclaraient point d'entrée du projet. Le titre est recadré en « entrées ouvertes
de V11 », et les 4 docs V11 portent un bandeau qui répartit les rôles (le ROADMAP pour l'ordre,
eux pour le détail et l'état). La règle d'arbitrage n°3 en tête du ROADMAP tranche les désaccords
futurs.

## Fusions et suppressions (arbitrages 1 et 2 validés par l'utilisateur)

- **Fusion** `overrun.md` + `bug_pile_in_bfs_clearance_mismatch.md` →
  [`A_faire/pile_in_overrun_par_figurine.md`](../A_faire/pile_in_overrun_par_figurine.md). Les deux
  prescrivaient l'inverse l'un de l'autre ; la décision 2026-07-16 tranche pour MIGRER, le fix de
  parité BFS↔commit est conservé en §6 marqué **rejeté**. Ancres de ligne recalculées (les
  anciennes étaient fausses de >1000 lignes).
- **`10x/` supprimé** : `10x_Move_init.md` (chantier terminé) → [ici même](10x_Move_init.md) ;
  `10x_acceleration.md` réduit à ses deux axes vivants →
  [`A_faire/perf_noyau_natif_et_gzip.md`](../A_faire/perf_noyau_natif_et_gzip.md).
- **`MCTS_agent_implementation.md` supprimé**, résidu absorbé en
  [`A_faire/MCTS/MCTS_bot_final.md`](../A_faire/MCTS/MCTS_bot_final.md) **§20 bis** (MCTS à
  l'inférence, périmètre distinct de l'adversaire d'entraînement).
- **`DB_migration_prompt.md`** recâblé vers `DB_migration.md` (le `DB_migration33.md` qu'il citait
  n'existe pas).
- 20 références recâblées dans 11 fichiers (docs V11, `Documentation_audit.md`,
  `engine/w40k_core.py:6478`).
