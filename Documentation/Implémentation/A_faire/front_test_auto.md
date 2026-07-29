# Tests automatiques du front PvP — plan de mise en place exhaustif

> **Périmètre** : vérifier automatiquement TOUT ce que le front PvP affiche et permet de faire
> (cercles verts, previews, flux d'actions par phase, HUD, rendu PIXI), sans avoir à tester à la main.
>
> **Principe fondateur (vérifié dans le code)** : le front ne décide RIEN. `useEngineAPI.ts` mappe des
> champs renvoyés par le backend (`move_activation_pool` → cercles verts, `valid_move_destinations_pool`
> + mask loops → preview move, `squad_shoot_los_overview` → cibles surlignées) et `BoardPvp`/`UnitRenderer`
> les dessinent. On teste donc en 3 couches, de la moins chère à la plus chère :
> - **Couche A — API (sans navigateur)** : la donnée que le front consomme est correcte.
> - **Couche B — vitest (jsdom)** : le mapping donnée → props/état front est correct.
> - **Couche C — Playwright (navigateur réel)** : ce qui est effectivement dessiné/cliquable est correct.
>
> Une fonctionnalité est « couverte » quand sa source de vérité (A), son mapping (B) et son rendu (C)
> sont testés. Beaucoup de bugs vus en test manuel sont des bugs de A ; la couche A est donc prioritaire.
>
> **Aucun fallback, aucune valeur par défaut masquant une erreur** — un champ absent = FAIL explicite.
> **Aucune règle 40k assertée sans référence** au PDF `Documentation/40k_rules/` (ex. 09.07 déjà utilisé).

> **Statut (2026-07-29)** : Couche A — **T1, T2, T3, T4, T5, T6, T7b FAITS**.
> - **T1** (`scripts/pvp_smoke_test.py`, 27 checks verts) : smoke test de la vraie stack HTTP
>   (réseau + auth + serveur réel). Conservé tel quel, il ne grossit plus (cf. §0.5).
> - **T2/T3/T4/T5/T6/T7b** : `tests/integration/pvp/`, 6 fichiers, pyright propre.
>   Hors de `pytest tests/unit/` : ils ne sont PAS dans la commande de vérification large.
> - Le fuzzing T7b a trouvé une anomalie réelle dès sa 3ᵉ seed ; elle est corrigée, ainsi que
>   son jumeau en mêlée et l'anomalie « id inconnu ». L'allowlist du fuzzing est VIDE (§0.6).
> - Les deux anomalies de RÈGLES trouvées en T4/T6 sont elles aussi CORRIGÉES (§0.6.4 tir
>   après advance, §0.6.5 PV des personnages attachés) : arbitrage rendu le 2026-07-29 —
>   « les règles doivent être suivies ». Le masque gym appliquait déjà 10.05 ; seule la
>   correction des PV touche l'observation de l'agent → ré-entraînement à prévoir de ce fait.
> - Reste À FAIRE : T2b, T3a, T7, et toutes les couches B et C.

---

## 0. Existant et infra acquise

### 0.1 Harnais couche A : `scripts/pvp_smoke_test.py`
- Client `ApiClient` (stdlib pure), auth Bearer (`--token` / `--login+--password` / `--token-from-db`
  qui lit la dernière session de `config/users.db` en LECTURE SEULE).
- `--spawn-server` : serveur Flask dédié port 5011, `use_reloader=False` (le reloader Werkzeug
  redémarrait le serveur en boucle sous WSL2 et effaçait la partie — fixé aussi dans
  `services/api_server.py` : `debug=False`, `127.0.0.1`).
- Résultats typés PASS/FAIL/SKIP, exit code exploitable en CI/script.
- Partie de référence : `mode_code=pvp_test` (board 44x60x5, 42 unités / 123 figurines, phase
  initiale move, P1 ; 21 unités au pool de move, 5 engagées dès le départ).

### 0.2 Contrats API appris (à réutiliser tels quels)
- Toutes les actions passent par `POST /api/game/action` ; état par `GET /api/game/state`.
- Transition de phase : JAMAIS automatique — le front envoie `advance_phase` quand le pool est vide ;
  réponse `{phase_complete: true, reason: "pool_empty", next_phase: ...}`.
- Phase shoot : le moteur REJETTE `activate_unit` — chemin escouade obligatoire
  (`squad_shoot_activate`, puis `squad_shoot_los_overview` pour les cibles).
- HP : `unit.HP_CUR` = somme des PV des figurines VIVANTES, personnages attachés compris, à
  tout instant (corrigé le 2026-07-29, §0.6.5 — la convention « hors leader attaché » relevée
  en T1 n'était tenue qu'avant la première perte et ne vaut plus). HP par figurine dans
  `models_cache` ; `squad_models[uid]` = liste des ids de figurines (`"6#0"`, …).
  NB : `unit.HP_MAX` reste le profil de BASE (une figurine), pas un total d'escouade.
- Leviers de test déterministes déjà exposés par l'API :
  - `charge_roll_override` (remplace le jet 2D6 de charge) ;
  - `shoot_pool_require_los` (mode pool de tir exact vs transition rapide).

### 0.3 Existant couche B
- Vitest 3 + @testing-library/react + jsdom + msw (installé, aucun handler monté).
- 10 tests unitaires utils seulement (`activationClickTarget`, `losPreviewHelpers`,
  `movePoolRefsSync`, `weaponHelpers`, …). Aucun test de `useEngineAPI` ni de composant.

### 0.4 Existant couche C
- Rien. Pas de Playwright/Cypress, pas de `data-testid`, pas de hook de test exposé.
- Points d'accroche déjà présents (bridges fonctionnels) : `window.boardUnitDoubleClickHandler`,
  `window.cancelChargeHandler`, `window.cancelAdvanceHandler`, CustomEvents `boardUnitDoubleClick`.

### 0.5 Couche A — deux harnais, deux rôles (décision 2026-07-29)

La couche A est désormais écrite en **tests pytest in-process** (`tests/integration/pvp/`),
et non plus en extension du script HTTP. Raison mesurée dans le code :

- **Déterminisme.** Tous les jets du moteur passent par le `random` global du stdlib
  (`combat_utils.py:46`, `charge_handlers.py:4269`, `shared_utils.py:4450`, `roll_d6` injecté
  dans `attack_sequence`). Aucun `np.random`, `secrets`, `uuid4` ni `time.time()` dans
  `phase_handlers/`. Le `deterministic_seed` autouse de `tests/conftest.py` seede donc le
  moteur lui-même — impossible depuis un client HTTP, qui vit dans un autre process.
  C'est ce qui permettra à T4/T5/T6 d'asserter des valeurs exactes plutôt que des invariants.
- **Coût.** Démarrage d'une partie `pvp_test` : **1,0 s** in-process contre 7,6 s en HTTP
  (spawn du serveur compris). Une partie complète jusqu'à `game_over` : 595 actions, 64 s.
- **Isolation.** Seul `/api/game/start` exige une auth (`api_server.py:2086`) ; `/action` et
  `/state` n'en ont aucune. La fixture injecte l'auth et les permissions : `config/users.db`
  n'est jamais ouverte. Elle coupe aussi la persistance disque — à l'import, `api_server`
  charge `logs/save_config.json`, qui active snapshots et autosave en usage normal.

**Le script HTTP reste** : il est le seul à couvrir le réseau, l'auth réelle et le serveur
Flask complet. Il garde ses 27 checks et n'est plus étendu ; toute nouvelle tranche va en
pytest. Pas de duplication.

Socle livré dans `tests/integration/pvp/` :
- `conftest.py` : `GameClient` (act/try_act/refresh, pools, drain, `play_nominal`), fixtures
  `game` (invariants armés) et `game_unchecked`.
- `invariants.py` : les invariants T2, revalidés après **chaque** action par `GameClient`.

Contrats API relevés à cette occasion (à réutiliser) :
- Refus métier = HTTP 200 + `success:false` + motif machine dans **`result.error`**
  (`unit_not_eligible`, `invalid_destination`, `invalid_action_for_phase`,
  `plan_models_mismatch`) — il n'y a PAS de clé `error` au premier niveau.
- `max_turns` et `pve_mode` ne sont servis que par `/api/game/start`, jamais par `/state`
  ni `/action` : comparer deux états issus de sources différentes crée de faux diffs.
- `units_fled` ⊆ `units_moved` (`movement_handlers.py:1292`) : un fall-back reste une
  sélection pour bouger (09.02).
- Un `move` sur une unité non activée **auto-active** l'unité puis traite la destination
  (`movement_handlers.py:819-841`) : un refus de destination laisse donc un preview posé.
- Phase fight : chaque sous-phase a son verbe de sortie (`end_pile_in`, `skip_fight`,
  `end_consolidation`). Tout autre verbe y est un **no-op renvoyant `success:true`** —
  piège à boucle infinie pour tout pilote automatique.

Contrats relevés pendant T4/T5/T6 (2026-07-29) :
- `charge_roll_override` et `shoot_pool_require_los` voyagent au PREMIER niveau du corps de
  l'action (`api_server.py:2386-2392`), pas dans un sous-objet. L'override de charge est lu
  à l'ACTIVATION de l'unité (11.02 : le jet précède la déclaration des cibles) et mémorisé
  dans `charge_roll_values` : une même unité ne peut pas être ré-activée avec un autre jet
  dans la même phase.
- Résolution d'un tir/combat avec défenseur humain, DEUX temps distincts :
  `..._declare_order` (ordre des groupes de figurines, 05.03 — demandé seulement si la cible
  a plusieurs groupes) puis un `..._allocate_model`/`..._manual_alloc` PAR BLESSURE (05.04).
  L'activation ne se termine qu'au dernier clic.
- Les lots d'attaques (`bs`, `bs_base`, `cover`, `heavy_applied`, `rapid_fire_applied`, jets
  détaillés) ne sont exposés que TANT QU'une blessure reste à allouer
  (`game_state["pending_shoot_allocation"]`). Une salve sans sauvegarde ratée termine
  l'activation sans jamais publier ces lots.
