# Moteur — Tâches ouvertes

---

## ✅ 13.09 — le statut « caché » suit les pertes et les tirs {#hidden-fraicheur}

**Livré le 2026-09-08 (option C).** Change les parties jouées : `--new` obligatoire pour tout modèle
entraîné avant ce correctif.

13.09 décrit un état **continu** — « a model is hidden WHILE all of the following apply » — mais le
moteur ne posait le drapeau qu'au début de la phase de tir, et la porte 13.09 du pool de cibles
lisait cette valeur gelée. Une escouade dont la dernière figurine exposée mourait en cours de phase
restait ciblable au-delà de la portée de détection. Ce n'est pas un cas de bord : les pertes sont
allouées en priorité à la figurine la plus proche de l'ennemi, donc à l'exposée.

Le statut est désormais rafraîchi dans `destroy_model`, **choke-point unique** de retrait de
figurines — donc pour les huit causes de mort, mêlée comprise, et non par un appel ajouté sur le
chemin du tir. `compute_hidden_status_for_unit` porte le calcul d'une escouade et
`compute_hidden_statuses` n'en est plus que la boucle : une seule implémentation des gardes 13.09,
aucun chemin parallèle. Le placement est contraint des deux côtés — après le recalcul de l'empreinte,
avant l'invalidation LoS qui purge le cache du pool.

**DEUX déclencheurs, un par membre de la règle** — correction de périmètre du 2026-09-08 : la
rédaction initiale n'en voyait qu'un, et s'y tenir fermait la règle à moitié.

1. **Membre géométrique** (les figurines vivantes) → `destroy_model`, décrit ci-dessus.
2. **Membre « did not make one or more ranged attacks during this turn »** →
   `end_activation(arg3="SHOOTING")` (`generic_handlers.py`), seul site d'alimentation de
   `units_shot` et donc seul déclencheur possible de ce membre. Sans lui, une escouade qui tirait
   depuis une zone obscurante restait marquée cachée jusqu'à la fin de la phase — 42 activations de
   tir sur 682 sur 20 épisodes. Le rafraîchissement passe par la fonction de règle plutôt que par
   un `hidden = False` écrit sur place : l'issue y est déterministe, mais la coder en dur ouvrirait
   un second endroit où vit 13.09.

   **Portée exacte de ce second déclencheur**, mesurée et non extrapolée : c'est un durcissement,
   pas la correction d'un ciblage aujourd'hui atteignable. `shooting_build_activation_pool` filtre
   sur `current_player`, donc seul le joueur actif tire pendant sa phase et le statut périmé de ses
   propres escouades est réécrit par le balayage complet au début de la phase adverse. Ce que le
   déclencheur apporte : un état exact entre-temps pour les quatre lecteurs de `unit['hidden']` et
   pour l'affichage PvP, et la clause fermée par avance pour tout tir hors de son propre tour.

**Contrat D1 étendu dans le temps** : `test_d1_survives_a_loss_mid_phase`
(`test_squad_obs_hidden_enemies.py`) vérifie que l'observation et le pool basculent ensemble après
une perte, sans rejouer le balayage de début de phase. Le membre « a tiré » a son propre couple
rouge/vert dans `test_hidden_1309_previous_turn.py` — `test_shooting_breaks_hidden_at_once` et sa
contre-épreuve `test_charging_does_not_break_hidden`, qui interdit un rafraîchissement posé sur
toute fin d'activation. Le balayage complet reste en place au début de la phase de tir et à chaque
sérialisation PvP.

**Limite connue, hors périmètre** : aucun MOUVEMENT ne rafraîchit le drapeau — il reste périmé
pendant le move et après un pile-in adverse. C'est la raison pour laquelle l'observation continue de
recalculer 13.09 à chaud plutôt que de lire `unit['hidden']`.

---

## P3-0 — Retrait pour cohérence 03.03 {#p3-0}

✅ **Livré 2026-08-23.** TOTAL_ACTION_SIZE 1359 → 1379 (+20 slots COHERENCY). Queue multi-escouade, sièges muets auto-résolus, tête pointeur `coherency_query_net` sur `self_models`. 32 tests verts. Run `--new` requis.

→ `Documentation/Chantiers/backlog/coherency_removal_choix_agent.md`

---

## Plunging Fire (22.05) + Deadly Demise (24.08) {#plunging-fire}

✅ **Livré 2026-08-25.** Mécanisme générique + câblage WeirdBoy (chantier 06). 17 tests rouge/vert. Lot passif ⚡ — aucun changement d'action space ni d'obs.

