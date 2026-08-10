# ROADMAP — source unique de l'ordre du travail

> **Rôle.** Ce fichier est la SEULE source de vérité sur « qu'est-ce qu'on fait ensuite ».
>
> **Trois dossiers, trois rôles distincts** (`2_Various/` dissous le 2026-08-10) :
>
> | Dossier | Contient | Ce qu'on y cherche |
> |---|---|---|
> | [`1_Agent/`](1_Agent/) | la spec et l'état du programme V11 (4 docs) | le **détail** d'une tranche, un piège de méthode |
> | [`A_faire/`](A_faire/) | le backlog des chantiers ouverts | le **contenu** d'un chantier à faire |
> | [`Implémenté/`](Implémenté/) | les chantiers livrés | la **référence** de conception d'un truc déjà fait |
>
> Aucun des trois ne donne l'ordre du travail — il est **ici, et nulle part ailleurs**.
>
> **Règles d'arbitrage entre docs** (établies le 2026-08-10) :
> 1. **Le code fait foi** sur fait/pas fait. Un doc contredit par le code est périmé, pas le code.
> 2. **La décision datée la plus récente tranche l'approche.** Les décisions sont recensées dans
>    `V11_agent_rework.md` §0 (tableau récapitulatif) et dans les amendements des chantiers.
> 3. **Sur les priorités, ce fichier l'emporte** sur tout autre doc, y compris `V11_agent_rework.md`
>    §0 et sa colonne « Ordre ». Sur le détail et l'état de V11, c'est l'inverse.
> 4. Conflit résiduel → section « Arbitrages ouverts » ci-dessous, tranchée par l'utilisateur.
>
> **Discipline.** Tout nouveau chantier prend une ligne ici AVANT d'ouvrir un doc de détail.
> Un chantier livré passe son doc en `Implémenté/` et sa ligne ici à jour DANS la même livraison.
>
> État vérifié contre le code le **2026-08-10** (tous dossiers balayés, exécutions à l'appui).

---

## 0. En cours — ne rien casser

- 🟢 **Run `--new` ArmageddonAgent x1** (PID vivant, `run_20260810-111734`) — c'est une **base de
  développement, PAS la mesure** (décision 2026-08-10). Ne rien lancer de cassant tant qu'il vit
  (workers `spawn` relisent le working tree). → [`1_Agent/V11_agent_rework.md`](1_Agent/V11_agent_rework.md) §0.70

## 1. Chemin critique vers la mesure de référence

Ordre imposé par les décisions du 2026-08-07 et 2026-08-10 : la mesure de référence (`x1_long`,
600 parties/bot) est **différée** jusqu'à livraison de tout ce bloc. D'ici là le projet est SANS
mesure, et c'est assumé (§0.14).

1. **P3-4 — Allocation des pertes défenseur** (= L3) → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.4 pt 4
2. **P3-5 — Pile-in / consolidation** (= L4) — **bloqué en amont** par la migration par-figurine
   du pile-in auto V11 → [`A_faire/pile_in_overrun_par_figurine.md`](A_faire/pile_in_overrun_par_figurine.md).
   Décision spatiale ⇒ top-K d'hex interdit (§9.0bis). → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.4 pt 5
3. **P3-6 — Move-after-shooting + reactive move** (= L5) → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.4 pt 6
4. **P3-8 — Optionnels à statuer** (= L7→L11) — le choix d'arme en mêlée (§0.69) est déjà acté
   en ordre 3 ; le reste (split-fire, multi-cibles charge, placement final, stratégies de
   déploiement) exige de **mesurer le regret** avant de trancher (§9.0bis). → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.4 pt 8
5. **P4 — Observation de support** (= L12, ne se livre pas seule) → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.5
6. **P5 — Validation par tranche** (protocole jamais appliqué depuis sa rédaction ; `x5_debug`,
   jamais `x1_debug`) → [`1_Agent/V11_phaseA.md`](1_Agent/V11_phaseA.md) §9.6
7. **Mesure de référence** `x1_long` — solde §0.14, §0.67, critère T6 (via §10.6) d'un coup.
8. **§0.59 — Phase 2 self-play** (`--append x1_selfplay`) — livré, JAMAIS exécuté ; le premier
   run est aussi son premier test d'intégration. → [`1_Agent/V11_agent_rework.md`](1_Agent/V11_agent_rework.md) §0.59

## 2. Capacités — seul chantier restant de la série « chantiers capacités »

- **06 — Capacités Armageddon** : 0/6 passes, tous prérequis (01→05) livrés et vérifiés.
  Passes 1-2 d'abord (12 capacités sans nouvelle structure d'état) ; FNP déjà câblé côté moteur.
  ⚠️ Risque concret : `ABILITY_SLOTS = 8` est une projection — si une entité dépasse 8 capacités
  en vigueur, le moteur lève. → [`A_faire/06_armageddon_abilities.md`](A_faire/06_armageddon_abilities.md)
