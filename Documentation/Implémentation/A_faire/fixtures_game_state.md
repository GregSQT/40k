# Les fixtures de test fabriquent un `game_state` que la production ne produit jamais

**Ouvert le 2026-07-29.** Backlog — inventaire mesuré, chantier NON commencé.
Décision d'architecture en attente (voir §4) : elle appartient à l'utilisateur.

---

## 1. Comment ce sujet est apparu

Le commit `7addf91f` (« appliquer 10.05 apres advance ») a ajouté dans
`shared_utils._advance_blocks_weapon` une lecture obligatoire :

```python
if squad_id not in require_key(game_state, "units_advanced"):
```

**21 tests** de `test_squad_shoot_declaration.py` sont passés au rouge d'un coup, tous sur le même
`ConfigurationError: Required key 'units_advanced' is missing`.

Le réflexe naturel — assouplir la lecture en `.get("units_advanced", set())` — aurait été le pire
choix possible : il aurait fait passer **toutes** les unités pour « n'ayant pas avancé », donc
**désactivé 10.05** au lieu de le vérifier, en silence. `require_key` ne s'était pas trompé : il
venait de révéler que la fixture `_make_gs` construisait un `game_state` **impossible en
production**. Le moteur, lui, pose toujours la clé (`w40k_core`, dict d'init, 63 clés).

Correctif appliqué le jour même : `_make_gs` pose `units_advanced: set()`. 21 tests réparés.
**Ce document traite la cause, pas ce symptôme.**

## 2. L'inventaire (mesuré à l'AST, 2026-07-29)

Référence : le dict d'init du `game_state` dans `w40k_core` — **63 clés**, dont **19 d'état de
tour** (`units_*`, `advance_rolls`, `reactive_*`, `last_move_*`, `reaction_window_active`).

Balayage de `tests/` : tout dict littéral portant `units` + `phase` (ou `units` + `board_cols`).

> **62 `game_state` littéraux, répartis dans 51 fichiers.
> AUCUN ne pose les 19 invariants. La médiane est à 17 invariants manquants sur 19.**

| Invariant manquant | Fixtures concernées |
|---|---|
| `advance_rolls`, `units_shot_previous_turn` | **62** (toutes) |
| `units_took_to_skies_charge` | 59 |
| `last_move_cause`, `last_move_event_id`, `reactive_mode`, `reactive_decision_mode`, `units_attacked`, `units_took_to_skies` | 56 |
| `reaction_window_active`, `reactive_decision_payload`, `reactive_macro_order_current_window`, `units_reacted_this_enemy_turn` | 55 |
| `units_shot` | 52 |
| `units_cannot_charge` | 50 |
| `units_charged` | 44 |
| `units_fled` | 40 |
| `units_advanced`, `units_moved` | 37 |

Fichiers les plus exposés : `test_movement_pool_build.py` (4 fixtures, 19/19 manquants),
`test_phase_start.py` (3), `test_phase_transitions.py` (3), `test_engine_turn_loop.py` (2),
`test_model_value_per_figurine.py` (2), `test_move_budget_geodesic.py` (2),
`test_fly_2103_conformity.py` (2).

## 3. Le vrai danger n'est pas le crash

Comment la **production** lit chacune de ces clés décide de ce qui arrive à une fixture qui l'omet :

| Mode de lecture en production | Ce qui se passe | Exemples |
|---|---|---|
| `require_key(...)` ou `gs["..."]` | **erreur immédiate** — le test devient rouge et le dit | `units_advanced` (10 `require_key`), `units_fled` (7), `units_cannot_charge` (3) |
| `.get("...", <défaut>)` **sans aucun `require_key`** | **silence** — le test observe un comportement faux et reste **vert** | `units_shot_previous_turn` (4 `.get`), `units_attacked` (1) |

C'est le second cas qui justifie ce chantier. L'épisode `units_advanced` s'est **bien** terminé
précisément parce que la lecture était bruyante. À l'inverse, `units_shot_previous_turn` est absent
des **62** fixtures et n'est lu que par `.get` avec défaut : **aucun test ne peut aujourd'hui
observer un comportement correct qui en dépend**, et rien ne le signalera.

> ⚠️ Nuance à ne pas gommer : plusieurs clés ont **les deux** modes de lecture selon le chemin
> (`units_charged` : 1 `.get` mais 8 accès directs ; `units_moved` : 2 et 10). Pour celles-là le
> silence est **partiel** — il dépend du chemin emprunté. Ne pas les classer « sûres ».

## 4. La décision d'architecture — À ARBITRER AVANT LA PREMIÈRE LIGNE

**Un constructeur unique, ou un socle d'invariants que chaque fixture spécialise ?**

Les 62 fixtures divergent beaucoup (plateaux, phases, rosters, caches pré-construits). Un builder
unique assez riche pour toutes les couvrir **deviendrait un second moteur à maintenir**, et sa
dérive par rapport au vrai `game_state` reproduirait le problème un cran plus loin.

La piste à instruire en premier : un socle minimal qui pose **les 19 invariants d'état de tour et
rien d'autre**, que chaque fixture fusionne avec son propre littéral. Faible surface, pas de
duplication du moteur. Mais c'est une piste, **pas une décision prise**.

Question ouverte associée : ce socle doit-il **dériver** de l'init de `w40k_core` (garantie
d'alignement, couplage fort) ou **répliquer** la liste (indépendance, dérive possible) ? Un test
comparant les deux ensembles de clés réglerait la dérive sans le couplage — à évaluer.

## 5. Emplacement

`tests/unit/engine/` a déjà `conftest.py`, `_config_helpers.py`, `_roll_helpers.py` : l'ossature
existe. **5** des 62 fixtures sont hors `tests/unit/engine/` (`tests/unit/ai/test_evaluation_bots.py`,
`tests/unit/ai/test_step_log_weapon_rule_tokens.py`, `tests/unit/services/test_api_endpoints.py`,
`tests/unit/services/test_endless_duty_value_baseline.py`,
`tests/unit/services/test_api_integration.py`) — la portée du socle doit être décidée en
conséquence, mais le gros du parc est bien sous `tests/unit/engine/`.

## 6. Ce qui n'a PAS été instruit

- **Combien de tests observent aujourd'hui un comportement faux** à cause d'un invariant manquant
  lu en `.get`. L'inventaire dit qui est exposé, **pas** qui est effectivement faux. C'est le
  vrai travail, et il ne peut pas être mécanique : il demande de lire ce que chaque test prétend
  vérifier. **Ne pas confondre « exposé » et « cassé ».**
- Si des fixtures omettent des clés **hors** des 19 d'état de tour (les 44 autres de l'init).
- Les fixtures qui ne construisent pas un dict littéral (usines, `conftest`, factories) — le
  balayage ne les voit pas. Le chiffre 62 est un **plancher**, pas un total.