**Plunging Fire §22.05 :** `_manual_roll_intent` dans `shared_utils.py` — +1 BS (seuil amélioré de 1) si plancher ≥3" (chemin a) ou TOWERING ≤12" cible au sol (chemin b) ; `floor_height_by_model` lu dans `units_cache` ; court-circuit 2D (hauteur 0.0 jamais ≥ 3") ; step_logger token `[PLUNGING FIRE]` ; `_build_shot_details` dans `w40k_core.py` émet `hit_rule_modifier`.

**Deadly Demise §24.08 :** `_apply_deadly_demise` + `destroy_model` dans `shared_utils.py` — D6 lancé après disembark, sur 6 chaque unité à ≤6" subit X MW via `allocate_mortal_wounds` ; valeur `deadly_demise` lue dans `units_cache[squad_id]` avant suppression du modèle ; step_logger tag `[DEADLY DEMISE]` ; analyzer + corpus §22.05 et §24.08 câblés.

---

## Stratagèmes réactifs — Fire Overwatch (15.08) et Heroic Intervention (15.11) {#reactive-stratagems}

**Obs réservée avant R1 (2026-08-24), implémentation à J4.**

Deux stratagèmes core (1 CP chacun) déclenchés pendant le tour adverse :
- **Fire Overwatch §15.08** : fin de phase de mouvement adverse — unité amie tire en snap shooting (touche sur 6 seulement, une cible visible à ≤ 24").
- **Heroic Intervention §15.11** : fin de phase de charge adverse — unité amie résout une charge. Mode *Leap to Defend* (gratuit, cibles = unités qui ont chargé) ou *Into the Fray* (+1 CP, toutes cibles à ≤ 6").

Interruptions réactives pendant le tour adverse — cas le plus complexe du gym (le joueur passif décide). Implémentées via le mécanisme `agent_decision` existant.

**Slots obs réservés maintenant (avant R1) :**
1. `"fire_overwatch"` + `"heroic_intervention"` dans `AGENT_DECISION_TYPE_IDS` — **gratuit** (AGENT_DECISION_TYPE_SLOTS = 8, 5 → 7 utilisés).
2. `"charged"` dans `UNIT_BIN_FIELDS` — **+1 scalaire/entité**, nécessaire pour le mode *Leap to Defend* (distinguer les ennemis qui ont chargé). À faire en même temps que R1 pour éviter un 2e `--new` post-J3.

→ `Documentation/Chantiers/backlog/reactive_stratagems_overwatch_hi.md`

---

## T7 — Unification validation de déploiement {#t7}

**Suspendu.** Déclencheur : « le training tourne ».

🔴 Le fix décrit est FAUX en l'état (mesuré 2026-07-20) — c'est une décision de design (plan contraint par l'ancre), pas un bug. Re-analyser avant de toucher.

→ `Documentation/Chantiers/v11/tranches_et_ruptures.md` §5 T7

---

## ✅ 13.06 — le move gym peut finir en hauteur {#verticalite-move-gym}

**Livré le 2026-09-09.** Le move d'escouade du pipeline gym atterrissait TOUJOURS au sol :
`build_rigid_plan` écrivait `SQUAD_RIGID_MOVE_DESTINATION_LEVEL` pour toutes ses figurines et le
pool d'ancre sortait avant son bloc multi-niveaux. Mesuré avant : 710 275 destinations sur 6
épisodes, **aucune** à l'étage, alors que les deux terrains d'entraînement portent 8 étages chacun.

Ce qui change : une escouade **déclare** (13.06, point de choix `ascent_declaration`, sur les
emplacements `CHOICE_*` existants — zéro action nouvelle) qu'elle finira en hauteur, puis chaque
figurine finit au niveau résolu à SA case d'arrivée. Une escouade à cheval sol/étage est un plan
légal (03.03 tolère 5" de dénivelé), pas un cas limite. Le coût vertical est facturé **à la
figurine qui monte**, dans son propre budget de trajet — jamais en forfait au bloc : la pénalité de
descente n'en est pas le miroir (elle dépend du départ, la montée dépend de l'arrivée).

**Sans déclaration, tout le pipeline est bit-à-bit celui d'avant** — c'est ce qui borne le lot.

**Impose un retrain `--new`** : `obs_size` 16971 → 17055 (`max_floor_height`, `has_ground_model`,
`elevated`) et `GRID_CHANNELS` 11 → 12 (`occupant_level`). Sans ces features la montée serait un
état CACHÉ à effet sur la récompense (+1 BS de Plunging Fire 22.05, coût de descente au move
suivant) — le motif d'aliasing qui a déjà coûté un run à ce projet.

**Rendement mesuré, à connaître avant d'espérer** : sur 3 parties gym à x1, déclaration toujours
acceptée, **62 cellules sur 7 408** offertes par le masque (0,8 %) mettent au moins une figurine à
l'étage. La verticalité est désormais *jouable*, elle n'est pas *fréquente* : à x1 un socle ne tient
que sur 34 des 72 cases d'étage de `terrain-mc1` (13.06 interdit tout débordement du bord), et la
montée coûte 3" sur un MOVE de 6".

Reste ouvert : la **charge**, le **pile-in** et la **consolidation** gardent leur destination au
sol (`SQUAD_RIGID_MOVE_DESTINATION_LEVEL`), et **FLY + étages** reste hors périmètre — le pool
d'ancre renvoie avant son bloc multi-niveaux quand la traversée est active, exclusion préexistante.

---

## Phase B — Observation des niveaux {#phase-b}

**Partiellement levé le 2026-09-09** par le lot ci-dessus : l'observation porte désormais la
hauteur des unités (`max_floor_height`, `has_ground_model`), le bit `elevated` par figurine et le
canal de grille `occupant_level`. Ce qui restait de la Phase B — la LoS 3D côté `combat_utils`/WASM
— est inchangé.

**Suspendu pour le reste.** Après Phase A' validée ET vérification du chantier LoS 3D
(`combat_utils`/WASM, câblage incomplet).

→ `Documentation/Chantiers/v11/tranches_et_ruptures.md`

---

## LoS 3D : tir à travers un mur depuis un étage {#los-mur-etage}

**Cadré le 2026-08-25 — même root cause que la Phase B, pas un chantier indépendant.**

Le tir est légitime côté backend : le tireur élevé ignore correctement les murs de sa propre ruine (`_walls_around_occupied_floor`). Mais le cône WASM ne le sait pas — il trace la LoS comme si le tireur était au sol, bloque sur le mur de la ruine, alors que la cible clignote (backend valide). Le joueur voit le cône bloqué, clique quand même, ça tire. Bug d'affichage, pas de règle.

→ Traiter en même temps que la Phase B (`combat_utils`/WASM).

---

## Preview de tir sans deepcopy {#preview-tir}

**Lourd, re-cadrer avant reprise.** 4-8 j. Meilleure spec du lot, mais touche `compute_unit_los` = source unique (obs RL, reward, déploiement).

→ `Documentation/Chantiers/backlog/preview_tir_position_virtuelle.md`

---

## Endless Duty {#endless-duty}

**Plus aucune décision produit en attente** (constat vérifié 2026-08-28, signet
`tests/unit/services/test_endless_duty_is_broken.py` relancé vert) : les obstacles 1, 3, 5, 6 et 7
sont soldés en code — les décisions 3 (objectif fixe unique via terrain dédié) et 7 (séparation
`VALUE`/`REQUISITION_COST`) sont prises. Restent l'obstacle 2 (choix de murs, level design, ~½ j),
l'obstacle 4 (architecture d'init, ~1 j) et des résidus (FACTION_KEYWORDS vides, consommables,
scoring, UI, cohérence investi front/back — `REQUISITION_COST` écrit mais jamais lu).

→ `Documentation/Chantiers/backlog/endless_duty.md` (spec + état mesuré + obstacles, consolidés 2026-08-28)

---

## fix-reactive-move-coherency — ✅ livré 2026-08-21 {#reactive-move-coherency}

Move réactif : une escouade hors cohérence ne pouvait pas faire ce mouvement (03.01) mais le moteur ne le bloquait pas. Fix : check `_positions_in_coherency` avant le pool D6 dans `maybe_resolve_reactive_move`, log `reactive_move_declined reason=formation_incoherente`. Aligné sur le move normal (`build_squad_move_cell_map`). Test rouge→vert par mutation.

---

## Replis `unit_by_id` {#unit-by-id}

**T0 livré le 2026-08-19** — `require_unit_by_id(game_state, unit_id)` dans `engine/game_utils.py`, re-exportée depuis `combat_utils`. Signature canonique `(game_state, unit_id)` alignée sur le pattern moteur.

**T1 livré le 2026-08-25** — 9 sites Forme C convertis (commit dff4e8f0). `squad_fight_activation_order` supprimée (code mort, 0 appelant depuis fb7e83b6). 7 sites shooting_handlers + `_enqueue_rule_choice_candidates` w40k_core + résidu waaagh T2 → `require_unit_by_id`. Grep 0 résidu. 5 tests mutation-prouvés.

**T2 livré le 2026-08-25** — 46 sites Forme B convertis (charge_handlers 11, movement_handlers 11, fight_handlers 4, shared_utils 12, shooting_handlers 7+1 hors AST, reward_calculator 1). `unit_is_on_battlefield` supprimée (code mort, 0 appelant de production). api_server : 5 guards 404 ajoutés (frontières user-input). Grep résidu 0 (6 sites préservés : 2 tests, 3 frontières API, 1 contrat retour None). 13 tests mutation-prouvés (ROUGE→VERT).

**T3 livré le 2026-08-25** — 20 sites Forme D. **T4 livré le 2026-08-25** — 15 sites fight_handlers. **T4-bis livré le 2026-08-25** — 7 gardes résiduelles (shared_utils ×6, action_decoder ×1) + import manquant action_decoder. Re-grep global : 0 garde is-None résiduelle. Chantier clos.

→ `Documentation/Archives/chantiers/replis_unit_by_id_2026-08-05.md`