- `pile_in_autoplace` exige un `targetId` (focus de l'optimisation), `consolidate_autoplace`
  et `charge_autoplace` non.
- `end_pile_in` doit être envoyé DEUX fois pour quitter la sous-phase : 12.02 fait jouer le
  pile-in par le joueur actif puis par son adversaire, chaque moitié se fermant elle-même.
- En phase de tir, l'état n'expose AUCUN booléen d'engagement : le seul juge est la géométrie
  (empreinte à empreinte vs `get_engagement_zone`). Les tests classent donc les unités avec
  la brique du moteur et n'assertent que la sortie de l'API.

### 0.6 Anomalies trouvées — toutes CORRIGÉES (2026-07-29)

Trois de ROBUSTESSE (HTTP 500) et deux de RÈGLES. L'allowlist `KNOWN_SERVER_ERRORS` du
fuzzing est **vide**, plus aucune 500 n'est tolérée nulle part, et il ne reste AUCUN test
`@pytest.mark.anomaly` en couche A : chaque sentinelle a été remplacée par un test du
comportement corrigé. Arbitrage rendu sur les deux corrections de règles : les règles
priment. Le masque d'action du gym appliquait déjà 10.05 (§0.6.4) ; c'est la correction des
PV (§0.6.5), qui entre dans l'observation, qui impose un ré-entraînement.

1. **Id d'unité inexistant → HTTP 500** au lieu d'un refus métier. **CORRIGÉ**.
   La levée était dans le pré-traitement du step_logger (`_process_semantic_action`,
   `w40k_core.py`), qui récupère l'unité avant l'action pour logger sa position et son
   joueur — pas dans la logique de jeu. Le motif `unit_not_found` existait déjà dans une
   dizaine de handlers (`movement_handlers.py:797`, `shooting_handlers.py:5429`…) : c'était
   le dispatch central qui était incohérent avec eux.
   Correctif appliqué : id inconnu de `units` ET `units_cache` ET `squad_models` → refus
   métier `unit_not_found`, HTTP 200, motif dans `result.error` ; id connu de `units_cache`
   ou `squad_models` mais absent de `units` → `KeyError` conservée (vraie incohérence d'état
   interne, elle doit rester bruyante). Le traceback exposé en 500 est conservé (serveur de
   dev, utile au debug).
   NB : le second cas n'est **pas atteignable par l'API** — `units_cache ⊆ units` est un
   invariant vérifié après CHAQUE action (`invariants.py`, fermeture référentielle), y
   compris sur la partie complète et le fuzzing. Aucun test ne le provoque donc : le
   fabriquer demanderait de truquer le `game_state`, ce qui ne prouverait rien du contrat
   de l'API. C'est précisément le sens de la distinction : ce chemin ne doit jamais arriver.
   Test : `test_invariants.py::test_unknown_unit_id_is_a_clean_business_refusal`
   (réutilise `_assert_inert`, donc state strictement inchangé).
2. **Ré-activation d'une escouade en tir → HTTP 500** (trouvée par le fuzzing T7b).
   **CORRIGÉ**.
   Forme la plus courte, mesurée : **deux clics** sur la MÊME escouade suffisent
   (`squad_shoot_activate` ×2). Formes voisines : A → B → re-clic A (comparer les cibles de
   deux unités avant de choisir) ; et la variante inter-tours (activation abandonnée, le
   pending survit au changement de tour).
   Cause : `active_shooting_unit` est un SINGLETON, écrasé à chaque activation sans libérer
   le pending de l'escouade précédente, qui devenait orphelin — inaccessible mais présent.
   `assert_no_pending_shoot_intent` (`shared_utils.py`) levait alors au retour sur elle.
   Le front ne protège pas de ce chemin : `useEngineAPI.handleStartSquadModelShoot`
   n'envoie **pas** de `squad_shoot_cancel` avant d'activer une autre unité (son
   `squadShootActivatingRef` ne garde que contre le double-clic *concurrent*, et il est
   relâché dès la réponse). Le bug était donc atteignable à la souris, pas seulement par API.
   Correctif appliqué (2 points) :
   - **cancel implicite** dans le dispatch `squad_shoot_activate` (`w40k_core.py`) : toute
     activation en cours est libérée (`clear_pending_shoot_intent` + `active_shooting_unit`)
     avant d'en ouvrir une nouvelle, y compris quand c'est la même escouade. Ses
     déclarations d'armes sont perdues — c'était déjà le cas de fait. Mémoriser puis
     restaurer les déclarations de l'escouade quittée est une évolution fonctionnelle
     séparée, hors périmètre.
   - **purge de sécurité** en fin de phase de tir (`_shooting_phase_complete`) : les
     pendings résiduels et `active_shooting_unit` sont vidés. On ne lève PAS : laisser
     plusieurs activations en plan est un état NORMAL du flux (le joueur explore les cibles
     de plusieurs unités).
   Ce qui n'a **pas** été fait, à dessein : aucun `pop` défensif dans
   `squad_shooting_unit_activation_start` (la sentinelle reste entière) ; rien ajouté dans
   la résolution, qui purge déjà les intents (`_build_manual_allocation`,
   `shared_utils.py:8043`, via `ctx.intents_key` — commun au tir et à la mêlée).
   Tests : `test_shoot.py::TestShootActivationLifecycle` (3 tests).
3. **Jumeau en mêlée → HTTP 500** (cherché après le correctif du tir, trouvé). **CORRIGÉ**.
   Forme minimale : sous-phase `fight`, `activate_unit` A → `squad_fight_assign` (le flux
   manuel par-figurine ouvre l'activation via `_fight_ensure_activation_started`) → clic
   direct sur la cible (`fight`). Ce dernier chemin appelait
   `squad_fight_unit_activation_start` sans libérer le pending →
   `assert_no_pending_fight_intent`.
   Correctif appliqué : `squad_fight_restart_activation` (`shared_utils.py`) — libère puis
   ouvre — sur les 4 chemins de **résolution directe**, qui redéclarent TOUTE l'escouade et
   remplacent donc les déclarations manuelles au lieu de s'y ajouter (`fight_handlers.py`
   dispatch FIGHT, branche New Foes, `_fight_v11_resolve_attacks`, et le chemin gym
   `squad_fight` de `w40k_core.py`). Plus la purge symétrique en fin de phase
   (`_fight_v11_phase_complete`).
   Tests : `test_fight.py::TestFightActivationRestart` (2 tests).
4. **Tir d'une arme non-[ASSAULT] après un advance** — PDF 10.05. **CORRIGÉ** (trouvée en T4).
   Mesuré : une escouade qui a avancé et possède au moins une arme [ASSAULT] entre bien dans
   le pool de tir (10.05), mais le flux d'escouade lui laisse ensuite DÉCLARER et RÉSOUDRE
   ses armes non-[ASSAULT] (ex. unité 1008 : `bolt_pistol` tiré après advance).
   PDF 10.05, WHILE SHOOTING : « You can only select [ASSAULT] weapons to make attacks with ».
   Root cause : l'éligibilité par arme du flux d'escouade
   (`_model_can_shoot_target_with_weapon`, shared_utils.py) ne teste que portée, LoS et
   engagement (10.06) — elle ignore `units_advanced`. Les deux autres chemins l'appliquent
   pourtant : `weapon_availability_check` (shooting_handlers.py:560, mono-figurine) et
   `_unit_can_shoot` (niveau POOL, d'où l'exclusion correcte d'une unité sans [ASSAULT]).
   Correctif appliqué : `_advance_blocks_weapon` (shared_utils.py) — même critère et même
   fonction que le chemin mono-figurine (`_can_unit_shoot_after_advance_with_weapon`), donc
   l'exception `shoot_after_advance` reste honorée — appelée dans les DEUX points
   d'éligibilité par arme du flux d'escouade : `_model_can_shoot_target` (arme sélectionnée)
   et `_model_can_shoot_target_with_weapon` (arme précise). Tout en découle : menu
   `can_use`, menu cible-d'abord, `qty_max`, voile vert et déclaration.
   Troisième point, trouvé en relisant le correctif : `squad_shoot_los_overview` choisissait
   son ARME DE TEST (une seule, la plus longue portée, la LoS ne dépendant pas de l'arme)
   sans regarder le type de tir — juste « engagée → un [CLOSE-QUARTERS] ». Une escouade ayant
   avancé aurait donc testé une arme non-[ASSAULT], désormais bloquée, et n'aurait affiché
   AUCUNE cible. Corrigé en déléguant à `resolve_squad_shooting_type` +
   `shooting_type_allows_weapon`, l'autorité déjà utilisée par le masque gym. Effet de bord
   bienvenu : le volet MONSTER/VEHICLE de 10.06 (« you can select any of that model's ranged
   weapons ») y est désormais honoré, là où un véhicule engagé sans arme [CLOSE-QUARTERS]
   était privé de cibles.
   NON VÉRIFIABLE sur `pvp_test` : aucune unité du roster n'a d'arme non-[ASSAULT] plus
   longue que son [ASSAULT], et aucun véhicule n'est engagé au tour testé. Ces deux
   comportements sont donc corrects par construction mais non verrouillés par un test —
   à couvrir avec un roster qui les produit.
   IMPACT GYM : nul pour cette règle. Le masque de l'agent appliquait DÉJÀ 10.05
   (`resolve_squad_shooting_type` + `squad_model_shootable_weapon_indices`, action_mask) ;
   c'est le flux d'escouade PvP qui était en retard sur lui. Aucun ré-entraînement de ce
   fait.
   Test : `test_shoot.py::test_only_assault_weapons_are_firable_after_an_advance`
   (menu, menu cible-d'abord ET refus de la déclaration directe).
5. **PV d'unité : la convention « hors personnage attaché » n'était pas tenue après la
   première perte** (PDF 19). **CORRIGÉ** (trouvée en T6).
   §0.2 documentait alors la convention : `unit["HP_CUR"]` = total d'escouade HORS leader
   attaché.
   Elle est bien appliquée au démarrage (`nb_figurines × PV_du_profil_de_base`) : 5 unités
   sur 42 divergent alors de la somme réelle de leurs figurines (ex. 111 : 21 annoncés pour
   26 répartis, Librarian 5 PV + Captain 6 PV).
   Le défaut est la SUITE : dès la première figurine tuée, le moteur recalcule le total sur
   les survivantes, personnages COMPRIS — les PV de l'unité AUGMENTENT (21 → 23 en tuant une
   figurine à 3 PV). La grandeur change donc de définition en cours de partie ; tout lecteur
   du total d'unité (score, observation de l'agent, tri de cibles) compare des choux et des
   carottes selon qu'une perte a eu lieu ou non.
   Correctif appliqué : au réveil de l'épisode (`w40k_core`), `HP_CUR` d'unité = somme des
   `HP_MAX` PAR FIGURINE, avec la même convention que le constructeur de `models_cache`
   (`spec.get("HP_MAX", hp_max)`, shared_utils.py:778) pour les figurines sans override.
   La formule fautive était `HP_MAX * model_count`, où `unit["HP_MAX"]` porte le profil de
   BASE ; `game_state.py:1240` calculait déjà le bon total, c'est le réveil qui l'écrasait.
   Une seule définition désormais, celle des figurines, identique avant et après la première
   perte. IMPACT GYM : le total d'unité entre dans l'observation et les agrégats de valeur
   (avantage matériel, attrition) → c'est LA correction qui justifie un ré-entraînement.
   L'égalité est promue INVARIANT transversal (`invariants.py::_assert_hp_squad_sum`, sans
   plus aucune exception) : elle est revalidée après CHAQUE action de toute la couche A.

---

## Couche A — Tests API exhaustifs (`tests/integration/pvp/`)

Objectif : dérouler UNE partie scriptée qui traverse toutes les phases des deux joueurs sur
plusieurs tours, avec des checks par phase + des invariants transversaux revalidés après CHAQUE action.

### T2 — Invariants transversaux (à revalider après chaque action) — **FAIT**
`invariants.py` + `test_invariants.py` (10 tests). Armés sur chaque action par `GameClient`.
- [x] Ids uniques ; HP figurines bornés ; positions dans le board (unités ET figurines).
- [x] HP d'unité == somme des PV de ses figurines vivantes, SANS exception (§0.6.5).
- [x] Cohérence référentielle `units` ↔ `units_cache` ↔ `models_cache` ↔ `squad_models`
      (fermeture dans les deux sens, `squad_id` de chaque figurine cohérent).
- [x] Tout pool ⊆ unités vivantes ; appartenance au joueur actif pour
      `move/shoot/charge/command_activation_pool`. Les pools de fight en sont exclus : par
      construction, l'alternance 12.01-12.03 y fait figurer les unités des DEUX joueurs.
- [x] États contradictoires : pool ∩ `units_moved`/`units_shot`/`units_charged` = ∅ ;
      `units_fled` ⊆ `units_moved`.
- [x] Action refusée → state STRICTEMENT inchangé (diff champ à champ), motif dans
      `result.error`, jamais de 500 (hors anomalie §0.6.1).
      Exception documentée : `move` sans activation préalable auto-active l'unité
      (`movement_handlers.py:819-841`) — le test vérifie alors qu'elle n'a ni bougé ni
      quitté le pool.
- [x] `phase` ∈ {deployment, command, move, shoot, charge, fight}, `current_player` ∈ {1,2},
      `turn` ≥ 1. Séquence 07 (alternance + incrément de tour) vérifiée par T7b.
      NB : `pvp_test` démarre en move ; le flux deployment/command se teste en mode `pvp`
      (T3a/T2b), toujours à faire.

### T2b — Phase command + réactions
Champs relevés : `command_activation_pool`, `reaction_window_active`, `reactive_decision_mode`,
`reactive_decision_payload`, `units_reacted_this_enemy_turn` ; actions `force_battle_shock`,
`select_rule_choice`.
- [ ] Pool command : composition, activation, effets (battle-shock tests LD — PDF 08/01.07 à lire
      avant d'asserter), transition vers move.
- [ ] Fenêtres de réaction : quand `reaction_window_active` s'ouvre, seules les actions du payload
      réactif sont acceptées ; toute autre action → rejet explicite, state inchangé.
- [ ] `select_rule_choice` : un choix de règle en attente (`choice_timing_index`) BLOQUE les autres
      actions tant qu'il n'est pas résolu ; chaque option produit l'effet attendu.

### T3a — Déploiement (mode `pvp`)
Actions relevées : `deploy_unit`, `deploy_preview`, `deploy_generate_formation`,
`deploy_model_destinations`, `deploy_squad_destinations`, `deploy_commit`, `change_roster`.
Contrainte (mémoire projet) : le déploiement doit copier EXACTEMENT la phase de move — mêmes
fonctions de pool par figurine, jamais de logique durcie/divergente.
- [ ] Alternance de déploiement entre joueurs, unités restantes correctes.
- [ ] `deploy_model_destinations`/`deploy_squad_destinations` : destinations ⊆ zone de déploiement
      (`deployment_zone`), niveau par sœur honoré (superposition inter-étage).
- [ ] `deploy_generate_formation` → formation valide (cohérence, pas de chevauchement), commit →
      positions posées, mismatch masque/commit (bug historique T5 V11) surveillé.
- [ ] `change_roster` : nouveau roster chargé, state réinitialisé proprement.
- [ ] Fin de déploiement → première phase de bataille correcte.

### T3 — Move : escouades par figurine + advance + fall-back
Actions front relevées : `preview_move_plan`, `move_model_destinations` (BFS par figurine, avec
`provisional_plan`, `level`, `orientation`), `commit_move_plan`, `advance`, `wait`, `left_click`,
`right_click`.
**FAIT** (`test_move.py`, 10 tests) — sauf les 3 dernières lignes.
- [x] Pool complet en début de phase = toutes les unités vivantes du joueur actif (09.02).
- [x] Activation d'une escouade multi-figurines → destinations PAR FIGURINE
      (`move_model_destinations`), plan provisoire (une sœur posée retire sa case du pool des
      suivantes), `preview_move_plan` (`coherency_ok`/`can_validate`/`per_model`), commit →
      positions par figurine mises à jour, sortie du pool, réactivation refusée.
- [x] Plan incomplet → `plan_models_mismatch`, unité conservée dans le pool.
- [x] Distance : aucune destination au-delà de `MOVE` (09.05). Borne assertée en hexes —
      chaque pas de BFS coûtant ≥ 1 subhex, `hex_distance ≤ MOVE` est vrai quel que soit le
      coût du terrain. Le coût de descente §13.06 n'est PAS encore vérifié séparément.
- [x] Advance (09.06) : jet ∈ 1..6, portée étendue et bornée par `M + jet × inches_to_subhex`,
      unité marquée `units_advanced`, puis EXCLUE du pool de charge.
      NB : le PDF 09.06 n'interdit PAS de tirer après un advance (il n'interdit que charge et
      action) — la restriction de tir relève des règles d'armes (Assault), à traiter en T4.
- [x] Fall-back (09.07) : unité engagée → marquée `units_fled` (et `units_moved`), exclue du
      pool de tir ET du pool de charge, et absente de `fight_eligible_units` (désengagée).
- [ ] Pivot/orientation : `orientation` passée au BFS → empreinte honorée (EZ 2", collisions).
- [ ] Étages : `level` ≠ 0 → pool niveau-conscient (unité 1008 du scénario, level 1).
- [ ] Rejets : move hors pool de destinations → erreur explicite, state inchangé.

### T4 — Shoot : par arme et par figurine — **FAIT** (`test_shoot.py`, 14 tests)
Actions relevées : `squad_shoot_select_model`, `squad_shoot_assign_weapon_qty`,
`squad_shoot_weapon_qty_max`, `squad_shoot_unassign`, `squad_shoot_unassign_weapon`,
`squad_shoot_validate`, `squad_shoot_cancel`, `squad_shoot_allocate_model`, `move_after_shooting`.
- [x] Cycle de vie de l'activation : cancel implicite A→B→A, re-clic sur la même escouade,
      activation abandonnée purgée en fin de phase (§0.6.2).
- [x] `squad_shoot_los_overview` : `cover_by_unit_id` et `count_by_unit_id` couvrent EXACTEMENT
      `valid_targets` ; cibles toutes ennemies et vivantes ; `1 ≤ count ≤ squad_alive_count`.
- [x] `squad_shoot_select_model` : l'union des cibles par figurine == les cibles d'escouade
      (04.01, le tir est par figurine), et aucune figurine ne voit au-delà.
- [x] Unité engagée (10.06) : seules les armes [CLOSE-QUARTERS] sont `can_use`, et les cibles
      se limitent aux ennemis avec lesquels l'unité est engagée. Vérifié sur les 3 unités
      engagées du tour 1 (1011, 7, 1009).
- [x] Advance (10.04/10.05) : une unité sans arme [ASSAULT] qui a avancé quitte le pool de
      tir ; avec une [ASSAULT] elle y reste, mais SEULES ses armes [ASSAULT] sont proposées
      (menu, menu cible-d'abord) et la déclaration directe d'une autre est refusée
      (`cannot_shoot`). Corrigé en §0.6.4.
- [x] Quantités : `squad_shoot_weapon_qty_max` == `m` du menu cible-d'abord == nombre de
      figurines du voile vert ; `count > qty_max` → refus `cannot_shoot` sans déclaration
      résiduelle ; `count == qty_max` → une déclaration par figurine distincte.
- [x] Unassign, les trois granularités : par (arme, cible) `squad_shoot_unassign_weapon_qty`,
      par figurine `squad_shoot_unassign`, et par INDEX d'arme `squad_shoot_unassign_weapon`
      (celle qu'utilise le front pour le remplacement de profil combi). La borne
      `qty_max` revient à son état initial dans chaque cas.
- [x] Cancel : l'escouade retourne au pool sans déclaration (10.02 : pas encore « sélectionnée
      pour tirer »).
- [x] Résolution : allocation manuelle par le défenseur (05.04) figurine par figurine, PV
      décrémentés dans `models_cache`, morts retirés du cache, `attacks ≥ hits ≥ wounds ≥
      failed_saves`, `units_shot` alimenté, sortie du pool, pending libéré.
- [x] Cover (13.08) : `bs == min(6, bs_base + 1)` si couvert, `bs == bs_base` sinon — mesuré
      sur les lots d'attaques exposés par l'allocation, en écartant les modificateurs
      concurrents ([HEAVY] 24, [IGNORES COVER] 24.18, volet MONSTER/VEHICLE de 10.06).
- [x] Unités cachées (13.09) : une unité cachée hors de sa portée de détection n'apparaît
      JAMAIS dans `valid_targets` ; `detection_inches` ∈ {15 (13.09), 12 (gone to ground)} ;
      toute unité listée dans `hidden_detection_info_by_unit_id` est bien `hidden`.
      NB : le PvP est en hotseat, `/state` n'est pas filtré par joueur — c'est donc bien la
      liste des cibles (et le blink qu'elle alimente) qui porte la confidentialité.
- [ ] `shoot_pool_require_los` true/false : NON couvert. Le drapeau ne change pas le verdict
      légal, il change le COÛT de la transition move→shoot (pool exact au build vs cible
      résolue à l'activation, `shooting_handlers.py:2196`). Un test d'équivalence des deux
      modes coûte ~1,5 s de transition par phase : à faire dans une passe dédiée.
- [ ] `move_after_shooting` : INATTEIGNABLE avec ce roster. La règle existe
      (`config/unit_rules.json`) mais AUCUNE unité de `config/unit_definitions.json` ne la
      porte — il n'y a rien à déclencher. À couvrir le jour où une unité l'obtient.
- [ ] `shoot` (verbe mono-figurine) : le flux PvP passe exclusivement par le chemin escouade
      (`squad_shoot_*`) ; le verbe `shoot` appartient au chemin gym. Hors couche A PvP.

### T5 — Charge — **FAIT** (`test_charge.py`, 8 tests)
Actions relevées : `charge`, `charge_plan_state`, `commit_charge_plan`, `charge_autoplace`,
`take_to_skies`, `charge_roll_override`, `force_charged`, annulation via `right_click`
(`window.cancelChargeHandler`).
- [x] Pool 11.02 : unités vivantes du joueur actif, jamais `units_advanced` ni `units_fled`,
      jamais une unité déjà engagée, toujours un ennemi à 12" ou moins (mesuré empreinte à
      empreinte, pas d'ancre à ancre).
- [x] Une unité qui a avancé est exclue du pool de charge (09.06 + 11.02).
- [x] `charge_roll_override` : le jet forcé est bien celui utilisé (4, 8, 12) et aucune cible
      déclarable n'exige un déplacement supérieur au budget. Le budget nécessaire est
      `distance − zone d'engagement` : l'unité s'arrête à la zone, et elle ne peut pas y être
      déjà (encadré FAILED CHARGES de 11.02).
- [x] Jet à 2 → `charge_failed`, unité sortie du pool, AUCUNE figurine déplacée, pas de
      `units_charged`, pas d'engagement créé.
- [x] Charge committée (11.04 AFTER MOVING) : l'unité engage TOUTES ses cibles déclarées et
      AUCUN ennemi non déclaré ; elle s'est rapprochée ; `units_charged` alimenté ; sortie du pool.
- [x] Plan par figurine : `charge_plan_state` (phase, `eligible_models`, `unsatisfied_targets`,
      `can_validate`) ; un plan hors pool est refusé en 200, l'unité reste au pool sans bouger.
      `charge_autoplace` produit un plan couvrant TOUTES les figurines, accepté au commit.
- Contrat mesuré, à ne pas confondre avec la lettre de 11.04 : le moteur n'offre que les
  cibles qu'il peut réellement ENGAGER (empreinte finale légale). Des ennemis à portée du jet
  sont donc écartés faute de placement — c'est le résultat correct (11.04 exige l'engagement
  de toutes les cibles), mais cela rend le sens « toute cible à portée est déclarable »
  non-assertable.
- [ ] `take_to_skies` (21.03) et `force_charged` : non couverts (aucune unité FLY éligible
      rencontrée dans le scénario au tour testé). À reprendre avec un roster qui en contient.

### T6 — Fight — **FAIT** (`test_fight.py`, 7 tests)
Actions relevées : `fight`, `skip_fight`, `squad_fight_assign`, `squad_fight_assign_weapon`,
`squad_fight_validate`, `squad_fight_manual_alloc`, `squad_hazard_allocate_model`,
`hazard_confirm`, pile-in : `pile_in_plan_state`, `pile_in_autoplace`, `commit_pile_in_plan`,
`end_pile_in` ; consolidation : `consolidation_plan_state`, `consolidation_select_target`,
`consolidation_select_objective`, `consolidate_autoplace`, `commit_consolidation_plan`,
`cancel_consolidation`, `end_consolidation`.
- [x] Redémarrage d'activation : `squad_fight_assign` puis clic-cible direct (le clic redéclare
      toute l'escouade) ; déclaration abandonnée purgée en fin de phase (§0.6.3).
- [x] Sous-phases : le verbe de sortie d'une AUTRE sous-phase est un no-op `success:true` qui
      ne fait pas avancer la phase (piège à boucle infinie, vérifié explicitement).
      `end_pile_in` doit être envoyé DEUX fois : 12.02 fait jouer le pile-in par les deux
      joueurs successivement, chaque moitié se ferme par son propre verbe.
- [x] Éligibilité 12.04 : toute unité éligible est engagée ou a chargé ce tour, et aucune n'a
      déjà été sélectionnée pour combattre.
- [x] Pile-in 12.03 : `pile_in_model_move` (modèle par figurine), `pile_in_targets` == tous les
      ennemis engagés, aucun déplacement au-delà de 3", engagements conservés après commit.
      `pile_in_autoplace` exige un `targetId` (focus ILP), contrairement à `consolidate_autoplace`.
- [x] Résolution 12.05 : déclaration par figurine/arme, puis DEUX temps côté défenseur —
      `squad_fight_declare_order` (ordre des groupes, 05.03, demandé seulement si la cible a
      plusieurs groupes) puis `squad_fight_manual_alloc` par blessure (05.04). PV décrémentés
      par figurine, morts retirés du cache, unité consommée (`units_selected_to_fight`,
      retirée de `fight_eligible_units`), déclarations libérées.
- [x] Consolidation 12.08 : une unité engagée est en mode `ongoing` IMPOSÉ, ses cibles sont
      tous ses ennemis engagés, les modes concurrents ne proposent rien
      (`awaiting_target_selection`/`awaiting_objective_selection` faux, candidats vides),
      aucun déplacement au-delà de 3", engagements conservés après commit.
- [ ] Modes `engaging` / `objective` de la consolidation (`consolidation_select_target`,
      `consolidation_select_objective`, `cancel_consolidation`) : non couverts. 12.08 les rend
      mutuellement exclusifs et subordonnés — une unité engagée ne peut PAS y accéder, et
      toutes les unités éligibles à la consolidation du tour testé sont engagées. Il faut un
      scénario où une unité survit à la mort de son adversaire pour les atteindre.
- [ ] `squad_hazard_allocate_model` / `hazard_confirm` (24.15) : non couverts — aucune arme
      [HAZARDOUS] déclarée dans les combats testés.
- [ ] Mort d'une unité en mêlée (retrait complet, ré-éligibilité de l'adversaire selon 12) :
      non couvert isolément ; le retrait des FIGURINES l'est.

### T7 — Fin de partie et systèmes annexes (API)
- [x] Victoire : `game_over`, `winner`, VP corrects sur une partie scriptée jusqu'au bout
      (couvert par T7b `test_a_whole_game_stays_coherent_until_game_over` : 595 actions, la
      partie va au bout, tours croissants et bornés par `max_turns`, les deux joueurs jouent
      chaque tour, `winner` cohérent avec les VP).
- [ ] Battle-shock : `force_battle_shock` + tests LD/OC (PDF 01.07/08).
- [ ] Snapshots/rewind : `GET /api/game/snapshots`, `timeline`, `snapshot/restore` → l'état restauré
      est STRICTEMENT égal au state d'origine (diff JSON champ à champ).
- [ ] Save/load : `game/save` + `save/load` → même égalité stricte.
- [ ] Auth : accès sans token → 401 ; mode non autorisé → 403.

### T7b — Fuzzing par invariants (la vraie garantie d'exhaustivité) — **FAIT**
`test_fuzzing.py` (6 tests). Les tranches T2-T7 testent des scénarios CONNUS ; le fuzzing
couvre les enchaînements imprévus.
- [x] Partie complète jusqu'à `game_over`, invariants revalidés après chaque action.
- [x] Agent aléatoire : 2/3 d'actions nominales (pour que la partie progresse), 1/3 tirées du
      vocabulaire de la phase courante ; invariants T2 après chaque action ; 3 seeds. Le
      tirage utilise son propre `random.Random(seed)` pour ne pas déplacer la séquence de dés
      du moteur — le journal des 8 dernières actions est affiché en cas d'échec.
- [x] Fuzzing négatif : actions illégales sur des ids VALIDES → refusées avec motif, state
      inchangé, jamais de 500 ; 2 seeds. Restreint à move/shoot/charge, dont le dispatch
      refuse explicitement : en fight, tout verbe hors sous-phase est un no-op à
      `success:true` (§0.5), un refus ne peut donc pas y être exigé. Les ids inexistants sont
      exclus : ils relèvent de l'anomalie §0.6.1, déjà verrouillée.
- [x] Chaque violation trouvée devient un check nommé permanent : appliqué dès le premier run
      (anomalie §0.6.2, trouvée à la seed 3).
- [ ] Budget : N parties complètes par run (ex. 20), sur plusieurs boards. Aujourd'hui 1 partie
      complète + 5 marches aléatoires bornées à 120/40 actions (~2 min à `-n 4`).

### Hors périmètre de ce document (à décider séparément)
- **Tutoriel** (BoardPvpWithTutorialAdvance, `/api/config/tutorial/steps`, scénarios étape N) :
  flux scripté à part, testable avec la même infra couche C — tranche dédiée si souhaité.
- **PvE / `ai-turn`** : le tour IA dépend d'un modèle entraîné (non déterministe entre versions de
  modèles) — tester uniquement le contrat (l'IA joue des actions légales, la main revient au joueur).
- **Endless Duty** (`endless_duty_status`/`commit`) : mode à part, mêmes couches applicables.
- **Replay viewer** (`/api/replay/*`, `replayParser` déjà testé en vitest) : tranche C dédiée si
  le viewer devient critique.

---

## Couche B — vitest : le mapping donnée → affichage

Cible : la logique front PURE, exécutée en jsdom sans navigateur ni backend (msw pour mocker l'API).

- [ ] **T8 — `useEngineAPI` (hook loué avec renderHook + msw)** :
  - `eligibleUnitIds` = exactement le pool de la phase courante (move/shoot/charge/fight) — c'est
    LA garantie « seules les unités activables ont le cercle vert » côté front.
  - `movePreview`/`targetPreview`/`attackPreview` alimentés/vidés aux bons moments ;
    normalisation `normalizeMaskLoopsFromApi` (hash/`_unchanged` : le cache ne sert jamais un
    masque périmé).
  - Gestion d'erreur : réponse `success:false` → `setError`, pas de mutation d'état de jeu.
- [ ] **T9 — utils critiques non couverts** : `probabilityCalculator` (probas de dégâts du tooltip
      vs calcul exact), `boardClickHandler` (routage clic → action selon phase/mode),
      `movePreviewFootprintMaskLoops` (déjà partiel), helpers charge/fight.
- [ ] **T10 — composants DOM non-PIXI** : HUD (phase, tour, joueur, VP), menus d'armes du tir
      (quantités, max, unassign), bandeau fight, modales hazard — via @testing-library/react,
      assertions sur le DOM réel.

---

## Couche C — Playwright : le rendu et l'interaction réels

PIXI dessine dans un canvas : le DOM ne contient PAS les cercles verts ni les previews. Deux
prérequis à implémenter dans le front (gardés par un flag, ex. `VITE_TEST_HOOKS=1`, jamais actifs
en build normal) :

### T11 — Hooks de test front (prérequis)
- [ ] `window.__W40K_TEST__` exposant l'état RENDU (pas l'état API) : par unité, le fait qu'un
      cercle vert est dessiné (`renderGreenActivationCircle` effectivement appelé, `UnitRenderer.tsx:1475`),
      les hexes de preview peints, le mode courant (`squadModelShoot`, …), la sélection, les positions
      écran des figurines (pour cliquer juste sur le canvas).
- [ ] `data-testid` sur toute l'UI DOM (boutons de phase, menus d'armes, HUD, modales).
- [ ] Helper de clic board : conversion hex → coordonnées écran exposée par le hook de test
      (le test clique sur le canvas aux coordonnées réelles, PAS en dispatchant des événements
      synthétiques internes — on teste la vraie chaîne hit-test PIXI).

### T12 — Scénarios E2E (Chromium ; backend réel spawné sans reloader, partie `pvp_test`)
- [ ] Login → lancement PvP test → board affiché (canvas non vide, 41 unités rendues).
- [ ] **Cercles verts** : ensemble des unités cerclées == pool backend, à CHAQUE phase, y compris
      après chaque activation/skip (le hook de test lit ce qui est dessiné, l'API dit ce qui doit l'être).
- [ ] **Preview move** : clic unité éligible → hexes peints == `valid_move_destinations_pool`,
      masque affiché ; clic destination → figurine déplacée à l'écran ; clic droit → annulation.
- [ ] **Preview tir** : activation → cibles qui blinkent == `valid_targets` du LoS overview ;
      cône LoS WASM affiché ; menu d'armes conforme ; résolution → HP bars mises à jour.
- [ ] Charge (avec `charge_roll_override` posé via l'UI debug si exposé, sinon via API avant le clic),
      fight (pile-in par figurine à la molette, attribution, consolidation) — chaque étape vérifiée
      visuellement via le hook + API.
- [ ] Rewind/playback : restore d'un snapshot → le board re-rend l'état restauré.
- [ ] **Assertions scene-graph PIXI (mode principal, PAS le screenshot)** : le hook de test expose
      une lecture du stage PIXI (par unité : cercle vert présent/couleur/épaisseur, hexes de preview
      peints, HP bar, blink actif). Déterministe, rapide, diff lisible — c'est lui qui vérifie
      « ce qui est dessiné == ce que dit l'API » à chaque étape des scénarios.
- [ ] **Régression visuelle (complément minimal)** : screenshots `toHaveScreenshot` sur ~10 états
      canoniques SEULEMENT (board initial, preview move, tir, mêlée, fin de partie) — seul filet pour
      les bugs que le scene-graph ne voit pas (z-order effectif, alpha, shaders). Fragile par nature :
      seuil de tolérance calibré, rendu fixé (fenêtre fixe, `deviceScaleFactor:1`, fonts embarquées),
      à ne PAS généraliser au-delà de ces ~10 états.
- [ ] Console : tout `console.error`/exception non attendu pendant un scénario = FAIL.

### T13 — Orchestration et CI
- [ ] `scripts/front_test_all.sh` : couche A (exit code) → couche B (`npm run test:run`) → couche C
      (`npx playwright test`), chacune avec son propre serveur backend éphémère (ports dédiés,
      `use_reloader=False`), token via `--token-from-db`.
- [ ] Nettoyage garanti (trap) : aucun process orphelin, aucune écriture dans `config/users.db`
      ni `ai/models/`.
- [ ] Rapport unique : total PASS/FAIL par couche + screenshots des échecs Playwright.

---

## Matrice de couverture — les 58 actions du front

Vocabulaire complet relevé dans `useEngineAPI.ts` (`action: "..."`). Une action sans tranche = trou
de couverture. État : ✅ testée (T1/T2/T3/T4/T5/T6/T7b faits), sinon tranche cible. Les cases annotées
« inatteignable / mode inaccessible » sont des trous de DONNÉES (aucune unité du roster ne
déclenche la règle), pas des oublis : cf. le détail dans la tranche correspondante.

NB : `move_squad_unplaced_destinations` (pools de toutes les figs non posées en un appel,
`api_server.py:2497`) manque à cette liste — à couvrir en T3 également.

| Action | Tranche | Action | Tranche |
|---|---|---|---|
| `activate_unit` (move) | ✅ T1 | `squad_shoot_activate` | ✅ T1 |
| `move` | ✅ T1 | `squad_shoot_los_overview` | ✅ T1 |
| `skip` | ✅ T1 | `squad_shoot_cancel` | ✅ T1 |
| `advance_phase` | ✅ T1 | `squad_shoot_select_model` | ✅ T4 |
| `advance` | ✅ T3 | `squad_shoot_assign_weapon_qty` | ✅ T4 |
| `wait` | T3 | `squad_shoot_weapon_qty_max` | ✅ T4 |
| `preview_move_plan` | ✅ T3 | `squad_shoot_unassign` | ✅ T4 |
| `move_model_destinations` | ✅ T3 | `squad_shoot_unassign_weapon` | ✅ T4 |
| (hors liste) `squad_shoot_assign_weapon` | ✅ T4 | (hors liste) `squad_shoot_unassign_weapon_qty` | ✅ T4 |
| `commit_move_plan` | ✅ T3 | `squad_shoot_validate` | ✅ T4 |
| `left_click` | T3 | `squad_shoot_allocate_model` | ✅ T4 |
| `right_click` | T3/T5 | `move_after_shooting` | T4 — inatteignable (aucune unité ne porte la règle) |
| `end_phase` | T3 | `shoot` | hors périmètre (chemin gym) |
| `deploy_unit` | T3a | `charge` | ✅ T5 |
| `deploy_preview` | T3a | `charge_plan_state` | ✅ T5 |
| `deploy_generate_formation` | T3a | `commit_charge_plan` | ✅ T5 |
| `deploy_model_destinations` | T3a | `charge_autoplace` | ✅ T5 |
| `deploy_squad_destinations` | T3a | `take_to_skies` | T5 |
| `deploy_commit` | T3a | `force_charged` | T5 |
| `change_roster` | T3a | `fight` | ✅ T6 |
| `select_rule_choice` | T2b | `skip_fight` | ✅ T6 |
| `force_battle_shock` | T2b/T7 | `squad_fight_assign` | ✅ T6 |
| `pile_in_plan_state` | ✅ T6 | `squad_fight_assign_weapon` | T6 (variante par arme) |
| `pile_in_autoplace` | ✅ T6 | `squad_fight_validate` | ✅ T6 |
| `commit_pile_in_plan` | ✅ T6 | `squad_fight_manual_alloc` | ✅ T6 |
| `end_pile_in` | ✅ T6 | `squad_hazard_allocate_model` | T6 — aucune arme [HAZARDOUS] rencontrée |
| `consolidation_plan_state` | ✅ T6 | `hazard_confirm` | T6 — idem |
| `consolidation_select_target` | T6 — mode inaccessible si engagée (12.08) | `end_consolidation` | ✅ T6 |
| `consolidation_select_objective` | T6 — idem | `cancel_consolidation` | T6 — idem |
| `consolidate_autoplace` | ✅ T6 | `endless_duty_status` | hors périmètre |
| `commit_consolidation_plan` | ✅ T6 | `endless_duty_commit` | hors périmètre |

## Ordre de réalisation conseillé et coûts

| Étape | Contenu | Coût estimé | Valeur |
|---|---|---|---|
| ~~T2-T3~~ | ✅ FAIT — invariants + move escouade/advance/fall-back (API) | faible | haute — cœur du jeu |
| ~~T5-T6~~ | ✅ FAIT — charge + fight (API) | moyen | haute — zone à bugs historique |
| ~~T4~~ | ✅ FAIT — shoot par arme/figurine + unités cachées (API) | moyen | haute |
| ~~T7b~~ | ✅ FAIT — fuzzing par invariants (1 anomalie trouvée au 1er run) | faible (réutilise T2) | très haute — couvre l'imprévu |
| T2b, T3a | Command/réactions + déploiement (API) | moyen | moyenne |
| T7 | Snapshots/save/fin de partie (API) | faible | moyenne |
| T8-T10 | vitest hook + utils + composants DOM | moyen | moyenne |
| T11 | Hooks de test front (prérequis C) | moyen | — (infra) |
| T12 | E2E Playwright (scene-graph + ~10 screenshots) | élevé | haute — seul filet « rendu » |
| T13 | Orchestration/CI | faible | moyenne |

## Pièges connus (acquis pendant T1)
- Reloader Werkzeug : ne JAMAIS tester contre un serveur `debug=True` d'avant le fix — parties effacées.
- `pkill -f` avec un pattern présent dans sa propre ligne de commande se tue lui-même (utiliser
  `pgrep -af "motif[x]"`).
- Le serveur spawné par le harnais meurt avec lui (atexit) — pour sonder à la main, lancer un serveur
  séparé.
- Sémantique HP escouade/leader attaché (cf. §0.2) — toute assertion HP doit passer par `models_cache`.
- Les checks « composition de pool » doivent rester ⊆ (sous-ensemble) tant que la règle exacte
  d'éligibilité n'a pas été lue dans le PDF correspondant — l'égalité stricte exige la référence règle.
