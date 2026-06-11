# Plan de migration — Phase Fight V10 → V11 (révisé + durci)

> **Statut** : plan révisé après revue expert (code + PDF relus) puis durci (4 points), implémentation non démarrée.
> Ce fichier est le **plan de référence** ; il intègre les corrections de la revue (ex-`phase_fight_v11_v2.md`, désormais redondant)
> et les 4 durcissements : pool de consolidation dynamique (décision #9), critères de validation par bloc explicites,
> portée objectif à chiffrer (PDF 14), périmètre exact de la vérification « Fights Last ».
> **Pas de rétrocompatibilité** requise.
> **Source de vérité règles** : `Documentation/40k_rules/` (PDF). Toute règle citée ci-dessous a été lue dans le PDF correspondant.

---

## 1. Objectif

Adapter l'implémentation de la phase de combat (actuellement V10) aux règles V11.
La phase V11 se résout selon **5 étapes** (PDF `12 Fights pahse.pdf`) :

```
1. START OF FIGHT PHASE      (12.01)
2. PILE IN                   (12.02 / 12.03)   ← groupé, actif puis adverse
3. FIGHT                     (12.04 → 12.06)   ← Fights First puis Remaining
4. CONSOLIDATE               (12.07 / 12.08)   ← 3 modes, peut déclencher des combats IN-PLACE
5. END OF FIGHT PHASE        (12.09)
```

---

## 2. Définitions règles V11 confirmées (lues dans les PDF)

| Notion | Règle | Définition | Conséquence code |
|---|---|---|---|
| **engaged** | 03.04 | Figurine à **2" horizontal / 5" vertical** d'une figurine ennemie (vertical sans objet sur board hex 2D). | = `engagement_zone: 2` dans `config/game_config.json` (déjà implémenté via `get_engagement_zone`). **Aucun changement.** |
| **active player** | 01.03 | « While it is a player's turn, that player is the active player ». | Les 3 étapes (12.02, 12.04, 12.07) commencent par le **joueur actif**. |
| **Fights First** | **11.04 + 24.13** | Mécanisme unique : l'**ability Fights First (24.13)**. 11.04 AFTER MOVING : « Until the end of the turn, each model in your unit has the Fights First ability (24.13) » — le **charge move effectué** (pas la déclaration) confère l'ability **jusqu'à la fin du tour**. 24.13 : « While every model in a unit has this ability, that unit is a Fights First unit ». | Modéliser comme **grant temporaire de l'ability** : `is_fights_first(unit) = unit_has_rule_effect(unit, "fights_first")`, où la charge ajoute l'effet jusqu'à fin de tour. L'extension datasheet devient triviale (ability permanente). Vérifié : `units_charged` n'est alimenté qu'après un charge move effectué (charge_handlers.py:2416) → utilisable comme source du grant. |
| **Fights Last** | — | **Absent des core abilities** (vérifié : 24.01→24.38 entier). Stratagèmes / règles de faction : **hors scope moteur, non vérifiés**. | Ne rien construire (conclusion valide pour le périmètre du moteur actuel — pas de stratagèmes implémentés). |
| **Pile-in move** | 12.03 | Max **3"**. Éligible si : engagée **maintenant**, OU a fait un charge move ce tour, OU sélectionnée pour un overrun fight (12.06). BEFORE : si engagée → cibles = **toutes** les unités ennemies engagées ; sinon → le joueur **choisit** 1+ unités ennemies **dans 5"**. WHILE : figurines en contact socle ne bougent pas ; chaque figurine déplacée finit plus près de la cible la plus proche, **et engagée avec elle si possible**. **AFTER : l'unité DOIT finir engagée** (contrainte dure : si aucune destination ne rend l'unité engagée → pas de pile-in du tout) ; chaque figurine qui a commencé engagée avec une unité doit le rester avec cette unité. | Nouveau seuil **5"** (`pile_in_target_range`). Contraintes AFTER = filtres durs sur les ancres, pas une simple préférence contact. Sélection des cibles (cas non engagé) = **choix joueur** en PvP (UI) ; auto-heuristique pour l'IA. |
| **Fight : éligibilité** | 12.04 | Pas encore « selected to fight » cette phase ET (engagée, OU **était engagée au début de l'étape Fight**, OU a fait un charge move ce tour). | Snapshot `engaged_at_fight_step_start` pris au **début de l'étape 3** (donc APRÈS le pile-in groupé). L'éligibilité ne dépend **jamais** de la présence de cibles valides. |
| **Normal fight** | 12.05 | Éligible si l'unité est engagée. | Type de fight par défaut. |
| **Overrun fight** | 12.06 | Éligible si l'unité est **unengaged maintenant**, OU **était UNengaged au début de l'étape Fight** et est devenue engagée pendant la phase. Effet : **1 pile-in additionnel** (règles 12.03 complètes) puis fight. | **Nouveau** (absent V10). Le test « was unengaged » se dérive du même snapshot `engaged_at_fight_step_start` (négation). |
| **Consolidation move** | 12.08 | Max **3"**. Éligible si l'unité **was eligible to fight this phase**. 3 modes en cascade obligatoire (voir §3). | Étape groupée n°4 (actif puis adverse, 1 move/unité). Nécessite le tracking « était éligible à combattre cette phase ». **Pool évalué dynamiquement par sous-étape** (décision #9). |
| **Engaging consolidation déclenche des combats** | 12.08 | AFTER : l'unité doit être engagée avec **toutes** les unités sélectionnées. « If one or more enemy units **engaged with your unit** have not been selected to fight this phase, your opponent must select each of those units, one at a time; when each is selected, it becomes eligible to fight and **is selected to fight (12.04)** ». | Les combats déclenchés se résolvent **immédiatement, dans l'étape CONSOLIDATE** (application de « WHEN A UNIT IS SELECTED TO FIGHT », avec choix du fight type) — **pas** de retour à la machine de l'étape 3. Le déclencheur porte sur les ennemis engagés avec l'unité **après le move**, pas seulement les unités sélectionnées. Conséquence sur les fenêtres de consolidation : voir décision #9. |
| **Pile-in / consolidation optionnels** | 12 (encart) | « You have to fight with all units that can, but you don't have to pile in or consolidate ». Si on consolide, le **mode** est imposé par la cascade. | Skip par unité dans l'UI des étapes groupées. Politique IA explicite (voir décision #7). |

---

## 3. Écarts V10 → V11

| # | Sujet | V10 (actuel) | V11 (cible) |
|---|---|---|---|
| 1 | **Ordre du PILE IN** | Par unité, juste avant que l'unité combatte (`fight_pile_in_pending`, fight_handlers.py:2699-2754). | Étape groupée **n°2 avant tout combat** : tous les pile-in (actif puis adverse), 1 fois/unité, optionnel par unité. |
| 2 | **Sémantique pile-in** | Seulement si non « collé » ; cibles = palier d'ennemis les plus proches (tous ennemis confondus) ; préférence contact (soft). | Éligible si engagée / a chargé ; cibles = **toutes les unités engagées** (si engagée) ou **choix joueur parmi les ennemis dans 5"** (sinon) ; contrainte dure : **doit finir engagée**. |
| 3 | **Fights First** | Absent. Sous-phase `charging` séparée + alternance `non_active` d'abord (fight_handlers.py:230/2178). | Séquence **Resolve Fights First** → **Resolve Remaining** (12.04), machine de sélection complète (voir §5) ; statut = ability 24.13 (grant par charge, 11.04). |
| 4 | **Overrun fight** | Absent. | Nouveau type (12.06) : pile-in additionnel + fight. |
| 5 | **Consolidation — timing** | Par unité, immédiatement après ses attaques (`_fight_try_begin_consolidation_after_attacks`, appelée en fin d'activation ; chemins entremêlés avec `end_activation` / `_fight_post_process_fight_activation_result` / `_fight_consolidation_ctx`). | Étape groupée **n°4** : actif puis adverse, 1 consolidation max/unité, optionnel par unité. **Extraction complète hors de l'activation.** Pools par sous-étape **dynamiques** (décision #9). |
| 6 | **Consolidation — modes** | 2 branches (`enemy` / `objective`, fight_handlers.py:1471/1561). Branche objectif **sans gate de distance** (consolide vers un objectif à n'importe quelle distance) ; cible = hex marqueur/médiode. | 3 modes (Ongoing / Engaging / Objective) en cascade obligatoire, gates **3"** pour Engaging et Objective ; Objective vise « **within range** of the objective » (portée de contrôle, PDF 14 — à chiffrer, décision #2) ; Engaging déclenche des combats in-place. |
| 7 | **Éligibilité fight** | Pools construits sur `_fight_build_valid_target_pool` (a des cibles en zone d'engagement, fight_handlers.py:294/324/2936). | Éligibilité 12.04 (engagée / était engagée au début du step / a chargé), **indépendante de la présence de cibles** — une unité éligible sans cible est quand même sélectionnée (cas overrun typique : a chargé, cible détruite). |

### Les 3 modes de consolidation (12.08)

Cascade obligatoire (si on choisit de consolider) :
- **Ongoing** : si l'unité est engagée → mode imposé. Cibles = **toutes** les unités ennemies engagées. WHILE : figurines en contact socle ne bougent pas ; les autres finissent plus près de l'unité sélectionnée la plus proche, et engagées avec elle si possible. AFTER : chaque figurine qui a commencé engagée avec une unité doit le rester.
- **Engaging** : sinon, si dans **3"** d'1+ unités ennemies → mode imposé. Sélectionne 1+ **de ces unités (dans 3")**. AFTER : doit finir engagée avec **toutes** les sélectionnées. Puis : tout ennemi engagé avec l'unité (après le move) non encore « selected to fight » → l'adversaire les sélectionne une à une, chacune **est sélectionnée pour combattre immédiatement** (12.04, choix du fight type inclus). Edge cases actés :
  - une telle unité, unengaged au début de l'étape Fight, satisfait 12.06 → peut choisir un **overrun fight** (pile-in additionnel) pendant l'étape Consolidate ;
  - une telle unité devient « selected to fight this phase » → elle satisfait l'éligibilité consolidation 12.08 ; sa propre fenêtre de consolidation dépend de la sous-étape (voir décision #9).
- **Objective** : sinon, si dans **3"** d'1+ objectifs → mode imposé. Sélectionne 1 de ces objectifs. WHILE/AFTER : chaque figurine finit **à portée de contrôle** de l'objectif si possible, sinon plus près.
- Éligibilité : unité qui **était éligible à combattre cette phase** (voir tracking §6) — pas « est engagée ».

---

## 4. Décisions actées

1. **Ordre** : joueur **actif d'abord** pour les 3 étapes (12.02/12.04/12.07 ; V11 > AI_TURN ; AI_TURN mis à jour séparément).
2. **Conformité** : V11 respectée à **100%**, sauf limitation technique explicitement justifiée. Limitation actée : « within range of the objective » approximé sur board hex par la portée de contrôle en hexes — **valeur non chiffrée à ce stade, à lire dans le PDF 14 au Bloc 5** — documenter dans le code.
3. **Engaging consolidation** : implémentation **complète**, résolution des combats déclenchés **in-place dans l'étape Consolidate** (y compris overrun 12.06 si applicable).
4. **Fights First** : modélisé comme **ability 24.13** ; le charge move confère un **grant temporaire jusqu'à fin de tour** (11.04). Pas d'ability datasheet pour l'instant (absente de `unit_rules.json`) ; le jour où elle existe, `is_fights_first` fonctionne sans changement.
5. **Retour Remaining → Fights First (12.04)** : implémenté pour conformité, mais **actuellement inatteignable** (FF = charge uniquement ⇒ toutes les unités FF sont éligibles dès le début de l'étape et sélectionnées pendant Resolve Fights First). Ne devient testable qu'avec l'ability datasheet — pas de test bloquant dessus.
6. **IA / RL** : configuration actuelle conservée (V1 auto-heuristique). Pile-in, overrun, modes de consolidation gérés automatiquement par le handler ; `action_space` inchangé (seule action fight = `activate+fight`). Décisions apprises = scope V2.
7. **Politique IA pour les moves optionnels** : pile-in auto = toujours si possible (maximise l'engagement) ; consolidation auto = Ongoing et Objective toujours si possible ; **Engaging seulement si aucun ennemi déclenché ne peut riposter** (sinon skip) — heuristique conservatrice V1, apprise en V2.
8. **Réentraînement** : acté — modèles `.zip` obsolètes après migration ; non modifiés (règle CLAUDE.md), réentraînés après.
9. **Pool de consolidation dynamique (12.07/12.08)** : l'éligibilité consolidation est évaluée **au début de chaque sous-étape** (actif, puis adverse) et **re-vérifiée à chaque sélection** (les fights in-place tuent des unités et changent les engagements) — jamais figée à l'entrée du step 4. Asymétrie actée, conséquence directe de « l'actif résout tous ses moves d'abord » :
   - unité **adverse** déclenchée (selected to fight) pendant les Engaging consolidations de l'actif → sa fenêtre (sous-étape adverse) n'est pas encore passée → elle **peut** consolider ;
   - unité de l'**actif** déclenchée pendant les Engaging consolidations de l'adversaire → sa sous-étape est passée, aucune règle ne prévoit de retour → **pas** de consolidation pour elle.
   Dans tous les cas : 1 consolidation max/unité/étape (`consolidation_done`).

---

## 5. Machine d'état cible

```
START
  → PILE_IN        (groupé : actif puis adverse ; 1 pile-in/unité, optionnel ;
                    éligibilité = engagée OU a chargé — PAS le bullet overrun,
                    qui ne sert qu'au pile-in additionnel de 12.06 en étape FIGHT)
  → [snapshot engaged_at_fight_step_start]
  → FIGHT          (machine de sélection 12.04, voir ci-dessous)
  → CONSOLIDATE    (groupé : actif puis adverse ; 1 consolidation/unité, optionnel ;
                    pools de sous-étape DYNAMIQUES — décision #9 ;
                    Engaging → combats déclenchés résolus IN-PLACE dans cette étape)
  → END
```

### Machine de sélection de l'étape FIGHT (12.04, exhaustive)

État : `fight_step` (`fights_first` | `remaining`) + `fight_selector` (joueur dont c'est le tour de sélectionner).

- **Resolve Fights First Combats** : `fight_selector` initialisé au joueur **actif**. Le sélectionneur choisit une unité amie **Fights First éligible** → elle est « selected to fight ». Si impossible :
  - s'il n'existe **plus aucune** unité FF éligible (des deux côtés) → passage à Remaining, **ce même joueur** sélectionne en premier ;
  - sinon (l'adversaire a encore des FF éligibles) → l'**autre joueur** sélectionne (le même joueur peut donc sélectionner plusieurs fois de suite).
- **Resolve Remaining Combats** : commence par **le joueur qui a fait passer la séquence à cette étape** (pas forcément l'actif). Même mécanique de handoff. Si plus aucune unité éligible → fin de l'étape FIGHT.
- Après chaque fight résolu en Remaining : s'il existe des unités FF redevenues éligibles → **retour à Resolve Fights First** (sélecteur ré-initialisé au joueur actif). (Inatteignable tant que FF = charge seule, voir décision #5.)
- **« Selected to fight »** ⇒ choix d'un **fight type** éligible : Normal (12.05, engagée) ou Overrun (12.06). Sélection **obligatoire** pour toute unité éligible (« you have to fight with all units that can ») — y compris sans cible (le fight se résout alors à vide).

Remplace les sous-phases V10 : `charging` / `alternating_non_active` / `alternating_active` / `cleanup_non_active` / `cleanup_active` (et `fight_alternating_turn`).

---

## 6. Nouveaux états / constantes

**Config (`config/game_config.json`)**
- `pile_in_target_range: 5` — sélection des cibles de pile-in quand non engagée (12.03).
- `consolidation_trigger_range: 3` — gate des modes Engaging (ennemis dans 3") et Objective (objectifs dans 3") (12.08). Numériquement égal à la distance max de move mais sémantiquement distinct.
- `engagement_zone: 2` (inchangé).
- Toutes les valeurs en pouces, converties via `inches_to_subhex` comme l'existant.

**game_state (nouveaux champs)**
- `engaged_at_fight_step_start` : snapshot par unité au **début de l'étape FIGHT** (après le pile-in groupé). Sert à : éligibilité fight 12.04 (« was engaged at the start of this step ») ET overrun 12.06 (« was UNengaged at the start of the Fight step », par négation). **Seul snapshot nécessaire** — aucun snapshot de début de phase n'est requis par le PDF 12.
- `units_selected_to_fight` : set des unités « selected to fight » cette phase. Sert à : exclusion 12.04 (« has not already been selected to fight »), déclencheur Engaging (« have not been selected to fight this phase »), et éligibilité consolidation (« was eligible to fight this phase » ≈ a été sélectionnée, puisque la séquence 12.04 épuise toutes les éligibles — y compris celles sélectionnées via Engaging pendant l'étape Consolidate, dont la fenêtre de consolidation est régie par la décision #9). Distinct de `units_fought` (sémantique « a combattu »).
- `pile_in_done` / `consolidation_done` : sets par étape groupée (1 move max/unité).
- `fight_step` : `"fights_first"` | `"remaining"`.
- `fight_selector` : joueur sélectionneur courant de l'étape FIGHT (handoff 12.04).
- `fight_subphase` : refonte → `"pile_in"` | `"fight"` | `"consolidate"` | `None`.

**Helper centralisé**
- `is_fights_first(unit, game_state) -> bool` : `unit_has_rule_effect(unit, "fights_first")`, l'effet étant accordé par le charge move (grant temporaire jusqu'à fin de tour, source 11.04) ou plus tard par datasheet. Implémentation V1 : équivalent fonctionnel `unit in units_charged` accepté si le système de grants temporaires n'existe pas encore — mais l'API reste « ability », pas « statut charge ».

---

## 7. Plan d'implémentation par blocs

> Chaque bloc = **backend + frontend + IA + tests**, validés **en fin de bloc**.
> **Critères de validation** — à ne pas confondre :
> - **Blocs 0 à 4** : les états de fin de bloc sont **transitoires et NON conformes V11** (mélanges V10/V11 assumés).
>   Le critère de fin de bloc est donc : (a) la machine tourne (run `--step` complet sans erreur), (b) **zéro régression**
>   sur les comportements non touchés, (c) les **comportements nouveaux du bloc** sont couverts par tests unitaires.
>   La conformité règles complète n'est **pas** un critère de ces blocs.
> - **Blocs 5 et 6** : critère = **conformité V11 complète** (+ validation intégrée Bloc 6).
> Chaque bloc précise son **état jouable** attendu (les blocs 1-3 sont couplés ; sans état jouable défini, la validation par bloc est illusoire).

### Bloc 0 — Fondations
- Config : `pile_in_target_range: 5`, `consolidation_trigger_range: 3`.
- État : snapshot `engaged_at_fight_step_start` (pris au début de l'étape FIGHT, donc fonction appelable après le futur pile-in groupé) ; sets `units_selected_to_fight`, `pile_in_done`, `consolidation_done`.
- Helper `is_fights_first(unit, game_state)` (API ability ; source = charge move pour l'instant).
- Extraire la primitive `pile_in_move` réutilisable (étape PILE_IN, overrun 12.06, et base des moves de consolidation), avec les **contraintes 12.03 dures** : cibles selon engagement (toutes engagées / choix dans 5"), fin strictement plus proche de la cible la plus proche, **doit finir engagée** (filtre dur), figurines en contact immobiles, conservation des engagements de départ.
- Tests : helpers unitaires (éligibilités, snapshot, contraintes d'ancres).
- **État jouable** : inchangé fonctionnellement (helpers non branchés).
- **Validation** : tests unitaires des helpers + run `--step` sans régression.

### Bloc 1 — Sous-phases (machine d'état)
- Remplacer les sous-phases V10 par `pile_in` / `fight` / `consolidate` + `fight_step` + `fight_selector`.
- Refonte : `fight_phase_start` (fight_handlers.py:180), `fight_build_activation_pools` (246) — **pools construits sur l'éligibilité 12.04, jamais sur la présence de cibles** —, transitions (2886-2933), routage `execute_action` (2130), suppression de `fight_alternating_turn`/`_toggle_fight_alternation` (2850).
- Machine de sélection 12.04 complète (handoff, démarrage de Remaining par « le joueur qui a fait passer la séquence », retour FF après fight en Remaining).
- **Frontend** : `src/types/game.ts` (subphase), `src/components/TurnPhaseTracker.tsx`.
- **IA** : `engine/observation_builder.py:1870` (sélection pool), `engine/action_decoder.py:469` (eligible units / masking).
- Tests.
- **État jouable** : machine V11 en place ; pile-in encore par unité (V10) ; consolidation encore en fin d'activation (V10) ; pas d'overrun. **Transitoire non conforme, assumé.**
- **Validation** : machine de sélection 12.04 testée unitairement (handoff, ordre actif d'abord) ; run `--step` complet ; zéro régression sur les attaques.

### Bloc 2 — PILE IN groupé
- Étape n°2 : toutes unités éligibles (**engagée OU a chargé** — pas le bullet overrun), actif puis adverse, optionnel par unité (skip), 1 fois/unité (`pile_in_done`).
- Cibles : toutes les unités engagées si engagée ; sinon **choix joueur** parmi les ennemis dans 5" (UI : sélection de cibles ou dérivation depuis la destination cliquée ; IA : heuristique plus-proche).
- Contraintes dures 12.03 (primitive Bloc 0) — remplace la logique « palier le plus proche tous ennemis » + préférence contact soft.
- Sortir le pile-in de l'activation-par-unité (`_handle_fight_unit_activation`, fight_handlers.py:2648, branche 2699-2754).
- Réutilise le BFS existant (`_fight_build_pile_in_valid_destinations`, 724) avec les nouveaux filtres.
- **Frontend** : UI pile-in de groupe (file d'unités éligibles, skip).
- **IA** : auto-heuristique (`_ai_select_pile_in_destination`, 1826) — politique décision #7.
- Tests.
- **État jouable** : pile-in groupé V11 + fights V11 ; consolidation encore V10 en fin d'activation. **Transitoire non conforme, assumé.**
- **Validation** : contraintes 12.03 testées unitairement (doit finir engagée, contacts immobiles, 5") ; run `--step` + partie PvP manuelle de l'étape pile-in ; zéro régression sur fight/consolidation V10.

### Bloc 3 — FIGHT : Fights First + sélection 12.04
- Brancher `is_fights_first` sur la machine du Bloc 1 ; éligibilité fight V11 (engagée / `engaged_at_fight_step_start` / a chargé) ; marquage `units_selected_to_fight` à la sélection (pas à la résolution).
- Sélection **obligatoire** des unités éligibles même sans cible valide (fight à vide si rien d'engagé après le type choisi).
- Snapshot `engaged_at_fight_step_start` pris à l'entrée de l'étape.
- **Frontend** + **IA** (subphase observée) + tests (y compris : unité chargée dont la cible est morte → éligible, sélectionnée).
- **État jouable** : étapes 2 et 3 conformes V11 ; consolidation encore V10. **Transitoire non conforme, assumé.**
- **Validation** : éligibilité 12.04 et ordre FF→Remaining testés unitairement ; run `--step` ; zéro régression.

### Bloc 4 — OVERRUN fight (nouveau)
- Type fight 12.06 : éligible si **unengaged maintenant**, OU **était UNengaged au début de l'étape Fight** (négation du snapshot) et devenue engagée pendant la phase.
- Effet : **1 pile-in additionnel** (primitive Bloc 0, règles 12.03 complètes — c'est ici que sert le 3e bullet d'éligibilité de 12.03) puis fight.
- Choix du fight type quand plusieurs sont éligibles (UI ; IA : overrun si unengaged, sinon normal).
- **Frontend** : UI overrun. **IA** (auto) + tests.
- **État jouable** : étapes 2-3 complètes avec overrun ; consolidation encore V10. **Transitoire non conforme, assumé.**
- **Validation** : les deux conditions 12.06 testées unitairement (dont le cas « a chargé, cible détruite ») ; run `--step` ; zéro régression.

### Bloc 5 — CONSOLIDATE groupé, 3 modes
- **Restructure timing** : extraire la consolidation de la fin d'activation (`_fight_try_begin_consolidation_after_attacks`, `_handle_fight_consolidation_resolution`, `_fight_post_process_fight_activation_result`, `_fight_consolidation_ctx`) vers l'étape groupée n°4 : actif puis adverse, optionnel par unité, 1 move/unité (`consolidation_done`).
- **Pools de sous-étape dynamiques (décision #9)** : éligibilité (`units_selected_to_fight` vivantes) évaluée au début de chaque sous-étape et re-vérifiée à chaque sélection ; asymétrie actif/adverse implémentée et testée (unité adverse déclenchée → consolide ensuite ; unité active déclenchée pendant la sous-étape adverse → ne consolide pas).
- Étend `_fight_plan_consolidation_destinations` (fight_handlers.py:1293) → cascade Ongoing / Engaging / Objective avec gates **3"** (`consolidation_trigger_range`) ; branche objectif : **chiffrer la portée de contrôle via PDF 14** puis viser « within range » — limitation hex documentée (décision #2) ; supprimer la consolidation objectif sans gate de distance.
- **Engaging** : sélection d'1+ ennemis dans 3", fin engagée avec tous (filtre dur) ; puis combats déclenchés résolus **in-place** : l'adversaire sélectionne un à un les ennemis engagés non `selected_to_fight`, chacun applique « WHEN A UNIT IS SELECTED TO FIGHT » (Normal ou **Overrun** si 12.06 satisfaite). `execute_action` doit accepter les actions fight pendant `fight_subphase == "consolidate"`.
- **Frontend** : UI choix de mode (mode imposé affiché, skip possible) + résolution des combats déclenchés.
- **IA** : politique décision #7 + tests.
- **État jouable** : phase fight 100% V11.
- **Validation** : **conformité V11 complète** — les 5 étapes, cascade des modes, combats déclenchés (y compris overrun in-place), pools dynamiques, gates 3" ; tests unitaires + partie PvP manuelle complète.

### Bloc 6 — Intégration finale
- `ai/analyzer_phases/fight_handler.py` (suit les nouvelles sous-phases).
- `src/utils/replayParser.ts`.
- **Validation** : run complet `--step` + `analyzer.py` + replay PvP — conformité V11 confirmée de bout en bout.

---

## 8. Fichiers impactés (référence)

**Backend**
- `engine/phase_handlers/fight_handlers.py` (cœur, 4056 lignes)
- `engine/phase_handlers/shared_utils.py` (`unit_has_rule_effect`, 1407-1520 ; grant temporaire fights_first si implémenté)
- `engine/game_state.py` (UNIT_RULES, 158-162 ; nouveaux champs §6)
- `engine/w40k_core.py` (`units_charged`, 512 ; action space, 619)
- `engine/observation_builder.py` (subphase, 1870 ; charge feature, 2231)
- `engine/action_decoder.py` (fight action/masking, 333/469/825)
- `engine/phase_handlers/generic_handlers.py` (`end_activation`, `_rebuild_alternating_pools_for_fight` — refonte des rebuilds de pools)
- `config/game_config.json` (`pile_in_target_range`, `consolidation_trigger_range`)

**Frontend**
- `src/types/game.ts`, `src/components/TurnPhaseTracker.tsx`, `src/components/BoardPvp.tsx`
- `src/hooks/useGameActions.ts`, `src/hooks/useEngineAPI.ts`
- `src/utils/activationClickTarget.ts`, `src/components/UnitRenderer.tsx`
- `src/utils/replayParser.ts`, `src/components/BoardReplay.tsx`

**Tests** (`tests/unit/engine/`)
- `test_fight_activation_pools.py`, `test_fight_attack_sequence.py`, `test_fight_consolidation_bfs.py`, `test_fight_execution.py`, `test_fight_resolution.py`, `test_fight_special_rules.py`, `test_fight_spatial_contract.py`, `test_cascade_fight_subphases.py`

**IA / analyse**
- `ai/analyzer_phases/fight_handler.py`
- `ai/train.py`, `ai/training_utils.py` (masking)

---

## 9. Points hors scope (V2 / ultérieur)

- Ability `Fights First` datasheet (le grant 24.13 par charge est dans le scope ; l'ability permanente non).
- Transformation overrun / choix de cibles de pile-in / choix de mode de consolidation en **actions RL apprises** (V2).
- Réentraînement des modèles après migration.
- Test du retour Remaining → Fights First (inatteignable sans ability datasheet, décision #5).
- Vérification « Fights Last » au-delà des core abilities (stratagèmes / règles de faction — sans objet tant que non implémentés dans le moteur).
