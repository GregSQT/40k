# OVERRUN FIGHT (12.06) — à implémenter en par-figurine

Rédigé le 2026-07-16, en marge du fix `squad_fight` (V11 T6). **Non implémenté dans le pipeline
squad gym.** Une implémentation par-ANCRE existe dans le backend, mais elle relève du modèle
condamné (cf. §3) — il ne faut PAS la réutiliser telle quelle.

---

## 1. La règle (source : `Documentation/40k_rules/12 Fights pahse.pdf`, lu le 2026-07-16)

### 12.04 — éligibilité au combat

> A unit is eligible to fight if it has not already been selected to fight this phase and one or
> more of the following apply to it:
> - It is engaged, or it was engaged at the start of this step.
> - **It made a charge move this turn.**

> **WHEN A UNIT IS SELECTED TO FIGHT** — Each time a unit is selected to fight, select one fight
> type that unit is eligible to make, and resolve it with that unit.

Deux types de fight existent (« Fight types are marked with this icon » dans le PDF) :

### 12.05 — NORMAL FIGHT
> ELIGIBLE IF: Your unit is engaged.
> EFFECT: Your unit fights as described in Making Attacks (04).

### 12.06 — OVERRUN FIGHT
> ELIGIBLE IF: Your unit is unengaged, or was unengaged at the start of the Fight step but became
> engaged during the Fight phase.
> EFFECT: Your unit **can** make one additional pile-in move, then fights as described in
> Making Attacks (04).

**Points de règle qui pilotent l'implémentation :**

1. **Le pile-in additionnel est OPTIONNEL** (« **can** make »). Cohérent avec 12.02 (« with all of
   their eligible units **they choose to move** ») et l'encart du PDF : « Yes, you have to fight
   with all units that can, but **you don't have to pile in or consolidate** with a unit if you
   don't want to ». → **Ne pas l'implémenter ne viole aucune règle** : l'unité résout alors un
   fight « à vide » (0 attaque). C'est l'état actuel du gym, et il est LÉGAL.
2. **Combattre est obligatoire, pas bouger** : une unité éligible DOIT être sélectionnée pour
   combattre (« you have to fight with all units that can »), même si elle finit à 0 attaque.