- Les chantiers **01→05 sont livrés** (vérifié code, 2026-08-10) et rangés en `Implémenté/` :
  [01 embedding](Implémenté/01_ability_embedding.md) · [02 CP/battle-shock](Implémenté/02_command_points.md) ·
  [03 capacités de faction](Implémenté/03_faction_abilities.md) · [04 réserves](Implémenté/04_strategic_reserves.md) ·
  [05 purge placeholders](Implémenté/05_purge_placeholders.md). Leur section CONCEPTION reste la
  référence vivante ; leur EXÉCUTION n'a plus que valeur d'historique.

## 3. Suspendus à un jalon explicite — ne pas commencer avant

- **T7 — Unification validation de déploiement** — déclencheur : « le training tourne ».
  🔴 Le fix décrit est FAUX en l'état (mesuré 2026-07-20) ; c'est une décision de design
  (plan contraint par l'ancre), pas un bug. → [`1_Agent/V11_tranches.md`](1_Agent/V11_tranches.md) §5 T7
- **Phase B — Observation des niveaux** (= L13) — après Phase A' validée ET vérification du
  chantier LoS 3D (`combat_utils`/WASM, câblage incomplet). → [`1_Agent/V11_tranches.md`](1_Agent/V11_tranches.md)
- **É9 — Second siège + second scénario** — après entraînement bot satisfaisant ; second
  scénario écrit par l'utilisateur (décision 2026-08-02). → [`1_Agent/V11_agent_rework.md`](1_Agent/V11_agent_rework.md) §0.47
- **§10.6 volet 2 — Validation qualitative par un joueur externe** — requis pour la démo, au
  même titre que le quantitatif. → [`1_Agent/V11_eval_strategy.md`](1_Agent/V11_eval_strategy.md) §10.6
- **§10.7 — MCTS à l'inférence** — plan B anti-coups-absurdes, « à ne PAS anticiper » avant la
  mesure ; risque = latence en démo. → [`1_Agent/V11_eval_strategy.md`](1_Agent/V11_eval_strategy.md) §10.7
- **Dette d'ancre G1/G2/G4** — recensement en fiabilité dégradée ; interdiction d'ouvrir un
  chantier depuis une ligne non ✅. → [`1_Agent/V11_tranches.md`](1_Agent/V11_tranches.md) §1bis

## 4. Backlog hors chemin critique (`A_faire/`)

Prêts à démarrer sans décision produit :
- **Security étapes 3→8** (~4-6 j ; étapes 1-2 livrées, suivi à jour) → [`A_faire/Security.md`](A_faire/Security.md)
- **Tests front — reste T2b/T3a/T7 (couche A) + couches B (vitest) et C (Playwright)**
  (~10 j au total, sécable) → [`A_faire/front_test_auto.md`](A_faire/front_test_auto.md)
- **Perf `generate_compact_formation`** (½-1 j) — MESURER avant d'implémenter, gain non acquis
  → [`A_faire/perf_generate_compact_formation.md`](A_faire/perf_generate_compact_formation.md)
- **gzip/Brotli** (½ j) — à faire AVEC l'étape 5 de Security (même proxy)
  → [`A_faire/perf_noyau_natif_et_gzip.md`](A_faire/perf_noyau_natif_et_gzip.md) §1

Bloqués par une décision utilisateur :
- **Replis `unit_by_id`** — T0 (signature de `require_unit_by_id`) appartient à l'utilisateur ;
  ~4-5 sessions ensuite. ⚠️ Chiffres du doc périmés 3× : **5** implémentations du lookup
  désormais, pas 4. → [`A_faire/replis_unit_by_id_2026-08-05.md`](A_faire/replis_unit_by_id_2026-08-05.md)
- **Endless Duty** (8-13 j) — décisions produit sur les obstacles 3 (format objectifs) et
  7 (double sens de `VALUE`). → [`A_faire/Endless_duty_etat_mesure.md`](A_faire/Endless_duty_etat_mesure.md)

Lourds, à re-cadrer avant toute reprise :
- **Preview de tir sans deepcopy** (4-8 j) — meilleure spec du lot, mais touche
  `compute_unit_los` = source unique (obs RL, reward, déploiement).
  → [`A_faire/preview_tir_position_virtuelle.md`](A_faire/preview_tir_position_virtuelle.md)
- **Pile-in / Overrun 12.06 par-figurine** (3-5 j après prérequis « le gym emprunte la machine
  V11 ») — **prérequis de P3-5** (§1), donc pas vraiment optionnel.
  → [`A_faire/pile_in_overrun_par_figurine.md`](A_faire/pile_in_overrun_par_figurine.md)
- **Migration PostgreSQL** (plusieurs semaines) — spec de mars 2026 visant des modules `ai/`
  réécrits par V11 depuis : re-confronter au code avant. → [`A_faire/Database/DB_migration.md`](A_faire/Database/DB_migration.md)
- **MCTS adversaire d'entraînement** (plusieurs semaines ; P0+P1 ≈ 1-2 sem.) — après stabilité
  obs/masques. → [`A_faire/MCTS/MCTS_bot_final.md`](A_faire/MCTS/MCTS_bot_final.md)

## 5. Hygiène documentaire

### Fait le 2026-08-10 — dissolution de `2_Various/`

Le dossier mélangeait 5 chantiers livrés et 1 ouvert, et sa numérotation `01_`→`06_` laissait
croire à une séquence vive. Il est **supprimé** : les 5 livrés sont en `Implémenté/`, le 06 en
`A_faire/`. Les noms de fichiers sont inchangés — les renvois « chantier 0X » du texte restent
valides. Chacun des 6 porte désormais un bandeau de statut vérifié contre le code.

Restent trois dossiers aux rôles disjoints (tableau en tête de ce fichier).

### Fait le 2026-08-10 — 497 liens relatifs morts réparés

Découvert en vérifiant les déplacements ci-dessus : **497 des 1171 liens** de
`Documentation/Implémentation/` ne pointaient nulle part. Cause unique et mécanique —
l'extraction des sections §1→§10 en sous-docs le **2026-07-28** a descendu les fichiers d'un
niveau **sans re-profondir les chemins relatifs** ; `V11_agent_rework.md` a subi le même effet en
entrant dans `1_Agent/`. Les plus touchés : `V11_agent_rework.md` (253), `V11_tranches.md` (91),
`LoS_unique_source_of_truth.md` (55), `V11_phaseA.md` (39), `squad_audit.md` (36).

Réparé par transformation déterministe (un lien n'est réécrit que si la nouvelle cible **existe**).
Il reste **2 faux positifs** du contrôle — du texte entre parenthèses pris pour un lien, dans
`V11_tranches.md` et `V11_refactor_plan.md` — et 2 liens retirés de `Boardx10-audit.md` vers des
configs supprimées depuis.

**Contrôle réutilisable** : parcourir les liens markdown de `Documentation/Implémentation/` et
vérifier que chaque cible existe. À relancer après tout déplacement de doc.

### Fait le 2026-08-10 — `1_Agent/` n'est plus un point d'entrée concurrent

`V11_agent_rework.md` §0 s'intitulait « **À LIRE EN PREMIER** » et porte une colonne « Ordre » :
deux documents se déclaraient point d'entrée du projet. Le titre est recadré en « entrées ouvertes
de V11 », et les 4 docs V11 portent un bandeau qui répartit les rôles (ce fichier pour l'ordre,
eux pour le détail et l'état). La règle d'arbitrage n°3 en tête tranche les désaccords futurs.

### Fait le 2026-08-10 (arbitrages 1 et 2 validés)

- **Fusion** `overrun.md` + `bug_pile_in_bfs_clearance_mismatch.md` →
  [`A_faire/pile_in_overrun_par_figurine.md`](A_faire/pile_in_overrun_par_figurine.md). Les deux
  prescrivaient l'inverse l'un de l'autre ; la décision 2026-07-16 tranche pour MIGRER, le fix de
  parité BFS↔commit est conservé en §6 marqué **rejeté**. Ancres de ligne recalculées (les
  anciennes étaient fausses de >1000 lignes).
- **`10x/` supprimé** : `10x_Move_init.md` (chantier terminé) → [`Implémenté/`](Implémenté/10x_Move_init.md) ;
  `10x_acceleration.md` réduit à ses deux axes vivants →
  [`A_faire/perf_noyau_natif_et_gzip.md`](A_faire/perf_noyau_natif_et_gzip.md).
- **`MCTS_agent_implementation.md` supprimé**, résidu absorbé en
  [`A_faire/MCTS/MCTS_bot_final.md`](A_faire/MCTS/MCTS_bot_final.md) **§20 bis** (MCTS à
  l'inférence, périmètre distinct de l'adversaire d'entraînement).
- **`DB_migration_prompt.md`** recâblé vers `DB_migration.md` (le `DB_migration33.md` qu'il citait
  n'existe pas).
- 20 références recâblées dans 11 fichiers (docs V11, `Documentation_audit.md`,
  `engine/w40k_core.py:6478`).

### Incohérences factuelles restantes (non traitées, aucune ne bloque)

- **`obs_size` : trois valeurs en circulation** — `Implémenté/01_ability_embedding.md` annonce
  14609/14615, la config ArmageddonAgent porte **16659** (3 occurrences), et sa `justification`
  raconte encore la lignée 20780 → 20727. La valeur vraie à HEAD est **16659** (vérifiée par
  exécution le 2026-08-08, revérifiée le 2026-08-10).
- `justification` de `bot_eval_final_normal` dit « x1 (10 000 episodes) » alors que
  `x1.total_episodes` = **50 000**.
- `A_faire/Endless_duty_etat_mesure.md` affirme que `config/agents/CoreAgent/` n'existe plus —
  **il existe**.
- Bandeaux et chiffres périmés listés en `1_Agent/V11_agent_rework.md` §0bis (l.3713-3735),
  signalés et volontairement non corrigés depuis le 2026-07-20.
- `ABILITY_SLOTS = 8` est une projection non mesurée ; le chantier 06 la rendra mesurable (§2).
