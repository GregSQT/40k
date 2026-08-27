# Endless Duty — spec du mode, état mesuré, obstacles restants

> **OBJET** : document de référence unique du mode survie « Endless Duty » — spec cible (V1 recalée sur ce que le code a tranché), inventaire mesuré de ce qui existe, obstacles restants et décisions attendues.
> **Chantier OUVERT.** L'état des chantiers fait foi dans `Documentation/Roadmap/`, jamais ici → [moteur.md#endless-duty](../../Roadmap/moteur.md#endless-duty).
> Sources absorbées (destinées à `Documentation/Archives/docs/` avec bandeau retour) : `Endless_duty.md` (spec fonctionnelle V1, 2026-03) et `Endless_duty_etat_mesure.md` (état mesuré 2026-07-29, complété 2026-08).
> Les valeurs de tuning (budgets, coûts, bonus) ne sont PAS recopiées ici : la source de vérité est `config/scenario_endless_duty.json` et `config/endless_duty/`.

---

## 1. Le mode et sa boucle

`Endless Duty` est un mode survie solo orienté high score. Le joueur contrôle une escouade Space Marines (1 à 3 slots) et défend **un objectif unique** contre des vagues Tyranides de budget croissant. Objectif : tenir le plus grand nombre de vagues possible.

Boucle :