3. **Ce pile-in est ADDITIONNEL** : il s'ajoute à celui de l'étape groupée 12.02 (limitée à
   « Each unit cannot make more than one pile-in move during **this step** » — l'étape PILE IN).
   Deux pile-in dans la phase sont donc légaux : un en 12.02, un en 12.06.
4. **L'encart OVERRUN FIGHTS du PDF** : « When a unit makes an overrun fight, its models can be
   moved such that enemy units that were unengaged become engaged. Such enemy units **become
   eligible to fight this phase** (and may even be able to fight next if they are Fights First
   units). » → conséquence à ne pas oublier : un overrun peut **rendre un ennemi éligible** et
   donc l'ajouter au pool d'activation en cours de phase.

### Les deux exemples du PDF

- **p.1 (START OF FIGHT PHASE)** : le MONSTER rouge a chargé, mais a détruit sa cible de charge
  dès la phase de charge (stratagème Crushing Impact 15.06). Il est donc **unengaged** et reste
  éligible au pile-in et au combat.
- **p.3 (OVERRUN FIGHT)** : une unité rouge Fights First était engagée avec un TRANSPORT. Le
  MONSTER détruit le transport ; l'unité embarquée fait un emergency disembark et se retrouve
  unengaged. L'unité rouge « is unengaged, but **was engaged with the TRANSPORT at the start of
  the Fight step**, so can make an overrun fight. It first makes a pile-in move to engage the unit
  that disembarked, then fights, destroying two enemy models. »

### Le cas concret qui nous concerne (= le bug corrigé)

Une escouade charge (→ éligible 12.04). Sa cible meurt **avant son activation**, tuée par un autre
combat de la phase. Elle n'est plus engagée → **Normal fight impossible** (12.05 exige engaged).
Son seul type possible est **l'overrun**. C'est la situation exacte de
`bug_squad_fight_mask_mismatch.md` (squad 3, `in_er=False`, `units_charged={'3'}`).

---

## 2. État actuel du code (vérifié le 2026-07-16)

| Élément | Emplacement | Modèle |
|---|---|---|
| `fight_v11_is_overrun_eligible(gs, unit)` | fight_handlers ~L2876 | prédicat pur, réutilisable |
| `_fight_v11_auto_overrun_pile_in(gs, unit, config)` | fight_handlers ~L3427 | **par-ANCRE — condamné** |
| Appel côté auto V11 | `_fight_v11_auto_step`, ~L3482-3487 | overrun ssi non engagée |
| Appel côté **PvP manuel** | `_fight_v11_manual_step`, ~L6218-6220 | fight type **choisi par le joueur** (`action["fight_type"] == "overrun"`) |
| Snapshot `engaged_at_fight_step_start` | posé par `fight_v11_enter_fight_step` ~L3146 | **absent du gym** (cf. §4) |
| Pipeline squad gym | `w40k_core._process_squad_action`, branche `squad_fight` | **overrun NON implémenté** |

### Le prédicat d'éligibilité (réutilisable tel quel)

```python
def fight_v11_is_overrun_eligible(game_state, unit) -> bool:
    engaged_now = _fight_v11_engaged_now(game_state, unit)
    if not engaged_now:
        return True                      # ← ne lit PAS le snapshot
    snapshot = require_key(game_state, "engaged_at_fight_step_start")   # ← require_key !
    was_engaged_at_start = bool(snapshot.get(str(require_key(unit, "id")), False))
    return (not was_engaged_at_start) and engaged_now
```

⚠️ **Piège** : `require_key` sur le snapshot n'est atteint QUE si l'unité est engagée maintenant.
Le pipeline squad gym ne pose jamais ce snapshot (§4) → il faut impérativement écrire
`if not _fight_v11_engaged_now(...) and fight_v11_is_overrun_eligible(...)` (dans CET ordre), sinon
`KeyError`. L'expression est logiquement équivalente à celle du chemin auto V11
(`fight_v11_is_overrun_eligible(...) and not _fight_v11_engaged_now(...)`), seul l'ordre
d'évaluation change.

---

## 3. Pourquoi ce n'est PAS implémenté (et ce qu'il ne faut pas faire)

**Décision utilisateur du 2026-07-16 : le pile-in de référence est celui du mode PvP, le
PAR-FIGURINE.** Le modèle par ANCRE d'unité (`_fight_apply_pile_in_move` →
`translate_squad_to_destination`, translation rigide de l'escouade) est **condamné**.

Or `_fight_v11_auto_overrun_pile_in` est **entièrement par-ancre** :

```python
def _fight_v11_auto_overrun_pile_in(game_state, unit, config):
    within = pile_in_targets_within_range(game_state, unit)      # ennemis ≤ 5"
    if not within: return
    dests = pile_in_move_destinations_12_03(game_state, unit, within)   # BFS par ancre
    if not dests: return
    pc, pr = _ai_select_pile_in_destination(game_state, unit, dests, 0, within)
    try:
        _fight_apply_pile_in_move(game_state, unit, pc, pr)       # translation RIGIDE
    except ValueError:
        pass                                                      # ← masque un mismatch, cf. autre doc
```

**⚠️ Le PvP est HYBRIDE sur ce point** : son pile-in normal (12.02) est par-figurine
(`pile_in_autoplace_plan`, `_fight_pile_in_model_plan_state`), mais son overrun (12.06) appelle la
version par-ancre ci-dessus. Donc **« copier le PvP » ne donne AUCUNE réponse pour l'overrun** :
**l'overrun par-figurine n'existe nulle part, il est à ÉCRIRE**.

### Ce qui a été fait puis retiré

Un overrun avait été greffé dans le gym (`_process_squad_action`, branche `squad_fight`) en
appelant `_fight_v11_auto_overrun_pile_in`. **Retiré le 2026-07-16** car il injectait une
translation rigide dans un pipeline par-figurine — le modèle condamné.

Mesure à connaître : sur `MELEE_SCENARIO` (2v2), seeds 1-5 × 400 steps, avec cet overrun actif,
`_fight_apply_pile_in_move` a été appelé **0 fois** → l'overrun ne s'est jamais déclenché (il
exige un AUTRE ennemi à ≤5"). **Ne pas en conclure qu'il est inutile** : sur un roster réel avec
plus d'unités, le cas se présentera (position utilisateur, 2026-07-16). C'est une raison de le
faire proprement, pas de l'oublier.

---

## 4. Obstacle bloquant : le gym n'entre pas dans la machine V11

Instrumenté sur un épisode gym complet (`MELEE_SCENARIO`, seed 1) — en phase fight, l'état est
**invariablement** :

```
(fight_subphase='pile_in', snapshot_present=False, nb_selected_to_fight=0)
```

Le gym appelle bien `fight_phase_start` (qui initialise la machine V11 et entre en étape PILE IN),
puis **n'en sort jamais** : il déroule son propre pipeline squad. Conséquences pour l'overrun :

- `engaged_at_fight_step_start` **n'est jamais posé** → le critère 12.06 « was unengaged at the
  start of the Fight step but became engaged during the Fight phase » est **inapplicable en gym**.
  Seule la moitié « is unengaged » du prédicat est évaluable.
- Le snapshot doit être pris **APRÈS le pile-in groupé des deux joueurs** (12.02 → 12.04). Le gym
  pile-in escouade par escouade au moment de son activation → **poser le snapshot depuis le gym le
  prendrait au mauvais instant**. Un snapshot faux est PIRE que pas de snapshot.
- `units_selected_to_fight` reste vide (le gym utilise `units_fought`).

→ **L'overrun gym complet (les deux branches du prédicat 12.06) suppose que le pipeline squad
passe sur la machine V11** — c'est la dette V11 T6 de fond. Un overrun gym partiel (branche « is
unengaged » seulement) est possible sans ça, et couvre déjà le cas du chargeur-sans-cible.

---

## 5. Ce qu'il faut implémenter

1. **Écrire `_fight_overrun_pile_in_plan(game_state, squad_id)` en PAR-FIGURINE**, sur le modèle
   de référence PvP — même famille que `pile_in_autoplace_plan` /
   `_fight_pile_in_preview_plan` / `commit_move(plan, gs, "pile_in")`, retour
   `List[(model_id, col, row)]` comme `fight_pile_in_plan` (shared_utils ~L6769).
   - cibles = `pile_in_targets_within_range` (ennemis ≤ `pile_in_target_range` = 5", 12.03
     « Otherwise, select one or more enemy units within 5" of your unit ») ;
   - contraintes 12.03 : chaque fig bouge ≤3", finit plus proche de la cible la plus proche et
     engagée si possible ; figs en contact socle immobiles ; cohésion 03.03 ; après le move,
     l'unité doit être engagée ; chaque fig engagée au départ doit le rester ;
   - transaction atomique (retour `None` si le plan est invalide), comme `fight_pile_in_plan`.
2. **Le brancher dans les 3 chemins** (dans cet ordre de priorité) :
   - PvP manuel (`_fight_v11_manual_step` ~L6218) : remplace l'appel par-ancre ; le joueur choisit
     déjà le fight type via `action["fight_type"] == "overrun"` ;
   - auto V11 (`_fight_v11_auto_step` ~L3482) : overrun ssi non engagée ;
   - gym (`_process_squad_action`, branche `squad_fight`, APRÈS le `fight_pile_in_plan` et AVANT
     `_fight_build_valid_target_pool`) — voir le piège d'ordre d'évaluation du §2.
3. **Ne pas oublier l'encart** : un overrun peut rendre un ennemi éligible au combat (§1.4) →
   vérifier que le pool d'activation est recalculé après le move (le PvP a déjà
   `_fight_on_target_damaged` / `FIGHT_CTX` pour la mort ; l'entrée en engagement est un autre
   déclencheur).
4. **Supprimer** `_fight_v11_auto_overrun_pile_in` et son `except ValueError: pass` une fois les
   3 chemins migrés (cf. `bug_pile_in_bfs_clearance_mismatch.md`).

---

## 6. Test retiré (à restaurer et adapter au modèle par-figurine)

Ce test existait dans `tests/unit/engine/test_squad_fight_target_parity.py` et vérifiait que le
gym tentait l'overrun. Il a été retiré avec les 3 lignes. **Vérifié : il échoue (`AssertionError`)
si l'appel overrun est absent** — c'est donc un verrou valide. À réintroduire en ciblant la
nouvelle fonction par-figurine.

```python
def test_unengaged_squad_attempts_overrun_pile_in(monkeypatch, melee_scenario_file):
    """OVERRUN 12.06 : une escouade non engagée au moment de son fight tente de se réengager
    (pile-in d'overrun) avant de résoudre."""
    from engine.phase_handlers import fight_handlers

    eng = _engine(melee_scenario_file, seed=1)
    gs = eng.game_state
    gs["phase"] = "fight"
    squad_id = next(iter(gs["units_cache"]))
    our_player = int(gs["units_cache"][squad_id]["player"])
    gs["current_player"] = our_player
    gs["units_charged"] = {squad_id}       # éligible 12.04 sans être engagée
    gs["units_fought"] = set()

    calls = []
    monkeypatch.setattr(fight_handlers, "_fight_v11_engaged_now", lambda _gs, _u: False)
    monkeypatch.setattr(
        fight_handlers, "_fight_v11_auto_overrun_pile_in",
        lambda _gs, u, _c: calls.append(str(u["id"])),
    )
    eng._process_squad_action({"action": "squad_fight", "squad_id": squad_id})
    assert calls == [squad_id]
```

Un second test devra couvrir le cas **fonctionnel** (et pas seulement l'appel) : escouade non
engagée + un ennemi à ≤5" ⇒ après `squad_fight`, l'escouade est engagée ET a porté des attaques.
Le scénario mêlée 2v2 ne le produit pas naturellement (0 déclenchement mesuré) → état à forcer.

---

## 7. Liens

- `Documentation/Implémentation/Implémenté/bug_squad_fight_mask_mismatch.md` — le bug qui a exposé ce
  trou (chargeur dont la cible meurt) ; **corrigé** côté gym (fight à vide au lieu du crash).
- `Documentation/Implémentation/A_faire/bug_pile_in_bfs_clearance_mismatch.md` — le mismatch
  cellules/clearance du BFS par-ancre (mesuré, fix reverté) ; disparaîtra avec la migration.
- `Documentation/Implémentation/V11_agent_rework.md` §T6 — la dette « le gym n'emprunte pas la
  machine V11 », prérequis de l'overrun complet.