1. Lancer une vague Tyranide (spawn en bordure de plateau).
2. Résoudre le combat sur la carte.
3. Fin de vague : créditer des points de réquisition.
4. Phase inter-vague : réquisition (évolution des slots, refit d'équipement).
5. Recommencer avec une vague plus difficile.

Défaite si : escouade détruite, ou objectif contrôlé par les Tyranides `loss_counter_threshold` fins de round consécutives (cf. §2.5).

Le Leader est l'avatar principal du joueur.

---

## 2. Spec cible (V1 recalée sur le code)

Chaque point où la spec V1 d'origine divergeait du code livré est corrigé ici, avec la preuve. Le code tranche.

### 2.1 Escouade : trois slots `leader` / `melee` / `range`

- Escouade limitée à **3 slots** : `leader`, `melee`, `range`.
  ⚠️ La spec initiale nommait le troisième slot « Heavy/Special » ; le code a tranché `range` — preuve : `def _slot_profile_to_unit_type` dans [`services/endless_duty_runtime.py`](../../../services/endless_duty_runtime.py) (mappe `leader`/`melee`/`range` vers les fiches `Leader*`/`Melee*`/`Range*`) et les trois fichiers `config/endless_duty/{leader,melee,range}_evolution.json`.
- Slot `leader` (unique) : seul autorisé à monter en grade. Profils du catalogue vif : `config/endless_duty/leader_evolution.json` → `catalog` (Sergeant → Lieutenant → Captain → CaptainGravis → CaptainTerminator au moment de la consolidation).
- Slot `melee` : profils corps à corps (`config/endless_duty/melee_evolution.json` → `catalog`).
- Slot `range` : profils de tir (`config/endless_duty/range_evolution.json` → `catalog`).
- Règles de loadout : `rules.package_replaces_all` / `package_blocks_extras` dans chaque fichier d'évolution ; les picks d'armes (`melee`/`ranged`/`secondary`) sont résolus par `def _resolve_slot_pick_override` et appliqués par `def _apply_slot_picks_to_unit` (`services/endless_duty_runtime.py`).

**Configuration de départ** — corrigée : la spec V1 disait « le joueur commence avec 2 unités, slot 3 verrouillé, débloqué en boutique ». Le code a tranché autrement : le scénario ne déclare **qu'une unité joueur 1** (le leader), et les autres slots se débloquent **par palier de vague**, pas par achat de déverrouillage (cf. §2.4). Preuve : clé `units` de [`config/scenario_endless_duty.json`](../../../config/scenario_endless_duty.json) (une seule entrée, `player: 1`) et absence de toute clé `unlock_slot3_cost` dans `endless_duty.economy`. Le leader est reconstruit au démarrage par `def initialize_endless_duty_state` selon le profil et le loadout de départ de `leader_evolution.json` (`starter_loadout_id`).

### 2.2 Fiches d'unités dédiées ED

Décision conservée : les profils standards restent inchangés pour PvE/PvP ; Endless Duty utilise des fiches dédiées, avec des règles de combat alignées sur l'unité de production déléguée (pas de fork gameplay), pour permettre une économie différenciée.

**Convention corrigée** : la spec V1 prévoyait un suffixe `*_ED` (ex. `CaptainPowerFistPlasmaPistol_ED`). Le code a retenu un **dossier dédié + préfixe de slot** : [`frontend/src/roster/spaceMarine/units/endlessDuty/`](../../../frontend/src/roster/spaceMarine/units/endlessDuty/index.ts), fiches `Leader*` / `Melee*` / `Range*` (ex. `LeaderSergeant`, `MeleeTerminator`, `RangeHellblaster`). Preuve : aucune classe suffixée `_ED` n'existe dans le dépôt ; `def _slot_profile_to_unit_type` construit les noms par préfixe. La liste vive des fiches est le dossier lui-même (et `_ED_UNIT_TYPES` dans le test signet, cf. §3.4).

Chaque fiche délègue ses champs à son unité de production (ex. `static VALUE = Intercessor.VALUE` ; références statiques `X.FIELD` résolues par `def _resolve_numeric_unit_field`). Règle anti-drift conservée : toute modification d'un profil standard doit être répercutée sur sa fiche ED (stats/règles/armes), sauf ce qui est explicitement économique.

Résidu connu : les fiches ED ont `FACTION_KEYWORDS` présent mais **vide** — elles n'appartiennent à aucune faction, donc aucune capacité de faction (Oath of Moment, etc.) ne les vise. Gardé sous test (cf. §4, obstacle 5).

### 2.3 Économie de réquisition (VALUE-driven, modèle capital)

Décisions verrouillées (ex-§19.1 de la spec), **implémentées** — les valeurs vives sont dans `config/scenario_endless_duty.json` → `endless_duty.economy` :

- Monnaie : points de réquisition (`economy.currency`).
- Crédits de fin de vague : `floor(alpha × VALUE_ennemie_tuée_sur_la_vague) + wave_clear_bonus + no_consumable_bonus + objective_hold_bonus` — formule et constantes dans `economy` (`credits_formula`, `credits_alpha_on_kill_value`, `wave_clear_bonus`, `no_consumable_bonus`, `objective_hold_bonus`) ; implémentation : `def _compute_wave_credits` (`services/endless_duty_runtime.py`).
- Recrutement d'une unité : `coût = VALUE(unité cible)` (`recruit_cost_formula`).
- Upgrade de modèle / variante d'arme : `coût = VALUE(cible) − VALUE(courante)`, delta signé (`upgrade_cost_formula`, `weapon_variant_cost_formula`).
- **Modèle « capital de réquisition »** (`economy.capital_model`) : le joueur cumule un capital total sur la run ; chaque configuration d'escouade correspond à un investissement ; `disponible = capital_total − investi`. Entre vagues, refit autorisé (armures + armes) : passer vers plus cher consomme du capital, vers moins cher en libère. Ce n'est **pas** une revente (`is_resale: false`) : l'équipement retiré est rendu au pool et le capital est recalculé via le nouveau total investi. Champs d'état : `capital_total_field` / `invested_total_field` / `available_field` du `capital_model`.
- Commit inter-vague : `def commit_inter_wave_requisition` valide la configuration demandée, débite le capital et déclenche le spawn de la vague suivante.
- Principe d'immersion conservé : uniquement des unités, armes et variantes existantes dans le roster du jeu ; aucun combo « hors catalogue ».
- Achats possibles uniquement entre les vagues ; pas de limite « 1 upgrade max par vague ».

**Séparation valeur de combat / coût** (décision issue de l'obstacle 7) : `VALUE` reste la **valeur de combat** (référence de la force d'usure, V11 §9.8) ; le coût de réquisition vit dans un champ distinct `REQUISITION_COST`, écrit par `def _apply_slot_picks_to_unit`. Valeurs de départ du leader : `economy.starting_leader_combat_value` / `economy.starting_leader_requisition_cost`. Preuve : test `test_obstacle_7_solved_value_and_requisition_cost_are_separate` du signet (§3.4).

⚠️ **Constat de câblage (mesuré à la consolidation)** : côté backend, le décompte du capital est en `VALUE` — `def initialize_endless_duty_state` et `def commit_inter_wave_requisition` calculent l'investi via `def _sum_units_value`, qui somme `VALUE` ; `REQUISITION_COST` est écrit sur chaque unité mais n'a **aucun lecteur** (grep : seules écritures dans `services/endless_duty_runtime.py` + déclarations statiques des fiches). Les coûts de picks du catalogue (`base` + `cost` par row) n'entrent donc pas dans le décompte backend, alors que le frontend projette l'investi **depuis ces coûts catalogue** (`resolveDraftInvestedTotal` dans `frontend/src/components/BoardWithAPI.tsx`). Deux bases de calcul différentes front/back — point de cohérence à trancher à la reprise (cf. §5).

**Purgé — première économie V1** : la formule `points_vague = 6 + floor(vague × 1.5)`, ses bonus `+3`/`+2` et la table de prix fixes (déblocage slot 3 à 18 points, Sergent 12, Capitaine 24, etc.) ont été remplacés par l'économie VALUE-driven ci-dessus, dans la spec elle-même (section « Decisions V1 lock ») puis dans le code.

### 2.4 Déblocage des slots par palier de vague

Décision verrouillée (ex-§19.1.b), **présente en config** : chaque slot devient utilisable à partir d'une vague donnée — `config/scenario_endless_duty.json` → `endless_duty.wave_unlock_rules` (au moment de la consolidation : `leader` vague 1, `range` vague 10, `melee` vague 15). Avant le palier, le slot est visible mais verrouillé en réquisition ; au palier atteint, il devient achetable immédiatement entre vagues (coût = recrutement de l'unité, cf. §2.3 — il n'existe **pas** de frais de déverrouillage distinct).

**Corrigé** : la spec verrouillait aussi `unlock_slot3_cost = 10 crédits (fixe)` ; cette clé n'existe pas dans `endless_duty.economy` — le déverrouillage par vague l'a remplacée.

### 2.5 Objectif unique et condition de défaite

- **Un objectif fixe unique**, issu de la zone de terrain marquée `"objective": true` du fichier [`config/board/44x60x5/terrain/terrain-endless-duty.json`](../../../config/board/44x60x5/terrain/terrain-endless-duty.json) (zone `objective_center`, petit polygone au centre du plateau). C'est la résolution de l'obstacle 3 : le format historique « `objectives` + `objective_pool` + tirage par run » a été supprimé du scénario ; le tirage aléatoire d'objectif par run a été **abandonné** au profit d'un objectif fixe. Preuve : test `test_obstacles_1_and_3_ed_scenario_now_uses_v11_format` (exactement 1 zone objectif exigée).
- Le joueur se déplace librement ; il n'est pas statique. Les ennemis arrivent en vagues avec variation des points d'entrée (§2.6).
- États de l'objectif en fin de round : `SM_CONTROL` / `TYR_CONTROL` / `NEUTRAL` (`def _objective_state_from_control_data`, sur la base de `calculate_objective_control` de [`engine/game_state.py`](../../../engine/game_state.py)).
- Compteur de perte : incrémenté uniquement si fin de round = `TYR_CONTROL`, remis à zéro sur `SM_CONTROL` ou `NEUTRAL`, défaite immédiate au seuil — règles et seuil dans `endless_duty.objective_rules` (`loss_counter_threshold`, `loss_counter_increment_when`, `loss_counter_reset_when`) ; implémentation : `def _update_objective_loss_counter`, qui évalue une fois par tour nouveau, à la phase `command` du joueur 1 (approximation « fin du round précédent » retenue par le code). ⚠️ Jamais vu s'incrémenter en exécution réelle (cf. §6).
- Conditions de défaite : escouade détruite, ou seuil du compteur atteint.

### 2.6 Vagues : budget, déblocage des menaces, spawn en bordure

**Budget de menace.** La difficulté monte via un budget par vague, pas seulement par le nombre d'unités. Principe clé conservé : le coût de menace d'une unité Tyranide est **strictement sa `static VALUE` existante** (source de vérité : `frontend/src/roster/tyranid/units/*.ts`) ; aucune table de coût parallèle. Le générateur (`def _compose_enemy_wave`) compose la vague sous contrainte `somme(VALUE) <= budget` (mode et tolérance : `endless_duty.budget_mode`, `budget_soft_cap_pct`).

Valeurs vives — ne pas recopier, lire `config/scenario_endless_duty.json` → `endless_duty` :
- `budget_by_wave` : table des budgets vagues 1-20. ⚠️ La table chiffrée de la spec V1 (18, 24, 30, …, 266) est **périmée** : la config vive diffère dès la vague 1.
- `budget_growth_after_wave_20` : croissance au-delà de la vague 20 (delta linéaire par vague).
- `wave_spike` : le « mini-spike toutes les 5 vagues (+10 %) » de la spec est **neutralisé** en config (`budget_multiplier` à 1.0 au moment de la consolidation).
- `spawn_unlock_rules` : paliers de déblocage des menaces par VALUE (vagues 1-4 : petites unités ; 5-9 : palier intermédiaire ; 10+ : menaces lourdes autorisées) — implémentation `def _get_unlocked_enemy_unit_types`.
- Spawns imposés par vague : [`config/endless_duty/wave_forced_spawns.json`](../../../config/endless_duty/wave_forced_spawns.json) (`def _forced_wave_entries_for_index`).

Les profils de composition de la spec (Swarm / Rush / Mix / Elite pressure / Boss + swarm…) restent des gabarits valables pour les presets QA, mais leurs arithmétiques chiffrées étaient liées à la table de budget périmée — les recomposer depuis `budget_by_wave` vif.

**Spawn ennemi** (ex-§19.2.b), **implémenté et conforme à la config** — `endless_duty.enemy_spawn_rules` :
- spawn uniquement sur les hex de bord (`mode: random_board_edge_hexes`), bords candidats `north`/`south`/`east`/`west` ;
- exclusion des hex d'objectif, distance minimale à l'objectif, distance minimale entre spawns d'une même vague, nombre max de tentatives par unité (`max_retries_per_unit`) — implémentation `def _build_and_place_enemy_units`, `def _random_edge_hex`.
- ED ne redéfinit **pas** les règles de combat : uniquement orchestration vagues + spawn.

### 2.7 Consommables (spec verrouillée, pipeline moteur ABSENT)

Spec verrouillée (ex-§19.3) et **déjà en config** — `config/scenario_endless_duty.json` → `endless_duty.consumables` : catalogue (`med_stim` soin, `adrenal_stim` mobilité, `targeter_stim` précision, `armor_stim` sauvegarde — effets et coûts de base dans `items`), achat uniquement entre vagues, plafond de stock par type, plafond d'usage global par vague, max par unité et par round, escalade de coût par type (multiplicateurs plafonnés), non-stackable pour un même buff, buffs de types différents cumulables.

**État réel : conception moteur absente, assumée.** Aucune occurrence de `consumable` dans `engine/`, `ai/` ni `frontend/src` ; `def _compute_wave_credits` le dit en commentaire (« V1: no consumables pipeline yet in engine => treat as unused for scoring ») — le bonus `no_consumable_bonus` est donc toujours acquis. À concevoir, pas à réparer.

Note d'équilibrage conservée : les consommables doivent rester des outils de clutch, moins rentables sur la durée que les upgrades permanents.

### 2.8 Scoring et télémétrie (spec, non implémenté)

Score de run (cible V1) : `score_run = (vague_max × 100) + bonus_mastery + bonus_objective`, avec `bonus_mastery = 15 × nb_vagues_sans_consommable` et `bonus_objective = 10 × nb_vagues_objectif_non_contesté`. Métagame : leaderboard local / high score run-to-run.

Télémétrie minimale cible : `wave_reached`, `final_score`, `points_earned_total`, `points_spent_total`, `consumables_used_total`, `leader_model_end_run`, vague de déblocage des slots.

**État réel** : aucun calcul de score dans `services/endless_duty_runtime.py` (0 occurrence de `score`). Spec cible, à implémenter.

### 2.9 Journalisation : `--step` source unique

Décision conservée : pas de format de log parallèle dédié ED ; le flux `--step` existant est la source de vérité unique. Extension par **champs optionnels** uniquement (événements crédits : `credits_delta`, `credits_balance_before/after`, `credits_reason`, `wave_index` ; événements achats : `purchase_type`, `purchase_item_id`, `purchase_item_from/to`, `purchase_cost`, `purchase_delta` — négatif possible en refit vers moins cher). Les parseurs existants doivent continuer à fonctionner sans ces champs ; l'agrégateur ED ignore proprement les steps sans métadonnées éco. Liste vive des champs : `endless_duty.logging.optional_fields` du scénario. Journal interne d'événements ED : `def _append_ed_log`.

### 2.10 UI de réquisition inter-vague (spec ; implémentation partielle inline)

Fenêtre « Requisition » entre vagues, affichant en permanence le modèle capital (`Capital total` / `Investi projeté` / `Disponible projeté` / delta net). Deux colonnes : cartes de slots (`leader`/`melee`/`range` — unité actuelle, VALUE, loadout, statut unlock) et builder par onglets (`Profile` / `Armor` / `Weapons` / `Consumables`), chaque option affichant VALUE cible, delta signé, badge de lock par vague, affordabilité. Comportements obligatoires : recalcul live sans roundtrip, commit impossible si disponible projeté < 0, options lockées visibles non sélectionnables, confirmation finale avec résumé des deltas. Edge cases : slot non débloqué en draft → erreur bloquante ; option retirée du roster → « invalid selection » + reset local ; capital négatif après mise à jour serveur → refuser le commit et recharger ; double-clic Apply → bouton désactivé + token d'idempotence.

Composants proposés (`RequisitionModal` et sous-composants), type d'état `SlotKey = "leader" | "melee" | "range"`, contrat de calcul frontend (`investedDraft` / `availableDraft` / `optionDelta`) : conservés comme spec de départ.

**État réel** : `RequisitionModal` n'existe pas dans `frontend/src` (0 hit), mais une UI inter-vague **inline** existe dans [`frontend/src/components/BoardWithAPI.tsx`](../../../frontend/src/components/BoardWithAPI.tsx) : affichage capital total / investi projeté / disponible projeté, draft de profils et de picks par slot construit depuis les trois configs d'évolution importées, calcul local `resolveDraftInvestedTotal`, validation d'affordabilité et commit. Le câblage bas niveau vit dans [`frontend/src/hooks/useEngineAPI.ts`](../../../frontend/src/hooks/useEngineAPI.ts) (état `endlessDutyState`, action `endless_duty_commit`). Rendu jamais validé (cf. §6) ; base de calcul de l'investi divergente du backend (cf. §2.3).

### 2.11 Bonus de plateau aléatoires (V1.1, désactivés)

Anti-monotonie : bonus rares à ramasser (cache de réquisition, soin, précision, mobilité), max 1 actif, jamais sur l'objectif, durée de vie courte, effets modestes, pas de stacking ni de drop garanti. Décision conservée : V1 sans bonus ; activation en V1.1 derrière flag. La config vit déjà : `endless_duty.bonuses` (`enabled: false`, `release_target: "v1.1"`).

### 2.12 Modèle time-to-maturation (méthode de tuning)

Méthode conservée pour piloter la vitesse de progression (« difficulty profile » = vitesse économique fast/standard/slow, PAS force de l'IA ; la menace reste progressive dans tous les cas) :

- Coût de maturation d'un build cible : `C_total = somme des deltas VALUE des slots` (le levier « coût de déverrouillage de slot » de la spec n'existe plus, cf. §2.4).
- Crédits par vague : `credits_w = floor(alpha × B_w) + bonus_w − sink_w` ; maturation atteinte à la première vague `N` telle que `credits_cumulés(N) >= C_total`.
- Leviers : `alpha` (= `economy.credits_alpha_on_kill_value`, levier n°1), bonus de fin de vague, sinks consommables.
- Cible V1 profil standard : maturation vers la vague 10-12 ; fast 8-9 ; slow 13-15.
- Procédure : fixer le build cible → choisir la vague de maturation → simuler les crédits cumulés sur 20 vagues → ajuster `alpha` puis les bonus/sinks.
- Validation télémétrie : écart médian `wave_maturation_observée` vs cible ≤ 1,5 vague ; surveiller snowball et stagnation.

### 2.13 Protocole de tests IA vs IA (achats scriptés)

Pour tuner l'économie sans boucle manuelle : combat IA joueur vs IA tyranide, achats inter-vagues appliqués par une politique déterministe, aucune modification des règles de combat.

- Trois policies : `GreedyPower` (upgrades chers d'abord), `Balanced` (répartit sur les slots), `Survivor` (survie court terme, consommables). Les lancer en parallèle sur les mêmes seeds.
- Règles d'achat script : recrutement `= VALUE(unité)`, upgrade `= max(0, VALUE(cible) − VALUE(courante))`, consommables `= coût de base × escalade`. Tie-break : légalité → ratio gain/coût → coût le plus bas → ordre alphabétique stable.
- Boucle : init (seed, policy, config éco) → vague IA vs IA → crédits → script d'achat → achats sous contraintes → vague suivante → stop sur défaite ou vague max → métriques.
- Métriques par run (seed, policy, `wave_reached`, `wave_maturation`, `final_score`, crédits gagnés/dépensés/restants, consommables, vagues de déblocage, unités finales par slot) et par vague (budget, crédits, valeur d'armée des deux camps, état objectif).
- Plan : ≥ 30 seeds par policy, mêmes seeds entre presets éco.
- Gates : maturation médiane dans la fourchette du preset ; écart interquartile de `wave_reached` non excessif ; taux de défaite avant vague 3 sous seuil ; anti-snowball (si > 20 % des runs dépassent la vague de maturation cible de +4, réduire `alpha` ou augmenter les sinks).
- Actions correctives : maturation trop rapide → baisser `alpha`, renchérir les consommables ; trop lente → l'inverse ; variance trop forte → lisser les spikes de budget, renforcer les rewards de maîtrise.
- Limites : ne mesure pas le ressenti joueur ; à compléter par playtests humains.

### 2.14 Non-goals V1, priorités d'équilibrage, critères de succès

Non-goals V1 : pas de traversal/extraction multi-objectifs, pas de rotation de nombreuses maps, pas d'arbre de talents complexe (V2/V3 après stabilisation du cœur survie).

Priorités d'équilibrage : 1) escouade globale vs vagues ; 2) éviter les stratégies dominantes absolues ; 3) progression satisfaisante même sans consommables.

UX minimale : numéro de vague, points disponibles, menace de la prochaine vague, slots et rôles, effets actifs des buffs ; boutique lisible par catégories.

Critères de succès V1 : boucle comprise en < 2 runs ; score piloté par la maîtrise (pas uniquement RNG) ; runs rejouables ; tuning stable sur les 10-15 premières vagues ; taux de « défaite avant vague 3 » < 25 % sur panel interne. Smoke QA : run complète jusqu'à vague 5 sans crash, réquisition, déblocages de slots, score, défaite par objectif.

---

## 3. Ce qui existe en code (mesuré)

### 3.1 Briques présentes

| Brique | Où | État |
|---|---|---|
| Moteur du mode | [`services/endless_duty_runtime.py`](../../../services/endless_duty_runtime.py) | budget de vague, spawn en bordure, compteur de perte d'objectif, économie inter-vague, évolution de slots |
| Câblage API | [`services/api_server.py`](../../../services/api_server.py) : appel de `initialize_endless_duty_state` après `engine.reset()`, garde `inter_wave_pending` sur la route `execute_ai_turn`, actions `endless_duty_status` / `endless_duty_commit` | présent |
| Scénario | [`config/scenario_endless_duty.json`](../../../config/scenario_endless_duty.json) | format V11 (`board_ref` + `terrain_ref`), cf. obstacles 1 et 3 soldés |
| Données d'évolution | `config/endless_duty/{leader,melee,range}_evolution.json`, `wave_forced_spawns.json` | présentes |
| Fiches d'unités | `frontend/src/roster/spaceMarine/units/endlessDuty/` | présentes, complétées (obstacle 5 soldé ; résidu `FACTION_KEYWORDS` vides) |
| Terrain dédié | `config/board/44x60x5/terrain/terrain-endless-duty.json` | présent, 1 zone objectif unique |
| Interface | [`SharedLayout.tsx`](../../../frontend/src/components/SharedLayout.tsx) (bouton `/game?mode=endless_duty`), [`Routes.tsx`](../../../frontend/src/Routes.tsx), [`useEngineAPI.ts`](../../../frontend/src/hooks/useEngineAPI.ts) (`endlessDutyState`, commit de réquisition), [`useGameConfig.ts`](../../../frontend/src/hooks/useGameConfig.ts) (clé `endless_duty` → chemin du scénario), [`BoardWithAPI.tsx`](../../../frontend/src/components/BoardWithAPI.tsx) (UI de réquisition inter-vague inline, cf. §2.10) | présent, rendu jamais validé |
| Base | `config/users.db` : table `game_modes` (code `endless_duty`) + autorisations `profile_game_modes` | présent (ids et profils = donnée runtime, lire la base, ne pas recopier) |

Il y a donc un chantier réel à reprendre, pas une coquille vide.

### 3.2 Comment l'état a été mesuré (2026-07-29)

Sonde jetable **hors dépôt**, rejouant le chemin exact de `POST /game/new` sans la couche HTTP/auth :

`def initialize_test_engine` (scénario ED, agent forcé) → `engine.reset()` → `def initialize_endless_duty_state` → `def handle_endless_duty_post_action` / `def spawn_next_wave_for_current_index` / `def commit_inter_wave_requisition` → `def _build_observation` → `def execute_ai_turn` (moteur).

À chaque erreur : noter, boucher au minimum, relancer. **7 obstacles** ont été franchis avant d'obtenir une boucle de jeu qui tourne. Tous les bouchons ont ensuite été retirés (dépôt propre) — aucun n'a été livré. Ce qui n'a pas été atteint est signalé **non exploré** (§6), pas sain.

### 3.3 Jusqu'où la boucle tourne (exécuté, pas déduit)

Une fois les 7 obstacles bouchés temporairement, la mesure a constaté :

- `initialize_endless_duty_state` va au bout : leader reconstruit, vague 1 composée sous budget et posée en bordure de plateau ;
- 12 `advance_phase` d'affilée : phases `move`/`shoot`/`charge` s'enchaînent sur 3 tours sans erreur ;
- sérialisation d'état API (`def _game_state_for_json` + `def make_json_serializable`) : OK ;
- fin de vague : `handle_endless_duty_post_action` détecte le nettoyage, crédite et passe `inter_wave_pending` à vrai ;
- réquisition inter-vague : `commit_inter_wave_requisition` accepte un achat de slot `range` au palier, débite le capital et déclenche le spawn de la vague suivante ;
- observation et tour IA : construits et joués une fois l'obstacle 7 contourné — `execute_ai_turn` rend une activation valide.

Le mode est donc plus proche qu'il n'y paraît : la boucle de jeu, l'économie et le cycle de vagues fonctionnent. Ce qui bloquait, c'étaient sept trous en amont — dont cinq ont été soldés depuis (§4).

### 3.4 Le signet exécutable

[`tests/unit/services/test_endless_duty_is_broken.py`](../../../tests/unit/services/test_endless_duty_is_broken.py) — des tests qui **affirment l'état constaté** (obstacles encore ouverts ET résolutions acquises), avec les valeurs exactes mesurées.

Forme retenue : affirmer l'état constaté, pas `xfail(strict=True)`. Deux raisons : (1) la vérification large de l'utilisateur doit rester exploitable — un rouge durable finit ignoré ; ces tests sont verts tant que l'état décrit tient ; (2) un `XPASS(strict)` signale « un truc a changé » sans dire lequel — ici chaque assertion nomme son obstacle et renvoie à ce document dans son message d'échec. Le jour où quelqu'un bouche un trou restant (ou fait régresser une résolution), le test correspondant passe au rouge : c'est le signal de mise à jour.

Voir aussi [`tests/unit/services/test_endless_duty_value_baseline.py`](../../../tests/unit/services/test_endless_duty_value_baseline.py) : contre-épreuve que `def _replace_units_for_player` (rappel de `build_units_cache` à chaque vague, pour les deux joueurs) ne réécrit pas la référence `value_at_start` de l'autre joueur — sans ce verrou, les pertes déjà subies du joueur 1 disparaissaient de l'observation à chaque vague.

---

## 4. Les 7 obstacles de la mesure — état courant

Numérotation historique conservée (les tests du signet la citent). **Nature** : `DONNÉE` = remplir une donnée existante · `CODE` = écrire/corriger du code · `CONCEPTION` = décision produit à prendre avant de coder. État vérifié au signet (relancé vert le 2026-08-28).

### Obstacle 1 — `CODE`/`DONNÉE` · le scénario n'était plus localisable — ✅ SOLDÉ

Mesuré : `def _resolve_board_dir` (`engine/game_state.py`, format V11) n'accepte un scénario que sous `config/board/<board>/scenario/` OU avec une clé `board_ref` ; le scénario ED était resté à la racine de `config/` sans `board_ref`.

Résolution livrée : `board_ref` déclaré dans `config/scenario_endless_duty.json` (plateau actif `44x60x5`), scénario resté à la racine (chemin porté par `ED_SCENARIO_DEFAULT` dans `services/endless_duty_runtime.py` et par la clé `endless_duty` de `useGameConfig.ts`). Gardé par `test_obstacles_1_and_3_ed_scenario_now_uses_v11_format`.

### Obstacle 2 — `DONNÉE` · le `wall_ref` pointe un plateau non jouable — 🔴 OUVERT (½ j)

`"wall_ref": "walls-11.json"` n'existe que sous `config/board/44x60x10/walls/`, et `44x60x10` n'est pas dans `BOARD_PATH_MAP` (`services/api_server.py` : seuls `x1` et `x5_44x60`). Le plateau actif (`config/board/44x60x5/walls/`) ne propose que `walls-33`, `walls-mc1`, `walls-mc2`, `walls-none`.

**Ce qu'il faut faire** : choisir (ou créer) un jeu de murs pour un plateau jouable — c'est un **choix de level design**, pas une substitution mécanique. Gardé par `test_obstacle_2_ed_wall_ref_targets_wrong_board`.

### Obstacle 3 — `CONCEPTION` · les objectifs du mode n'avaient plus de format — ✅ SOLDÉ (décision prise)

Mesuré : le mode était bâti sur UN objectif de 7 hexes tiré au sort par run dans un `objective_pool` de 5 ; ce format scénario (`objectives`) avait été supprimé au profit des zones de terrain `"objective": true`. Branché sur un terrain générique, le moteur produisait 5 objectifs de 1 730 à 3 000 hexes — sans rapport avec la géométrie « un point à tenir ».

Décision prise (en code) : **objectif fixe unique**, via un terrain dédié `terrain_ref: terrain-endless-duty.json` contenant exactement une zone objectif compacte au centre (`objective_center`) ; clés `objectives` / `objective_pool` / `objective_selection` supprimées du scénario — le tirage par run est abandonné. Le point de départ du leader (`ED_START_LEADER_COL` / `ED_START_LEADER_ROW`, `services/endless_duty_runtime.py`) est posé sur cette zone. Gardé par `test_obstacles_1_and_3_ed_scenario_now_uses_v11_format`.

### Obstacle 4 — `CODE` · aucune unité ennemie à `reset()` — 🔴 OUVERT (1 j)

Le scénario ne déclare qu'une unité, joueur 1. Or `engine.reset()` construit une observation qui exige les deux joueurs (`value_at_start[2]` requis par `def build_squad_observation`, `engine/observation_builder.py`), et `api_server.py` reconnaît lui-même l'ordre (« Endless Duty spawns tyranids after reset ») : l'enchaînement `reset()` → observation → `initialize_endless_duty_state()` est **structurellement inversé** — toujours vrai dans `services/api_server.py` au moment de la consolidation.

**Ce qu'il faut faire** : soit déclarer une garnison de vague 1 dans le scénario, soit spawner la vague avant la première construction d'observation. C'est un choix d'architecture d'initialisation, pas une ligne de donnée. Gardé par `test_obstacle_4_ed_scenario_declares_no_player_2_units`.

### Obstacle 5 — `DONNÉE` · les fiches endlessDuty étaient incomplètes — ✅ SOLDÉ (1 résidu)

Mesuré : les 18 fiches du dossier `endlessDuty/` n'avaient pas d'`ILLUSTRATION_RATIO` (exigé par `def _build_unit_from_registry`).

Résolution livrée : toutes les fiches ont désormais la clé (valeur directe ou référence statique résolue par `def _resolve_numeric_unit_field`). Requalifié au passage : `MeleeTerminator` sans armement à distance est **intentionnel** (pur mêlée) — le runtime lit `RNG_WEAPONS` et gère la liste vide (`selected_rng_weapon_index = None`). Gardé par `test_obstacle_5_ed_datasheets_have_illustration_ratio` et `test_obstacle_5b_melee_terminator_has_empty_ranged_weapons`.

**Résidu ouvert** : `FACTION_KEYWORDS` est présent (posé `[]` par le parseur depuis le chantier 03, 2026-08-05 — même convention que `UNIT_KEYWORDS`) mais **vide** sur toutes les fiches ED : elles n'appartiennent à aucune faction, donc aucune capacité de faction (Waaagh!, Oath of Moment) ne les vise. À compléter avec le mot-clé de l'unité de production déléguée ; le signet asserte l'état vide et signalera le changement.

### Obstacle 6 — `CODE` · `_build_unit_from_registry` était un doublon qui avait dérivé — ✅ SOLDÉ

Mesuré : `def _build_unit_from_registry` (`services/endless_duty_runtime.py`) réimplémente à la main `def _build_enhanced_unit` (`engine/game_state.py`) et n'avait pas suivi la migration V11 : 14 champs absents de sa sortie (`BASE_SHAPE`, `BASE_SIZE`, `MODEL_HEIGHT`, `orientation`, `level`, `deployed_on_turn`, `battle_shocked`, `hidden`, `hidden_models`, `hideable`, `CAN_LEAD`, `_UNIT_RULES_OWN`, `_ATTACHED_RULE_GROUPS`, `_wdc_def_key`) et trois conversions subhex manquantes (MOVE et portées × `inches_to_subhex`, socle non résolu) — unités 5× trop lentes et courtes de portée.

Résolution livrée : le builder émet les champs requis par `def build_units_cache` et applique les conversions subhex (`def _scale_weapons_rng` ; socle via `def _resolve_numeric_unit_field`). La forme retenue est l'**alignement en place gardé par test** (le builder reste distinct de `_build_enhanced_unit`, qu'il cite comme référence) — la recommandation de la mesure (déléguer à la fabrique canonique) n'a pas été retenue ; le risque de dérive est couvert par le signet : `test_obstacle_6_ed_unit_builder_emits_engine_required_fields` (champs + MOVE/RNG en subhex sur Termagant). Le même contrat de conversion est gardé côté picks d'armes par `test_apply_slot_picks_scales_rng_weapons_to_subhex` (fix post-mesure : `get_weapons` rendait des portées en pouces bruts, écrasant le scaling — tir inopérant).

### Obstacle 7 — `CONCEPTION` · `VALUE` portait deux sens incompatibles — ✅ SOLDÉ (décision prise)

Mesuré : le moteur lit `VALUE` comme valeur de **combat** (`build_units_cache` en dérive `value_at_start`, référence de la force d'usure V11 §9.8 ; `build_squad_observation` refuse une valeur nulle), mais ED écrasait `VALUE` avec le **coût en points de réquisition** — 0 pour le leader de départ → `value_at_start[1] = 0` → aucune observation constructible, tour IA impossible.

Décision prise (en code) : **séparation des deux notions** — `VALUE` reste la valeur de combat, le coût vit dans `REQUISITION_COST`, écrit par `def _apply_slot_picks_to_unit` ; valeurs de départ dans `endless_duty.economy` (`starting_leader_combat_value` / `starting_leader_requisition_cost`). Gardé par `test_obstacle_7_solved_value_and_requisition_cost_are_separate`.

---

## 5. Obstacles restants et décisions attendues

Restent, sur les 7 de la mesure : **obstacle 2** (choix de level design : jeu de murs du plateau actif, ½ j) et **obstacle 4** (choix d'architecture d'initialisation : garnison de vague 1 dans le scénario ou spawn avant la première observation, 1 j). Le chiffrage complet d'origine (≈ 8-13 j pour les 7) est historique ; il reste en plus des restes non chiffrés :

- **Résidu obstacle 5** : `FACTION_KEYWORDS` vides sur les fiches ED (aucune capacité de faction ne les vise) — mécanique, décision implicite à confirmer (quelle faction pour les fiches ED ?).
- **Cohérence du décompte de réquisition** : backend en `VALUE` (`def _sum_units_value`), frontend en coûts catalogue (`resolveDraftInvestedTotal`), `REQUISITION_COST` écrit mais jamais lu (§2.3) — à trancher.
- **Consommables** : conception moteur absente (§2.7) — à concevoir.
- **Scoring / télémétrie** : non implémentés (§2.8).
- **UI de réquisition** : spec §2.10 partiellement implémentée (UI inline dans `BoardWithAPI.tsx`, pas de `RequisitionModal`), rendu jamais validé.
- Tout le périmètre **non exploré** du §6 (parcours HTTP réel, frontend, multi-vagues, défaite par objectif, combat en mode ED).

L'ordre et la priorité de reprise se lisent dans [Roadmap/moteur.md#endless-duty](../../Roadmap/moteur.md#endless-duty), jamais ici.

---

## 6. Ce qui reste NON EXPLORÉ

À dire tel quel : ce n'est pas « sain », c'est **non testé**.

- **Le parcours HTTP réel** (`POST /game/new` avec auth + permissions de profil, puis `/api/game/action`, `/api/game/ai-turn`) : la sonde court-circuitait la couche Flask. Rien ne dit que les routes ED répondent correctement bout en bout.
- **Le frontend** : aucun rendu vérifié. Le bouton, la route et le hook existent ; leur comportement face à un état ED réel est inconnu.
- **Plusieurs vagues d'affilée**, la montée en budget (`budget_growth_after_wave_20`, `wave_spike`) et les `wave_forced_spawns` au-delà de la vague 1.
- **La condition de défaite par objectif** : `def _update_objective_loss_counter` n'a jamais été vu s'incrémenter. Le support a changé depuis la mesure (zone objectif unique dédiée, obstacle 3 soldé) ; son comportement réel reste à constater.
- **Le combat lui-même** en mode ED (phase `fight`, pertes, morale) : jamais atteint, les unités étant trop éloignées dans les tours joués.

Traité depuis la mesure : les coordonnées de départ du leader (`ED_START_LEADER_COL` / `ED_START_LEADER_ROW`) ne sont plus les coordonnées d'avant la migration subhex qui posaient le leader dans un coin — elles le posent au centre, sur la zone objectif du terrain dédié.

---

## 7. Historique et sources

- **2026-03** — spec fonctionnelle V1 (`Endless_duty.md`) : vision, économie initiale à points fixes (remplacée ensuite par le VALUE-driven), puis sections « Decisions V1 lock » (économie capital, unlock par vague, règle d'objectif, spawn en bordure, consommables, logs `--step`, UI réquisition, variantes ED, bonus de plateau).
- **2026-07-29** — mesure d'état (`Endless_duty_etat_mesure.md`) : mode jamais démarrable, 7 obstacles franchis par sonde hors dépôt, boucle de jeu fonctionnelle une fois bouchés, chiffrage ≈ 8-13 j dont 2 décisions produit (obstacles 3 et 7). Décision utilisateur : **on ne supprime pas, on ne répare pas maintenant — on mesure et on consigne** ; réactivation à moyen-long terme. Signet exécutable créé.
- **2026-08** — compléments de mesure : requalification `FACTION_KEYWORDS` (parseur chantier 03) ; correction du 2026-08-10 : `config/agents/CoreAgent/` existe (l'affirmation contraire de la mesure était fausse ; l'agent vif est `ArmageddonAgent` par décision du 2026-07-19, pas par suppression de CoreAgent). Note d'environnement de la mesure : le modèle `ArmageddonAgent` n'existait pas au moment de la sonde (entraînement en cours).
- **Post-mesure** (constaté au signet, relancé vert le 2026-08-28) : obstacles 1, 3, 5, 6, 7 soldés en code (format V11 du scénario, terrain à objectif unique, fiches complétées, builder aligné subhex, séparation `VALUE`/`REQUISITION_COST`) + fix du scaling des portées dans les picks d'armes. Obstacles 2 et 4 toujours ouverts.
- **2026-08-28** — consolidation des deux sources dans ce document ; corrections tracées dans la livraison de consolidation.

---

## 8. Correspondance des sources

| Source | Ancien § | Section actuelle |
|---|---|---|
| `Endless_duty.md` | §1 Vision · §2 Core Loop | §1 |
| `Endless_duty.md` | §3 Roster Rules | §2.1 |
| `Endless_duty.md` | §4 Progression Economy | §2.3 (économie initiale purgée, remplacée par l'ex-§19.1) |
| `Endless_duty.md` | §5 Consumables | §2.7 |
| `Endless_duty.md` | §6 Map and Objective Structure | §2.5 |
| `Endless_duty.md` | §7 Wave Scaling | §2.6 (table de budget → config) |
| `Endless_duty.md` | §8 Scoring | §2.8 |
| `Endless_duty.md` | §9 UX Expectations · §10 Balancing Priorities · §11 Non-Goals · §14 Success Criteria | §2.14 |
| `Endless_duty.md` | §12 Implementation Roadmap · §16 Todo implémentation | purgés (état de chantier → Roadmap ; l'existant → §3.1) ; gates QA reprises en §2.14 |
| `Endless_duty.md` | §13 Télémétrie minimale | §2.8 |
| `Endless_duty.md` | §15 Exemples de compositions | §2.6 (profils conservés, arithmétique → config) |
| `Endless_duty.md` | §17 Time-to-Maturation Model | §2.12 |
| `Endless_duty.md` | §18 Protocole IA vs IA (§18.10 logging) | §2.13 (§2.9 pour le logging) |
| `Endless_duty.md` | §19.1 Économie finale · §19.1.b Slot unlock | §2.3 · §2.4 |
| `Endless_duty.md` | §19.2 Objectif/défaite · §19.2.b Spawn ennemi | §2.5 · §2.6 |
| `Endless_duty.md` | §19.3 Consommables · §19.4 Contrat logs `--step` | §2.7 · §2.9 |
| `Endless_duty.md` | §20 UI Requisition | §2.10 |
| `Endless_duty.md` | §21 Variantes `*_ED` | §2.2 (convention corrigée) |
| `Endless_duty.md` | §22 Random board bonuses | §2.11 |
| `Endless_duty_etat_mesure.md` | §1 Ce que le mode est / ce qui existe | §1 · §3.1 |
| `Endless_duty_etat_mesure.md` | §2 Comment ça a été mesuré | §3.2 (note d'environnement → §7) |
| `Endless_duty_etat_mesure.md` | §3 Obstacles 1-7 | §4 (numérotation conservée) |
| `Endless_duty_etat_mesure.md` | §4 Total et point d'arrivée | §3.3 · §5 |
| `Endless_duty_etat_mesure.md` | §5 Non exploré | §6 |
| `Endless_duty_etat_mesure.md` | §6 Le signet | §3.4 |
