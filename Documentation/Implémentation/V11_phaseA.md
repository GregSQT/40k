# V11 — Phase A' : toutes les règles implémentées dans le training (P1-P5)

> **Origine.** Section §9 extraite de [`V11_agent_rework.md`](V11_agent_rework.md) le 2026-07-28
> (plan [`V11_refactor_plan.md`](Implémenté/V11_refactor_plan.md), étape 1). Contenu déplacé **tel quel**,
> aucune réécriture.
>
> **Rôle.** Spécification de la Phase A' : parité de résolution des règles (P1) puis mécanisme de
> décision agent (P2→P5). L'**état** (fait / à faire) reste dans l'index
> [`V11_agent_rework.md`](V11_agent_rework.md).
>
> **Convention.** Les renvois `§9.x` internes restent en texte nu ; les renvois vers l'index et
> vers les autres sections sont des liens de fichier.
>
> **Sous-docs frères.** Les sections [§1](V11_tranches.md#s1) à [§8](V11_tranches.md#s8) (spec des
> tranches) ont été sorties dans [`V11_tranches.md`](V11_tranches.md) le 2026-07-28 (étape 3 du
> plan) ; [§10](V11_eval_strategy.md#s10) est dans [`V11_eval_strategy.md`](V11_eval_strategy.md).

---
<a id="s9"></a>
## 9. Phase A' — Toutes les règles implémentées dans le training (P1-P5)

Décision utilisateur (2026-07-14) : l'agent doit s'entraîner sur TOUTES les règles déjà
implémentées, et chaque fois que les règles laissent un choix au joueur, c'est l'agent qui
choisit. Périmètre strict : règles présentes dans le moteur — on n'entraîne sur AUCUNE feature
absente (stratagèmes, CP, FNP, transports, etc. restent hors scope). Prérequis : Phase A
(T1-T6) validée.

<a id="s9.0"></a>
### 9.0 AUDIT DE STATUT 2026-07-24 — Phase A' — ❌ (P1 livré depuis ; **P2 + P3 point 0 livrés le 2026-07-28**)

> 🔴 **MISE À JOUR 2026-07-28 — la ligne P1 du tableau ci-dessous est PÉRIMÉE.** Les règles
> d'armes sont **vives** depuis le 2026-07-26 : le socle commun
> `engine/phase_handlers/attack_sequence.py` est importé par le chemin de tir vif
> ([shared_utils.py:7363](../../engine/phase_handlers/shared_utils.py#L7363), [:8667](../../engine/phase_handlers/shared_utils.py#L8667))
> et par le chemin de mêlée vif ([fight_handlers.py:5227](../../engine/phase_handlers/fight_handlers.py#L5227)).
> ~~**Ce qui reste de P1** = la SUPPRESSION du code mort `_attack_sequence_rng`~~ → **FAITE le
> 2026-07-28**, cf. **[§0hist.38](V11_agent_rework.md#s0.38)**. **P1 est intégralement soldé.** Les verdicts **P2, P3, P4, P5 du tableau restent exacts**, re-vérifiés le 2026-07-28
> (grep `pending_agent_decision`/`CHOICE_[0-9]` = 0 ; `TOTAL_ACTION_SIZE` = 1062 ;
> `raw_action_int % len(options)` toujours vif). Le titre « 0/5 » devient donc **0/4**.
>
> 🔴 **MISE À JOUR 2026-07-28 soir — les lignes P2 et P3 ci-dessous sont à leur tour PÉRIMÉES.**
> `TOTAL_ACTION_SIZE` vaut **1088 sur `main`** (1082 après P3-1, + 6 `CHOICE_i` avec P2 ; **1107 sur
> la branche `v11-p3-2-charge-target`, cf. §9.4bis**) et **P3 point 1 (cible
> de mêlée) est LIVRÉ** — non par le `CHOICE_k` de [§9.3](#s9.3), mais par une dimension d'action par slot
> ennemi + tête pointeur, la spec P2 ayant été jugée périmée par T-E/T-G. Détail, preuves et
> décision d'architecture → **[§0.41](V11_agent_rework.md#s0.41)**. Le grep `pending_agent_decision`/`CHOICE_[0-9]` rend
> toujours 0, et c'est **voulu** : le mécanisme générique n'est plus la réponse pour les décisions
> dont les candidats sont des entités. P3 est donc **1/9**, pas 0/9.

> 🟢 **MISE À JOUR 2026-07-28 (soir) — P2 est LIVRÉ, avec son pilote P3 point 0.** Le mécanisme
> générique de décision agent existe (`engine/agent_decision.py`, actions `CHOICE_0..5`, bloc
> d'observation « contexte de décision », tête pointeur de candidats) et la **pseudo-décision
> `raw_action_int % len(options)` n'existe plus** : le grep qui la trouvait à `w40k_core.py:2644`
> rend désormais 0. Les lignes **P2 et P3 du tableau ci-dessous sont donc PÉRIMÉES** pour ces deux
> points ; P3 points 2→8 et P4/P5 restent exacts (le point 1 est livré, cf. ci-dessus).
> **Mergé sur `main` le 2026-07-28 soir.** Détail → **§9.3bis**. `TOTAL_ACTION_SIZE` valait alors
> **1088** (1082 + 6 CHOICE) et `obs_size` **20740** : tout modèle antérieur est incompatible
> (retrain `--new`), et **aucune mesure de win-rate n'existe encore** pour ce changement.

> 🟢 **MISE À JOUR 2026-07-28 (nuit) — P3 point 2 (cible de CHARGE) est LIVRÉ**, sur le patron
> P3-1 (dimension d'action par slot ennemi + tête pointeur), avec son P4 (`charge_reachable_max_roll`).
> P3 passe donc à **3/9**. `TOTAL_ACTION_SIZE` vaut **1107** et `obs_size` **20768** — les chiffres
> ci-dessus sont périmés d'autant. Détail, preuves et mesure de coût → **§9.4bis** et
> **[§0.43](V11_agent_rework.md#s0.43)**. ⚠️ Livré sur la branche `v11-p3-2-charge-target`,
> **PAS mergé sur `main`** : le merge est une décision utilisateur, à ne pas prendre pendant un run.
> 🔴 Et la bascule de branche elle-même ne l'est pas non plus : c'est elle qui a tué le 2ᵉ run
> [§0.14](V11_agent_rework.md#s0.14) du 2026-07-28. Ce que les workers `spawn` relisent est le **working tree**, pas `main` —
> cf. la leçon durcie en [§0bis](V11_agent_rework.md#s0bis).

Revérification ligne à ligne contre le code (la première ; [§0.19](V11_agent_rework.md#s0.19) ne l'avait jamais menée, cf. sa
correction). **Aucune des cinq sous-parties n'est réellement en place**, malgré les marqueurs
✅ FAIT antérieurs. Chiffres et sites relevés par grep/lecture le 2026-07-24, pas de mémoire.

| Sous-partie | Statut réel | Preuve vérifiée |
|---|---|---|
| **P1** — Parité de résolution (§9.2) | ⏳ **démarré** (état initial « fait à l'envers » ; 1 règle corrigée le 2026-07-24, cf. **§9.2.1**) | **Snapshot à l'audit (état AVANT démarrage P1)** : les règles HEAVY, IGNORES_COVER, DEVASTATING_WOUNDS, closest_target_penetration, HAZARDOUS, reroll_1_towound, reroll_towound_target_on_objective étaient écrites **dans `_attack_sequence_rng`** (le code MORT, [shooting_handlers.py:5998](../../engine/phase_handlers/shooting_handlers.py#L5998)), **absentes du chemin vif** — `_attack_sequence_rng` n'a **aucun appelant vif** (seuls 6 fichiers de tests le monkeypatchent) → règles inactives gym ET PvP. **⚠️ MISE À JOUR 2026-07-24** : **IGNORES_COVER est désormais portée dans le vif** (`_cover_worsened_bs`, cf. §9.2.1) — cette ligne n'est donc plus vraie pour elle ; les 6 autres règles + la suppression du code mort (`_attack_sequence_rng`, états `_rapid_fire_*`, log `rapid_fire_bonus_shot`, 5 branches « squad path expected ») restent à faire. |
| **P2** — Mécanisme générique décision agent (§9.3) | ❌ **absent** | Grep `pending_agent_decision` / `CHOICE_[0-9]` / `agent_decision` sur `engine/` + `ai/` = 0. Action_space non étendu : `TOTAL_ACTION_SIZE` reste `BASE_ZONE_INTENT + MAX_OBJECTIVES*3` ([macro_intents.py:20](../../engine/macro_intents.py#L20)), pas le `41+K` prévu. Aucun bloc obs « contexte de décision ». |
| **P3** — Branchement décision par décision (§9.4) | ❌ **0/9** | Point 0 (pseudo-décision aléatoire, le plus urgent) toujours vif : `raw_action_int % len(options)` à [w40k_core.py:2644](../../engine/w40k_core.py#L2644). Points 1-8 : sélecteurs heuristiques `_ai_select_*` / scoring intacts, aucun branché sur une décision agent. |
| **P4** — Observation de support (§9.5) | ❌ **sans objet** | Le bloc décision (P2) n'existant pas, son support obs non plus. |
| **P5** — Validation par tranche (§9.6) | ❌ **sans objet** | Aucune tranche P3 ouverte → aucun cycle win-rate. |

**Seul acquis réel** : les 4 rerolls de fight sont vifs ([fight_handlers.py:5153-5206](../../engine/phase_handlers/fight_handlers.py#L5153)) — mais §9.2 les liste déjà comme « déjà vifs », donc rien de neuf au titre de P1.

⚠️ **Pourquoi les ✅ FAIT étaient faux.** Le travail P1 identifiable (règles d'armes) a été écrit
**dans le code mort** au lieu du chemin vif, et une batterie de tests (`test_unit_rules_shoot.py`,
`test_shoot_attack_sequence.py`, `test_special_rules_e2e.py`, `test_fight_special_rules.py`,
`test_phase_transitions.py`) le **monkeypatche** et passe au vert. C'est exactement le double motif
que [§0.19](V11_agent_rework.md#s0.19) existe pour interdire : **code testé mais jamais appelé** (T6-i) + **test qui passe pour
la mauvaise raison**. En jeu réel, ces règles ne s'exécutent nulle part.

**Conséquence de planning.** La Phase A' est **à faire intégralement**, dans l'ordre du plan
ci-dessous (P1 corrigé = déplacer les règles vers le vif PUIS supprimer le mort ; puis P2→P5).
Les critères d'acceptation de §9.2→§9.6 restent valides tels quels.

<a id="s9.0bis"></a>
### 9.0bis Optimalité du plan — arbitrage avant exécution (2026-07-24)

Question posée : « faire décider à l'agent TOUT ce qu'il peut est-il optimal ? ». Sites de code
ci-dessous **vérifiés par lecture** le 2026-07-24.

**La MÉTHODE du plan est bonne** — à garder telle quelle :
- **P2 générique** (un canal `pending_agent_decision` + `CHOICE_0..K`) plutôt qu'une action ad
  hoc par décision : évite l'explosion de l'action_space, mutualise, et le miroir des prompts PvP
  `waiting_for_player` respecte la règle projet « gym copie PvP ».
- **§9.6** (une tranche = une décision, win-rate ≥ tranche précédente sinon corriger
  observation/reward AVANT d'empiler) : c'est le garde-fou qui rend le plan robuste au risque
  « plus de décisions = agent pire ». À ne jamais assouplir.

**L'OBJECTIF « tout » n'est pas optimal en soi** — trois réserves, avec le traitement retenu :

1. **Levier tactique nul = ne pas brancher (mesurer, ne pas juger à la main).** Certaines
   décisions ont un optimum calculable déjà atteint en auto : choix d'arme CC par expected damage
   `_auto_select_cc_weapon_for_fig` ([shared_utils.py:7370](../../engine/phase_handlers/shared_utils.py#L7370)),
   ordre de déclaration des groupes d'allocation `_auto_declared_order`
   ([shared_utils.py:6462](../../engine/phase_handlers/shared_utils.py#L6462)). Les brancher
   n'ajoute que de la dimensionnalité (dilution du reward, credit assignment plus profond,
   risque de catastrophic forgetting — piège connu CLAUDE.md) sans gain. **Critère d'arbitrage à
   appliquer AVANT chaque tranche P3** : mesurer le *regret* de la décision — écart de valeur
   entre le choix optimal (rollout/oracle) et le choix de l'heuristique auto. Regret négligeable
   → rester en auto ; regret significatif → brancher. Ça remplace le « optionnels, à statuer
   utilisateur » (§9.4 point 8) par une mesure, pas un avis.

2. **Décisions spatiales : ne pas exposer en top-K d'hex.** Pour destination de pile-in/conso
   (§9.4 point 5), move-after-shooting (point 6), placement de charge, les candidats pertinents
   dépassent souvent K=6 → un top-K figé **tronque et peut exclure l'optimum** (troncature
   silencieuse = anti-pattern projet). Le plan le fait DÉJÀ bien pour le déploiement : actions
   4-8 = **5 stratégies tactiques scorées** (aggressive front / objective pressure /
   safe-cohesion / left / right flank), pas des hex bruts —
   [action_decoder.py:1833](../../engine/action_decoder.py#L1833). **À généraliser** : paramétrer
   toute décision spatiale à grand espace en *intentions scorées*, pas en hex. Sinon K=6 devient
   un plafond arbitraire sur la qualité.

3. **K=6 est un défaut, pas une loi.** L'alignement sur les 6 slots figurines (§9.3) vaut pour
   l'allocation de pertes ; il n'a aucune raison de borner les décisions de cardinalité
   différente. K doit être choisi par type de décision, pas global.

**En clair** : le plan est quasi-optimal en méthode ; l'objectif « tout » doit rester
**subordonné au win-rate §9.6 et au regret mesuré** (réserve 1), et la **paramétrisation des
décisions spatiales en intentions scorées** (réserve 2) est le point technique à ne pas rater.

<a id="s9.1"></a>
### 9.1 Constat d'architecture (audit 2026-07-14, vérifié par lecture)

Il existe DEUX moteurs de résolution d'attaque :
- **Chemin vif** (PvP ET gym) : résolution squad — `_manual_roll_intent`
  ([shared_utils.py:5905-5993](../../engine/phase_handlers/shared_utils.py#L5905-L5993)) + `_resolve_one_manual_wound` (L6038-6114).
- ~~**Code mort** : `_attack_sequence_rng`~~ — **SUPPRIMÉ le 2026-07-28** (§0hist.38), avec ses
  états orphelins `_rapid_fire_*` côté `shooting_handlers` et le helper mort
  `_get_rapid_fire_parameter`. **La chaîne d'affichage a été réparée le 2026-07-29** (après le
  merge de §0.40, qui a libéré `w40k_core.py`) : [DEVASTATING WOUNDS], [HEAVY] et [RAPID FIRE]
  atteignent de nouveau `step.log`, donc l'analyzer et le replay ; deux contrôles d'analyzer
  périmés ont été retirés avec leurs tests de non-régression. Détail en §0hist.38. Les **5** branches-gardes `raise RuntimeError` de
  `execute_action` (`activate_unit`, `shoot`, `select_weapon`, `left_click`, `invalid` — la 3ᵉ
  échappe au grep « squad path expected », son message diffère) sont **conservées** : le dispatcher est vif ([w40k_core.py:6157](../../engine/w40k_core.py#L6157)),
  ces `raise` sont des gardes explicites et les retirer dégraderait l'erreur en
  `invalid_action_for_phase` silencieux.
- `WeaponRulesApplier.apply_rules` est un placeholder pass-through ([rules.py:279-327](../../engine/weapons/rules.py#L279-L327)) :
  les règles d'armes sont validées/parsées mais PAS appliquées par ce système.

Conséquence : toute règle implémentée uniquement dans `_attack_sequence_rng` est inactive
partout (gym ET PvP).

<a id="s9.2"></a>
### 9.2 P1 — Parité de résolution : réimplémentation depuis les PDFs, puis suppression du mort

⚠️ **Le code mort N'EST PAS une spec à porter** — vérifié contre les PDFs du projet (24 Core
abilities lu) : il implémente une AUTRE édition des règles. Il ne sert que d'indice de point
d'insertion. Chaque règle se réimplémente depuis le PDF du projet.

Règles à implémenter dans le chemin vif (absentes du vif, présentes dans le mort sous forme
non conforme) — descriptions = PDF projet :

| Règle (PDF projet) | Indice mort | Point d'insertion vif |
|---|---|---|
| HEAVY (24.16) : +1 to hit si unité unengaged ET pas posée sur la table ce tour ET aucun modèle bougé de plus de 3" ce tour — PAS « remained stationary » | ~:5869-5880 | `_manual_roll_intent` (seuil de touche) |
| HAZARDOUS (24.15) : après que l'unité a résolu TOUTES ses attaques, un hazard roll (06.03) PAR ARME hazardous sélectionnée — pas un jet par attaque. NB : `roll_hazard_for_unit` (vif, shared_utils ~3410, câblé au move via w40k_core ~2635) implémente déjà 06.03 → réutiliser | ~:5887, :5916 | fin d'activation tir/fight |
| IGNORES_COVER : 17 armes la déclarent, la feature est OBSERVÉE, mais `_cover_worsened_bs` (shared_utils ~5745) ne la vérifie jamais — le malus de couvert est infligé À TORT à ces armes (gym ET PvP ; le commentaire w40k_core ~4380 « appliqué côté frontend » est faux pour la résolution backend) | — (jamais implémentée) | `_cover_worsened_bs` (bypass si arme IGNORES_COVER) |
| DEVASTATING_WOUNDS (24.10) : critical wound → la séquence de CETTE attaque s'arrête, la cible subit D blessures mortelles APRÈS les dégâts normaux, max 1 figurine endommagée par critical wound — PAS « save sauté » (le mort n'est pas conforme non plus) | ~:5970-5980 | `_resolve_one_manual_wound` + moteur MW |
| RAPID_FIRE : attaques bonus à mi-portée (conforme PDF) | état w40k_core ~:1055-1061 | `_manual_roll_intent` (calcul NB à la déclaration, comme Blast) |
| closest_target_penetration (règle projet unit_rules.json) : AP+1 sur la cible éligible la plus proche | ~:5836-5840 | `_manual_roll_intent` (AP effectif) |
| reroll_1_towound au TIR | ~:5935-5940 | `_manual_roll_intent` — déjà vif en fight (`_manual_roll_fight_intent`) : asymétrie tir/fight à combler |
| reroll_towound_target_on_objective au TIR | ~:5945-5957 | idem |

Méthode : une règle = une tranche (PDF relu AVANT implémentation + test unitaire dédié).
⚠️ Le chemin squad est partagé PvP/gym : chaque implémentation corrige AUSSI le PvP — c'est
voulu (conformité accrue partout), à annoncer à l'utilisateur (équilibre de jeu modifié).

Cas particulier : **`reroll_charge`** est déclaré dans `config/unit_rules.json` mais
n'existe NULLE PART dans le code (grep zéro, ni vif ni mort). À statuer : implémenter
(charge_handlers, reroll du 2D6) ou retirer de la config.

Déjà vifs (rien à porter) : charge_impact (règle d'unité D6 4+ → 1 MW, `_apply_charge_impact`
~L4551), charge/shoot_after_advance/flee, move_after_shooting, reactive_move,
**Desperate Escape (09.07)**, les 4 rerolls de fight, Blast, Pistol (10.06), couvert 13.08
(mécanique conforme PDF SAUF le cas IGNORES_COVER ci-dessus), obscuring, invuln, allocation
05.03/05.04, T du bodyguard 19.02.
NB : `closest_target_penetration` apparaît aussi comme feature d'OBSERVATION
(observation_builder) — actuellement observée sans effet en résolution.

**Périmètre à statuer (utilisateur)** : ~10 règles d'armes sont déclarées dans les armories ET
observées (observation_builder ~65-92) mais appliquées NULLE PART (ni vif ni mort) : TORRENT,
TWIN_LINKED, SUSTAINED_HITS, LETHAL_HITS, MELTA, ANTI_*, INDIRECT_FIRE, EXTRA_ATTACKS,
PSYCHIC. Elles sont hors périmètre A' (« règles présentes dans le moteur ») — MAIS
IGNORES_COVER fait exception (intégrée au tableau P1 ci-dessus) car son absence rend FAUSSE
une règle implémentée (le couvert). Pour les autres : soit les implémenter (extension de
périmètre à valider), soit retirer leurs canaux d'observation (bruit pur pour PPO), jamais
le statu quo silencieux.

~~Suppression du code mort (fin de P1)~~ : **FAITE** — cf. **[§0hist.38](V11_agent_rework.md#s0.38)**
pour le détail, les deux écarts de conformité trouvés en migrant les tests, les 13 mutations de
contre-épreuve, et la réparation de la chaîne d'affichage le 2026-07-29 (3 règles, 7 mutations
supplémentaires). **Les deux critères de §9.2 sont atteints** : `grep _attack_sequence_rng` est
vide sur `engine/ ai/ services/ tests/`, et `_rapid_fire_` ne subsiste plus que dans un
commentaire expliquant sa suppression. Le champ de log `rapid_fire_bonus_shot` est désormais
**produit** par le chemin vif au lieu d'être lu à vide.

<a id="s9.2.1"></a>
### 9.2.1 Progression P1 (démarrée 2026-07-24)

Ordre de démarrage validé utilisateur : commencer par IGNORES_COVER (seul cas où l'absence rend
une règle active FAUSSE). Arbitrages actés le 2026-07-24 : `reroll_charge` → **à implémenter**
(tranche charge) ; les ~10 règles d'armes observées non appliquées → **périmètre A' étendu, à
implémenter** (tranches ultérieures).

| Règle | Statut | Où (vif) | Test |
|---|---|---|---|
| **IGNORES_COVER (24.18)** | ✅ **FAIT dans le vif** (2026-07-24) | Helper `weapon_has_rule` ([weapon_helpers.py](../../engine/utils/weapon_helpers.py)) + court-circuit `(bs, False)` en tête de `_cover_worsened_bs` ([shared_utils.py:6078](../../engine/phase_handlers/shared_utils.py#L6078)), avant tout calcul de LoS. PDF 24.18 + 13.08 relus. | `tests/unit/engine/test_ignores_cover.py` (**6**) : 4 unitaires directs + **2 bout-en-bout via `_manual_roll_intent`** (verrouillent le CÂBLAGE appelant→fonction, pas la fonction seule — cf. [§0.19.3](V11_agent_rework.md#s0.19.3)). Deux contre-épreuves faites : (a) court-circuit neutralisé → 2 rouges ; (b) mauvais `weapon` passé à l'appel → l'e2e rougit. Restauré → 6 verts. |
| **reroll_1_towound (tir) + reroll_towound_target_on_objective (tir)** | ✅ **FAIT dans le vif** (2026-07-25) | Ajoutés dans `_manual_roll_intent` (tir) en **miroir exact** de `_manual_roll_fight_intent` ([fight_handlers.py:5203](../../engine/phase_handlers/fight_handlers.py#L5203)) : conditions via `_unit_has_rule_effect` + `is_unit_on_objective`. Helper `_is_unit_on_objective` **déplacé** de fight_handlers vers shared_utils (`is_unit_on_objective`, générique tir/fight), fight délègue. PDF 01 Core « Re-rolls » (un dé re-roll une fois). | `tests/unit/engine/test_reroll_towound_shoot.py` (**5**, bout-en-bout via `_manual_roll_intent`, RNG déterministe) : reroll d'un 1 / reroll tout échec sur objectif / discrimination non-1 et off-objectif / sans règle. Contre-épreuve : bloc reroll neutralisé → 2 rouges. |
| **closest_target_penetration** | ✅ **FAIT dans le vif** (2026-07-25) | Bloc dans `_manual_roll_intent` ([shared_utils.py:6335](../../engine/phase_handlers/shared_utils.py#L6335)), au calcul de l'AP effectif AVANT `save_threshold`/`display_save_th`. Garde `_unit_has_rule_effect(attacker_unit, "closest_target_penetration")` ; « cible la plus proche » = `min()` sur `shooting_build_valid_target_pool` (éligibles) via `ranged_edge_distance` bord-à-bord (sélecteur `ranged`), mesurée au niveau **ESCOUADE** (`attacker["squad_id"]` — dans le vif `attacker` est une FIGURINE, écart corrigé vs le mort qui utilisait `attacker["id"]`). AP+1 = `ap -= 1` (convention AP négatif, cf. `save_threshold`). Spec = `config/unit_rules.json` (aucun PDF ; le PDF 22 ne contient QUE Aura/Faction/Psychic/Wargear + Plunging Fire). Se propage au groupe d'arme (`gkey`), à l'allocation (`g["ap"]`) et au `display_save_th`. | `tests/unit/engine/test_closest_target_penetration_shoot.py` (**3**, bout-en-bout via `_manual_roll_intent`, distance mesurée pour de vrai sur `units_cache` positionnés, pool éligibles monkeypatché) : (a) cible la plus proche + règle → AP-1 + save_th dégradé ; (b) cible plus lointaine + règle → inchangé (discrimination « closest ») ; (c) plus proche sans règle → inchangé. Contre-épreuve mutation : `ap -= 1` neutralisé → (a) rouge. Suite `tests/unit/` verte. **Impact PvP** : chemin partagé → l'équilibre PvP change aussi. |
| **HEAVY** | ✅ **FAIT dans le vif** (2026-07-25) | Bloc dans `_manual_roll_intent` après `_cover_worsened_bs` ([shared_utils.py:6327](../../engine/phase_handlers/shared_utils.py#L6327)) : si `weapon_has_rule(weapon, "HEAVY")` ET l'escouade est absente de `units_moved` ET `units_advanced` (« Remained Stationary »), alors `bs = max(2, bs-1)` (+1 au jet de touche, plancher 2 car un 1 naturel rate toujours, 05.01). ⚠️ ~~**Écart PDF assumé**~~ — **PÉRIMÉ, corrigé le 2026-07-26 puis re-vérifié dans le code le 2026-07-28 (§0hist.38)** : les **trois** clauses du PDF 24.16 sont désormais CÂBLÉES — *unengaged* (`_heavy_unit_is_engaged`, même prédicat que le gate 10.06), *pas posé ce tour* (`_unit_was_set_up_this_turn` sur `deployed_on_turn`) et *aucune figurine >3"* (`moved_distance_by_model`, distance de chemin géodésique accumulée par `commit_move` — la donnée qui manquait existe). Le seuil est comparé strictement (« MORE than 3\" » : 3" pile conserve le bonus). Le code mort, lui, ne testait que « absente de `units_moved`/`units_advanced` » : c'est **lui** qui s'écartait du PDF. | `tests/unit/engine/test_heavy_shoot.py` (**13** au 2026-07-28, e2e via `_manual_roll_intent`) : les 3 clauses, la borne 3" stricte (0/2/3 → bonus ; 3.5/4/12 → pas de bonus), la clause « no MODEL » sur la figurine la plus mobile de l'escouade, le plancher 2 (BS2+ ne descend pas à 1+), `bs_base` préservé, et le token `[HEAVY]` du combat log. Contre-épreuve mutation : `bs=max(2,bs-1)` neutralisé→rouge. |
| **RAPID_FIRE X** | ✅ **FAIT dans le vif** (2026-07-25) | Bloc dans `_manual_roll_intent` juste après BLAST ([shared_utils.py:6323](../../engine/phase_handlers/shared_utils.py#L6323)), à la constitution du pool d'attaques (avant tout jet) : si l'arme déclare `RAPID_FIRE:X` (param extrait par le nouveau helper `weapon_rule_parameter`, [weapon_helpers.py](../../engine/utils/weapon_helpers.py), miroir de l'extraction `analyzer_config.py`) ET la cible est dans la **demi-portée** (`RNG/2`, RNG déjà en subhexes), alors `n_attacks += X`. Distance escouade→escouade via `ranged_edge_distance` (sélecteur `ranged`) — même convention que le gate de portée du moteur (socle d'escouade avec centres par-figurine) et que CTP ; positions figées pendant la résolution → mesurer là = « Select Targets step » (24.30). Conforme `config/weapon_rules.json` (« Increase this weapon's Attacks by X when target unit is within half range ») ET PDF 24.30. Pas de double-comptage : `n_attacks_resolved` (déclaration) = NB de base seul, BLAST et RAPID_FIRE ajoutés ici. | `tests/unit/engine/test_rapid_fire_shoot.py` (**3**, e2e via `_manual_roll_intent`, positions extrêmes proche/loin → seuil non ambigu) : dans demi-portée→+X ; hors→pas de bonus ; sans RAPID_FIRE→pas de bonus. Contre-épreuve mutation : `n_attacks += _rf_x` neutralisé→rouge. |
| **DEVASTATING_WOUNDS** | ✅ **FAIT dans le vif — vraie mécanique blessures mortelles** (2026-07-25) | Quatre points câblés : (1) flag posé au jet dans `_manual_roll_intent` sur blessure critique = jet de blessure **non modifié de 6** (05.02 ; testé sur la valeur finale, donc post-reroll) ET arme `DEVASTATING_WOUNDS` ; (2) propagé dans `_build_manual_allocation` ; (3) **ordonné en fin de lot** ([shared_utils.py:6859](../../engine/phase_handlers/shared_utils.py#L6859)) → les mortelles sont infligées **« after resolving any normal damage »** (24.10) ; (4) consommé dans `_resolve_one_manual_wound` ([shared_utils.py:6531](../../engine/phase_handlers/shared_utils.py#L6531)) : court-circuite **toute** save (armure ET invulnérable), la fig subit D (excess perdu = « max one model per critical wound »), record tagué `mortalWound`+`saveSkipped` (log/display + hook Feel No Pain futur). **Fidélité (décision utilisateur, arbitrée) :** en 40K les mortelles de Devastating sont **allouées par le défenseur comme les autres blessures de l'attaque** (05.03), sans save, après les dégâts normaux — c'est **exactement** ce que fait ce câblage en restant dans le flux d'allocation manuel (option A). Un pool MW séparé (`allocate_mortal_wounds`) n'ajouterait aucune fidélité et introduirait un prompt PvP inutile. **⚠️ Note d'équivalence :** aujourd'hui, sans Feel No Pain ni réduction-de-dégâts modélisés, « pas de save sur crit » et « D blessures mortelles » donnent le **même résultat numérique** ; le gain de cette tranche est le **modelage correct** (tag MW + ordre 24.10 + bypass invul explicite), pas un changement de chiffres. | `tests/unit/engine/test_devastating_wounds_shoot.py` (**2 BOUT-EN-BOUT** via `build_manual_shoot_allocation` en `gym_training_mode`) : critique+DEVASTATING → save 6 (qui réussirait sur Sv2+) **sautée** → dégât infligé **ET** record tagué `mortalWound`+`saveSkipped` ; sans DEVASTATING → save 6 protège, aucun tag. Contre-épreuve mutation : court-circuit `not _devastating` retiré → rouge. |
| **HAZARDOUS (24.15)** | ✅ **FAIT dans le vif** (2026-07-26) | Déclencheur en **fin d'activation** (`_finalize_manual_allocation`, tir ET combat — « after that unit has resolved all of its attacks »). Nombre de jets = nombre d'armes HAZARDOUS **sélectionnées** (couples figurine×arme distincts, comptés à la déclaration : `_count_selected_hazardous_weapons`), PAS par figurine. `roll_hazard_for_unit` généralisé (`n_rolls`, `context_label`) et 06.03 corrigé : **test « each model » par FIGURINE** (`models_cache[...]["UNIT_KEYWORDS"]`) au lieu des keywords d'unité — sans quoi l'union 19.03 donnerait 3 MW à une escouade d'infanterie menée par un character MONSTER. Reprise PvP branchée sur `hazard_origin` (`_resume_after_hazard` : shoot/fight → fin d'activation ; move → Desperate Escape inchangé). ⚠️ **PDF vs config** : `weapon_rules.json` disait « sur un 1 → 3 MW » ; le PDF 24.15+06.03 dit **1-2 → 1 MW (3 si CHAQUE figurine est MONSTER/VEHICLE)**. PDF appliqué. | `tests/unit/engine/test_hazardous.py` (**6**, e2e via `build_manual_shoot_allocation`) : MW sur 1-2, pas de MW sur 3+, aucun jet sans la règle, **2 armes = 2 jets** (discrimination par-arme vs par-figurine), 3 MW si tout véhicule, 1 MW si escouade mixte. |
| **TORRENT (24.37)**, **SUSTAINED HITS (24.36)**, **LETHAL HITS (24.23)**, **TWIN-LINKED (24.38)**, **ANTI-X Y+ (24.03)** | ✅ **FAIT dans le vif, tir ET mêlée** (2026-07-26) | Socle commun `engine/phase_handlers/attack_sequence.py` (cf. §9.2.3). LETHAL HITS : le « you CAN choose » est tranché par **espérance de dégâts** (`lethal_hits_auto_wound_is_better`), seul arbitrage exact — l'auto-blessure interdit la blessure critique, donc neutralise DEVASTATING. ANTI-X : seuil de critique abaissé si la cible porte le keyword X ; 24.02 (instances non cumulatives) → meilleur seuil applicable. | `test_weapon_rules_attack_sequence.py` (**24**) + `test_weapon_rules_fight.py` (**6**, câblage mêlée). |
| **MELTA X (24.25)** | ✅ **FAIT dans le vif** (2026-07-26) | Bonus sur la **caractéristique D** (D6+2, pas 2 forfaitaire) : `dmg_bonus` porté de `_manual_roll_intent` → clé de groupe d'armes (un même profil à demi-portée et hors demi-portée ne se résout pas dans le même lot, 04.03) → ajouté **après** le tirage du dé de dégâts dans `_resolve_one_manual_wound`. Demi-portée mutualisée avec RAPID FIRE (`_target_within_half_range`). | `test_melta_shoot.py` (**3**, e2e : à portée / hors portée / sans la règle). |
| **BLAST (24.05)** | ✅ **CORRIGÉ — la règle ne s'appliquait JAMAIS** (2026-07-26) | `_has_blast_keyword` testait `weapon["KEYWORDS"]`, champ **absent de toutes les armes** des armories (les règles vivent dans `WEAPON_RULES`) → bonus jamais accordé, gym ET PvP. Remplacé par `_blast_extra_dice_per_five` (`weapon_rule_parameter_or`, forme nue = 1 dé/5 figurines, forme `[BLAST X]` = X). | `test_blast_cleave.py` (**4** BLAST). |
| **CLEAVE X (24.06)** | ✅ **FAIT dans le vif** (2026-07-26) | Jumeau mêlée de BLAST + clause « une seule cible pour toutes les attaques de cette arme » (`_weapon_attacks_single_target`). ⚠️ **PDF vs config** : `weapon_rules.json` décrivait « touche X figurines supplémentaires dans l'ER » — **faux** ; le PDF donne des **dés d'attaque additionnels par tranche de 5 figurines cibles**. PDF appliqué. `target_squad_size_at_declaration` ajouté aux intents de `squad_declare_fight` (le chemin PvP par arme le posait déjà). | `test_blast_cleave.py` (**4** CLEAVE, dont multi-cibles et absence de taille = erreur explicite). |
| **EXTRA ATTACKS (24.11)** | ✅ **FAIT dans le vif** (2026-07-26) | Select Weapons step : `_select_fight_weapon_indices_for_fig` = **toutes** les armes EXTRA ATTACKS + **une** autre arme de mêlée (« if possible »), le choix principal les excluant. `squad_declare_fight` émet **un intent par arme** et `ATTACK_LEFT` cumule (sinon la 2ᵉ arme ne se résolvait jamais). | `test_extra_attacks_fight.py` (**7**, sélection + câblage). |
| **PRECISION (24.28)** | ✅ **FAIT dans le vif** (2026-07-26) | Override à l'ouverture de l'Allocation Order step : `_apply_precision_allocation_override` place le groupe CHARACTER visible en tête de l'ordre déclaré par le défenseur (l'ordre du défenseur est conservé pour le reste). Visibilité : mêlée = acquise au contact ; tir = `_attacker_model_can_reach_squad` restreint aux figurines CHARACTER (nouveau paramètre `only_target_mids`). Arbitrage du « can select » : **toujours**, sur le CHARACTER le plus cher. Ce n'est PAS un choix laissé à l'agent aujourd'hui — le mécanisme générique de décision agent (**P2**, `pending_agent_decision` + `CHOICE_0..K`) n'existe pas encore et l'action_space n'est pas étendu ; sans P2, la seule alternative serait une action ad hoc, exactement ce que §9.3 interdit. **Inscrite comme candidate à une tranche P3.** L'automatisme actuel est le choix strictement favorable à l'attaquant (viser le CHARACTER est l'unique effet de la règle), donc le regret attendu est faible — c'est le critère d'arbitrage de §9.0bis (mesurer le regret avant de brancher). | `test_precision.py` (**4**, dont la **contre-épreuve 05.03** : sans PRECISION le character est intouchable). |
| **PSYCHIC (24.29)** | ✅ **FAIT dans le vif** (2026-07-26) | « ignore any or all modifiers to BS/WS and to the hit roll » : le seul modificateur défavorable du moteur est le malus de couvert 13.08 → ignoré, **mais la cible garde le bénéfice du couvert** (contrairement à IGNORES COVER 24.18 qui le supprime). Le bonus HEAVY est conservé (« any or all » = choix du joueur). | `test_psychic_shoot.py` (**4**, dont la distinction explicite PSYCHIC vs IGNORES COVER). |
| **HEAVY (24.16) — mise en conformité PDF** | ✅ **RENFORCÉ** (2026-07-26) | La clause **« that unit is unengaged »**, absente de la config et donc de la 1ʳᵉ implémentation, est branchée (`_heavy_unit_is_engaged`, même prédicat que le gate de tir 10.06). Clause **« pas posée ce tour » : CÂBLÉE** sur le nouveau champ moteur `deployed_on_turn` (posé à la création de l'unité et au commit de déploiement — `_apply_deploy_plan` ; 0 = pré-bataille, N = arrivée de réserve au tour N, `None` = hors board). Aucune arrivée en cours de bataille n'existe encore (réserves 20 non modélisées) mais la clause n'aura pas à être retouchée le jour où elles arrivent. **C'est la source unique partagée avec la feature d'observation déploiement/réserve** (`V11_audit_observation.md` §8). Clause « aucune figurine > 3" » : ✅ **EXACTE depuis le 2026-07-26** — `moved_distance_by_model` (distance de CHEMIN accumulée par `commit_move`, hex géodésique en gym ET euclidienne any-angle en PvP) remplace la borne conservatrice « aucune figurine n'a bougé ». Détail et périmètre → **§9.2.6**. | `test_heavy_shoot.py` (**13** : bonus si stationnaire+unengaged ; pas de bonus si engagé / **posé ce tour** / **une figurine a parcouru > 3"** ; bonus CONSERVÉ jusqu'à 3" inclus (comparaison stricte) ; bonus conservé si posé au tour précédent ; rien sans HEAVY). |
| **reroll_charge** (`unit_rules.json`) | ✅ **IMPLÉMENTÉ** (2026-07-26) | Règle d'unité déclarée par 4 unités Orks et **totalement absente du code** (grep zéro). `roll_charge_distance` + `unit_can_reroll_charge` mutualisés ; relance sur le seul critère exact : le jet n'atteint **aucune** cible/destination légale (gym `squad_charge` ; PvP roll-first `charge_target_selection`). Un dé ne se relance qu'une fois. ⚠️ **Historique du 2026-07-26** : cette ligne avait affirmé à tort que la tranche « débloque 19.04 » ; le fold n'écrivait jamais les règles du character sur l'escouade, donc le `reroll_charge` d'un leader attaché était **perdu**. Corrigé par 19.04-a/b/c le 2026-07-27 (ligne ci-dessous) : `_unit_has_rule_effect` lit l'union en vigueur, un Captain attaché confère bien son reroll et le retire en mourant. | `test_reroll_charge.py` (**5**, dont l'ancrage donnée « des unités Orks déclarent bien la règle »). ⚠️ Ces tests fabriquent un `game_state` à la main et ne passent par **aucune** unité attachée réelle — c'est ce qui a laissé passer le trou 19.04 ; le câblage attaché est verrouillé par `test_attached_units_abilities_19_04.py` sur un vrai chargement de scénario. |
| **19.03 — union des keywords** | ✅ **FAIT** (2026-07-26) | `_build_enhanced_unit` : l'unité porte l'UNION des keywords de ses composants (prérequis d'ANTI-X). Keywords **propres** conservés par figurine pour les règles « each model » (06.03). `hideable` recalculé sur l'union. | `test_attached_units_keywords_19_03.py` (**2**, e2e via le vrai chargement de scénario). |
| **19.04 — abilities in attached units** | ✅ **FAIT dans le vif — 3 tranches a/b/c** (2026-07-27, commits `abcc80ca`, `57e53318`, `ee479cb3`) | `unit["UNIT_RULES"]` est désormais l'**union EN VIGUEUR**, dérivée de deux sources immuables posées au build : `_UNIT_RULES_OWN` (datasheet de l'escouade + règles propres de ses figurines natives) et `_ATTACHED_RULE_GROUPS` (un groupe par character replié, clé = id de l'unité d'origine, [game_state.py:1128](../../engine/game_state.py#L1128)). Les marqueurs de RÔLE ne remontent jamais (`strip_role_rules`, piège 1 ci-dessous). L'extinction est recalculée **à chaque mort de figurine** par `recompute_unit_rules_in_effect` ([shared_utils.py:664](../../engine/phase_handlers/shared_utils.py#L664)), appelée depuis `destroy_model` — point unique de retrait — avant ses `return` anticipés (une unité rasée doit aussi voir ses règles s'éteindre, PDF 25). Fenêtre 19.04-c : une source tuée `reason=="combat"` est inscrite dans `rule_sources_in_grace` **porté par l'allocation en cours** ; elle expire d'elle-même à `_finalize_manual_allocation`, qui recalcule les squads concernés après suppression de l'allocation → aucun état en sursis ne survit à l'activation. | `tests/unit/engine/test_attached_units_abilities_19_04.py` (**14**, e2e via le vrai chargement de scénario ; verts au 2026-07-27). Contre-épreuves : groupes attachés neutralisés → rouge (a) ; appel neutralisé dans `destroy_model` → 4 rouges (b) ; sursis neutralisé → 2 rouges et fenêtre jamais refermée → 1 rouge (c). |
| ~~~10 règles observées non appliquées~~ | ✅ **SOLDÉ** — il n'en reste **aucune** | Les 9 règles listées au 2026-07-24 sont traitées : TORRENT, TWIN_LINKED, SUSTAINED_HITS, LETHAL_HITS, MELTA, ANTI_* ✅ ; EXTRA_ATTACKS ✅ ; PSYCHIC ✅. **Seule INDIRECT_FIRE (24.19) reste** — ce n'est pas une règle de résolution mais un TYPE DE TIR entier (10.07 : tirer sans ligne de vue, la cible bénéficiant du couvert), donc un chantier à part et non un portage. **Laissée ouverte volontairement** ; 2 armes concernées, aucune dans les rosters de training. ⚠️ Dépendance déjà notée : quand elle sera faite, son couvert devra passer par un point qu'[IGNORES COVER] 24.18 annule aussi. | — |
| Suppression du code mort (fin P1) | ✅ **FAIT** (2026-07-28, §0hist.38) | `_attack_sequence_rng` (**184 lignes**, 193 avec sa bannière orpheline) + 7 états `_rapid_fire_*` + helper `_get_rapid_fire_parameter` supprimés de `shooting_handlers` ; les **5** fichiers de tests qui l'appelaient (138 assertions) re-pointés sur le chemin vif. Reliquat `w40k_core` (7 clés de purge, log de debug, champ `rapid_fire_bonus_shot`) laissé à l'agent §0.40 qui édite ce fichier en parallèle. | Les 5 fichiers migrés (+1 déjà migré) et les 6 fichiers vifs complétés = **110 tests verts** ; contre-épreuve : **13 mutations** du vif en deux salves → **13 rouges**, restauration → vert. La 2ᵉ salve a démasqué 3 tests neufs non discriminants, corrigés (détail en §0hist.38). |

**Choix d'implémentation IGNORES_COVER (vérifiés).** `_cover_worsened_bs` recevait `attacker`
mais pas l'arme ; l'appelant `_manual_roll_intent` résout déjà `weapon` juste avant l'appel
([shared_utils.py:6269](../../engine/phase_handlers/shared_utils.py#L6269)) → signature étendue de
`weapon` (appelant unique, vérifié : aucun autre site ni test n'appelait la fonction). Le helper
`weapon_has_rule` gère les trois formes d'entrée WEAPON_RULES (`'NAME'`, `'NAME:param'`, objet
`.rule`) et est réutilisable par les tranches P1 suivantes.

⚠️ **Dépendance à honorer quand INDIRECT_FIRE sera implémenté** : 24.18 dit « cannot have the
benefit of cover … *including from rules that give a model or unit the benefit of cover* ». Or
INDIRECT_FIRE (10 Shooting) accorde le cover à la cible. Aujourd'hui la SEULE source de cover est
`compute_unit_los`, que le court-circuit évite → conforme. Mais la tranche INDIRECT_FIRE devra
router SON cover par un point qu'IGNORES_COVER annule aussi, sinon 24.18 sera violée pour la
combinaison des deux règles.

**Choix d'implémentation rerolls tir (vérifiés).** Conformité tranchée sur la source de vérité
`config/unit_rules.json`, PAS sur le seul plan : `reroll_1_towound` (« When this unit makes an
attack, it can reroll rolls of 1 for the wound rolls ») et `reroll_towound_target_on_objective`
(« …reroll the wound rolls if the target unit is on an objective ») n'ont **AUCUNE restriction de
phase** → ils s'appliquent au tir comme au fight. Par contraste `reroll_1_tohit_fight` /
`reroll_1_save_fight` portent « During the fight phase » + suffixe `_fight` : mêlée-only. La
distinction de nommage est donc **délibérée** — l'asymétrie tir/fight préexistante était bien un
bug, et l'application au tir est la correction juste (pas une sur-application). Implémentation en
**miroir exact** du fight (helper `_unit_has_rule_effect`, mécanique un-reroll-par-dé) ; la
condition d'échec du tir est préservée → zéro régression quand aucune règle de reroll n'est
présente. Effet de bord traité : `_manual_roll_intent` résout désormais attaquant/cible via
`get_unit_by_id` → exige `unit_by_id` dans le game_state (toujours présent en runtime ; fixture
de `test_ignores_cover.py` complété en conséquence).

✅ **État de la suite (mis à jour 2026-07-25)** : les **15 échecs** qui étaient préexistants au
2026-07-24 (`test_deployment_per_model_commit`, `test_fight_target_selection_no_fallback`,
`test_game_state_contract`) ont été **corrigés** (contrats périmés post-V11 — commits `38362e81`,
`b9dc9916`). `tests/unit/` re-vérifiée verte avant la tranche rerolls ; validation complète
post-rerolls en cours. La condition [§8.5](V11_tranches.md#s8.5) est donc rétablie.

**Session 2026-07-25 (nuit) — 4 tranches livrées + 1 différée.** Portées dans le vif, chacune
avec test e2e + contre-épreuve mutation, suite `tests/unit/` re-vérifiée verte et commit
séparé : `closest_target_penetration`, `HEAVY`, `RAPID_FIRE`, `DEVASTATING_WOUNDS` (cf.
lignes ✅ ci-dessus). Effet de bord traité : `test_ignores_cover` utilisait `["HEAVY"]` comme
arme « quelconque » supposée inerte — basculé sur arme nue une fois HEAVY vif. Méthode :
conformité tranchée sur `config/weapon_rules.json` (source de vérité projet des règles d'armes)
quand elle diffère du PDF 24 — écarts explicitement documentés par tranche.

<a id="s9.2.2"></a>
### 9.2.2 HAZARDOUS (24.15) — LIVRÉE le 2026-07-26 (l'analyse de 2026-07-25 reste valide)

L'entrée du 2026-07-25 concluait « intégration multi-systèmes, pas un portage » : c'était exact,
et c'est ainsi qu'elle a été traitée. Ce qui a été fait, point par point :

- **Point de déclenchement** = `_finalize_manual_allocation` (shared_utils), le seul endroit qui
  signifie « l'unité a résolu TOUTES ses attaques », commun au tir et au combat. Pas
  `_manual_roll_intent` (per-intent/per-cible), conformément à l'analyse.
- **Nombre de jets** = armes HAZARDOUS **sélectionnées** au Select Weapons step, comptées à la
  construction de l'allocation (`_count_selected_hazardous_weapons`, couples figurine×arme
  distincts) et stockées dans l'état d'allocation avant purge des intents. Ce n'est **pas** un
  jet par figurine (c'est la règle du Desperate Escape 09.07, désormais distinguée par le
  paramètre `n_rolls` de `roll_hazard_for_unit`).
- **Chemin de reprise** : `_resume_after_hazard` était câblé en dur sur le retour à la phase de
  move (Desperate Escape). Il lit maintenant `game_state["hazard_origin"]` : `shoot`/`fight` →
  l'activation est terminée, rien à reprendre ; `move` → comportement historique intact.
- **Gym** : `is_programmatic_owner` sur le propriétaire du TIREUR → `auto_resolve=True`,
  résolution inline, aucun prompt. Verrouillé par 6 tests e2e headless.
- **PvP humain** : le prompt d'allocation des blessures mortelles est rendu
  (`manual_allocation_waiting_payload(HAZARD_CTX)`), et la ligne de log `[HAZARD]` est **publiée
  AVANT** que le joueur ne choisisse ses pertes (correction du 2026-07-26, demande utilisateur :
  on ne désigne pas des figurines sans savoir combien de blessures mortelles on encaisse ni d'où
  elles viennent). Mise en œuvre : `append_action_log` mute l'entrée en place et en garde la
  référence — les `hazardDetails` complètent CETTE ligne pendant l'attribution au lieu d'en créer
  une seconde ; `_finalize_hazard_alloc_log` ne ré-émet plus rien et `_finalize_hazard_log`
  (émission différée) est supprimé. Vaut aussi pour le Desperate Escape 09.07, même chemin.

<a id="s9.2.3"></a>
### 9.2.3 Socle de séquence d'attaque commun tir/mêlée — `attack_sequence.py` (2026-07-26)

**Trou majeur trouvé en cours de route** : `_manual_roll_fight_intent` ne lisait **aucune** règle
d'arme (zéro occurrence de `WEAPON_RULES` dans `fight_handlers.py`). Les 6 règles portées le
2026-07-25 étaient donc tir-only, alors que `relic_greataxe` et `thunder_hammer_terminator`
déclarent [DEVASTATING WOUNDS], `eviscerator` [SUSTAINED HITS 1], `urty_syringe`
[ANTI-INFANTRY 1+] + [EXTRA ATTACKS] + [PRECISION].

Plutôt que d'écrire dix règles deux fois, la boucle de jets est désormais **unique** :
`engine/phase_handlers/attack_sequence.py`, consommée par les deux rollers. Y vivent la notion
de **touche/blessure critique** (05.01/05.02) et tout ce qui s'y accroche : TORRENT, SUSTAINED
HITS, LETHAL HITS, TWIN-LINKED, ANTI-X, DEVASTATING WOUNDS. Reste chez l'appelant ce qui est
propre à la phase : pool d'attaques (BLAST/RAPID FIRE/CLEAVE/EXTRA ATTACKS), seuil de touche
(couvert/HEAVY/PSYCHIC), AP effectif, dégâts et allocation.

Effets de bord corrigés au passage :
- **05.01 en mêlée** : le test `hit_roll < ws` laissait passer un 1 non modifié si le seuil
  valait 1. Le socle applique la règle « 1 rate toujours / 6 est un critique » des deux côtés.
- **Ordre des dés préservé** (touche → [reroll] → blessure → [reroll] → sauvegarde) : les tests
  déterministes antérieurs restent valides sans modification.

<a id="s9.2.4"></a>
### 9.2.4 Écarts PDF vs `config/*.json` — arbitrage utilisateur du 2026-07-26

Consigne : **« les règles à suivre à 100 % sont dans `Documentation/40k_rules/` »**. Le PDF prime
donc sur la config quand ils divergent. Trois divergences réelles ont été trouvées et tranchées :

| Règle | `config/weapon_rules.json` | PDF (appliqué) |
|---|---|---|
| HAZARDOUS | « roll 1 D6, sur un **1** → **3 MW** » | 24.15 + 06.03 : **1-2** → **1 MW** (3 seulement si CHAQUE figurine est MONSTER/VEHICLE) |
| CLEAVE | « touche X figurines supplémentaires dans l'ER » | 24.06 : **X dés d'attaque additionnels par tranche de 5 figurines** cibles, si une seule cible |
| HEAVY | « +1 si Remained Stationary » | 24.16 : **unengaged** ET pas posée ce tour ET aucune figurine > 3" |

Les tranches du 2026-07-25 avaient suivi la config (arbitrage d'alors, documenté) ; HEAVY est
mis en conformité ci-dessus, les deux autres sont nées conformes au PDF.

⚠️ **Conséquence à connaître** : `config/weapon_rules.json` contient donc des descriptions
**fausses** pour HAZARDOUS et CLEAVE. Elles n'ont plus aucun consommateur de résolution (le code
suit le PDF), mais elles restent lues comme documentation. **Décision utilisateur attendue** :
corriger le fichier de config pour qu'il décrive les vraies règles, ou le marquer explicitement
comme non normatif.

<a id="s9.2.5"></a>
### 9.2.5 Ce que l'agent voit des règles — ✅ LIVRÉ (2026-07-26)

> **Était** : « les règles sont vives dans le moteur, mais l'observation squad (199-d) ne contient
> aucun profil d'arme ni bit de règle — l'agent les subit sans les percevoir ». **C'est fait.**
> `obs_size` **199 → 1011** (`vec_cont` 459, `vec_bin` 552) ⇒ **retrain from scratch**
> (déjà acté ; les `.zip` existants sont incompatibles, par construction).
>
> ⚠️ **MAJ 2026-07-26** : le contrat décrit ici (vecteur PLAT `vec_cont`/`vec_bin`) a été
> REMPLACÉ par les **tenseurs d'entités** de [§0.30](V11_agent_rework.md#s0.30) T-D (`obs_size` **20626** depuis [§0.32](V11_agent_rework.md#s0.32)). Ce qui suit reste
> la spécification de CE QUI est observé (profils d'armes, règles, mise en place, distance
> parcourue) ; la FORME, elle, se lit dans `V11_entity_encoder_pointer.md` §6 et dans l'en-tête
> de `build_squad_observation`.

**Ce qui a été ajouté à l'observation squad** (détail de layout : en-tête de
`build_squad_observation`, source unique) :

1. **Profils d'armes bruts + bits/params de règles** — nouveau module
   [`engine/observation_weapon_profiles.py`](../../engine/observation_weapon_profiles.py),
   **encodeur unique consommé par mon escouade ET par les slots ennemis** (un encodeur par camp
   aurait dérivé). Un profil = `{NB, ATK, STR, AP, DMG, portée, **nb de porteurs vivants**}` +
   6 params de règles (RAPID FIRE / SUSTAINED HITS / MELTA / CLEAVE / BLAST X, et le Y+ de
   ANTI) + 12 drapeaux (DEVASTATING WOUNDS, LETHAL HITS, TORRENT, TWIN-LINKED, EXTRA ATTACKS,
   PRECISION, PSYCHIC, HAZARDOUS, HEAVY, IGNORES COVER, PISTOL, ASSAULT) + le **one-hot du
   keyword ciblé par ANTI-X** + un mask. **13 cont + 18 bin par profil.**
   - Le **compteur de porteurs** est ce qui distingue « 1 rokkit » de « 9 shootas » : le volume
     de feu est `porteurs × NB`. Les profils sont regroupés par **identité de caractéristiques**
     (deux noms différents, même profil = un seul slot ; une arme « à profils multiples » = une
     entrée par profil, aucun cas particulier).
   - **[INDIRECT FIRE] 24.19 est délibérément ABSENTE** : elle n'est pas implémentée (cf. la
     ligne « 10 règles observées » de §9.2.1). Un bit pour une règle inerte est du bruit pur.
   - ⚠️ **Réserve sur [ASSAULT] et [PISTOL]** : bits conservés (effet réel côté PvP), mais le
     gate de tir gym rend leurs types de tir (10.05 / 10.06) INATTEIGNABLES pour l'agent —
     trou de conformité trouvé le 2026-07-26, **ouvert** : voir **§9.2.7**.
   - **K par camp, mesuré** : mon escouade **6 profils de tir + 5 de mêlée** — le maximum
     observé sur les rosters d'entraînement réels, persos attachés compris, donc **mes propres
     capacités ne sont jamais tronquées** ; slots ennemis **2 tir + 1 mêlée**, ordonnés par
     nombre de porteurs (le gros du volume de feu adverse). ⚠️ **Arbitrage assumé** : 11 profils
     × 5 escouades ennemies coûteraient 5 fois le vecteur entier pour une information marginale.
     Tout dépassement de K est **LOGUÉ** (`add_debug_file_log`), jamais silencieux.
2. **Mise en place / réserve** — one-hot 3 états (pas sur le board / posée avant la bataille /
   arrivée en cours de bataille) **+ le bit « posée CE tour »**, dérivés de `deployed_on_turn`,
   la **source unique déjà utilisée par la clause 2 de [HEAVY] 24.16**. Le one-hot seul ne dit
   pas si la pose est de ce tour — or c'est ce point-là qui supprime le bonus.
3. **Distance parcourue ce tour, par figurine** — nouvelle donnée moteur
   `moved_distance_by_model`, accumulée par `commit_move` en **distance de CHEMIN** ; exposée en
   **max** (porte la clause de règle) et **somme** (toute l'escouade a-t-elle bougé, ou une
   seule figurine). Voir §9.2.6 : elle rend la **clause 3 de [HEAVY] 24.16 EXACTE**.

**Verrous** : `tests/unit/engine/test_squad_obs_weapon_profiles.py` (**19**) et
`test_moved_distance_and_deploy_obs.py` (**10**). Contre-épreuves mutation : compteur de porteurs
figé + one-hot ANTI éteint + ordre des profils changé → **6 rouges** ; mesure à vol d'oiseau +
accumulation remplacée par écrasement → **2 rouges** ; restauré → verts. Les 6 fichiers de tests
d'observation squad préexistants restent verts **sans modification** (ils passent par les
accesseurs de layout, pas par des index recopiés).

**Ce que cette tranche NE fait PAS** (et pourquoi) :
- **Bloc E « escouades amies »** : toujours différé, il part avec l'archi set-based (le faire en
  K slots fixes exigerait d'inventer un ordre qu'aucune action ne consomme — cf.
  `V11_audit_observation.md` §11).
- **Listes de longueur variable** (fin des plafonds K) : idem, c'est l'étape architecture.
- ✅ **Les règles d'UNITÉ sont observées depuis le 2026-07-27** ([§0.31](V11_agent_rework.md#s0.31), commit `0fb94a01`) —
  13 bits d'EFFET par entité, amies ET ennemies, dans `UNIT_BIN_FIELDS`. Le constat qui suit
  décrit l'état AVANT ce correctif ; il est conservé parce qu'il documente le motif de trou.
- 🔴 ~~**Les règles d'UNITÉ (`config/unit_rules.json`) ne sont PAS observées**~~ — constat vérifié le
  2026-07-27, **non documenté jusqu'ici, ni comme trou ni comme choix**. Cette tranche a rendu
  visibles les règles d'**armes** (profils + drapeaux) ; les règles d'unité, elles, n'existent
  dans aucun schéma du pipeline squad : `UNIT_CONT_FIELDS`/`UNIT_BIN_FIELDS`
  ([observation_entities.py](../../engine/observation_entities.py), contrat unique des tenseurs
  d'entités) n'ont aucun champ de règle, et `unit_has_rule_effect` n'apparaît qu'à un seul
  endroit de tout l'encodage : `_encode_rule_features`, appelée **uniquement** par
  `build_observation` — le pipeline **mono-figurine legacy** (`obs_size` 357). Le routage
  ([w40k_core.py](../../engine/w40k_core.py) `_build_observation`) envoie le pipeline squad sur
  `build_squad_observation`, qui ne passe jamais par là. ⚠️ `AI_OBSERVATION.md` décrit bien
  « 12 unit-rule flags », mais dans le layout `obs[314:346]` du legacy : lu vite, il fait croire
  l'inverse. Concerné : les 12 règles vives (`reroll_charge`, `closest_target_penetration`,
  `charge_after_advance`, `charge_after_flee`, `charge_impact`, `reactive_move`,
  `move_after_shooting`, `shoot_after_advance`, `shoot_after_flee`, `reroll_1_towound`,
  `reroll_towound_target_on_objective`, `reroll_1_tohit_fight`, `reroll_1_save_fight`) —
  l'agent les subit sans les percevoir, exactement le constat qui avait motivé cette section
  pour les règles d'armes. **Enjeu accru depuis 19.04** (§9.2.8) : une escouade menée par un
  character porte désormais les règles de son leader, et cette information reste invisible.
  ~~**Ouvert — arbitrage de périmètre à faire**~~ → **TRAITÉ le 2026-07-27, cf. [§0.31](V11_agent_rework.md#s0.31).**

<a id="s9.2.7"></a>
### 9.2.7 ✅ CORRIGÉ le 2026-07-26 (tranche T-B) — les types de tir 10.05 / 10.06 existent enfin pour l'agent

**Trouvé en vérifiant, à la demande de l'utilisateur, l'affirmation « seules les règles à effet
réel sont exposées » de §9.2.5.** Elle est FAUSSE pour deux bits, et la cause n'est pas
l'observation : c'est le moteur.

**Le fait, lu dans le code.** Le gate de tir du chemin squad/gym
([`build_squad_action_mask`](../../engine/phase_handlers/shared_utils.py), branche `phase ==
"shoot"`) calcule :
`can_shoot = not has_fled and not has_advanced and not has_shot and not in_er` — **sans aucune
exception d'arme**.

**Ce que disent les PDF** (lus, pas supposés) :
- **10.05 ASSAULT SHOOTING** — éligible si : « Unengaged **and made an advance move this turn** »
  ET l'unité a ≥1 arme [ASSAULT]. *While shooting* : seules les armes [ASSAULT] peuvent être
  sélectionnées. ⇒ `has_advanced` ne doit PAS fermer le tir quand une arme [ASSAULT] est portée.
- **10.06 CLOSE-QUARTERS SHOOTING** — éligible si : « **Engaged** and did not make an advance
  move this turn » ET l'unité a ≥1 arme [CLOSE-QUARTERS] **ou est MONSTER/VEHICLE**. *While
  shooting* : les figurines peuvent cibler les unités avec lesquelles l'unité est engagée.
  ⇒ `in_er` ne doit PAS fermer le tir dans ces cas. **24.27 : [PISTOL] et [CLOSE-QUARTERS] sont
  identiques à toutes fins de règles** — donc la règle porte bien sur les armes [PISTOL] du
  projet.

**Portée du trou.** Le chemin **PvP/mono-figurine** connaît les deux règles
(`_weapon_has_assault_rule` → `weapon_availability_check` ; `_weapon_has_pistol_rule` → sélection
d'arme et allocation en zone d'engagement, `shared_utils` ~5030/5081/5802/6072). Le chemin
**squad/gym** ne les connaît pas. C'est **exactement le motif de §9.1** — une règle vive sur un
chemin, absente de l'autre — et le motif récurrent du document (« code testé mais jamais appelé »,
« migration partielle d'un chemin »).

**Sens de l'écart** : le gate gym est **plus STRICT** que les règles (il refuse des tirs légaux),
donc jamais laxiste. Conséquence : l'agent ne peut pas apprendre le tir d'assaut ni le tir à bout
portant, et les 30 armes [PISTOL] / 22 [ASSAULT] des armories perdent leur intérêt tactique côté
IA. Côté observation, les bits `PISTOL` et `ASSAULT` décrivent donc une capacité inexploitable en
gym — ils sont **conservés** (l'effet PvP est réel) avec la réserve écrite dans
`observation_weapon_profiles.py`.

**Statut : ✅ FERMÉ le 2026-07-26 par la tranche **T-B** du chantier dédié [`V11_entity_encoder_pointer.md`](V11_entity_encoder_pointer.md) (tranche T-B), avec 5 autres trous trouvés le même jour.** Le résolveur `resolve_squad_shooting_type` ouvre 10.05 et 10.06, le masque teste toute arme éligible, et le volet MONSTER/VEHICLE de 10.06 est implémenté (13 tests, mutations → 5 rouges). ⚠️ **Résidu** : le chemin PvP/mono ne connaît toujours pas le volet MONSTER/VEHICLE — voir §1.9 du chantier. Périmètre d'origine — c'est une **nouvelle règle à implémenter**
(deux types de tir, avec restriction d'armes et restriction de cibles), pas un correctif de la
tranche observation. Périmètre estimé, à arbitrer : (1) gate `build_squad_action_mask` ;
(2) restriction « seules les armes [ASSAULT] » / « seules les armes [PISTOL] » à la sélection
d'armes du squad ; (3) restriction de cible 10.06 (uniquement les unités engagées) ; (4) miroir
PvP à vérifier (le chemin mono connaît les helpers mais pas forcément les deux types complets) ;
(5) tests par règle + contre-épreuve mutation.

<a id="s9.2.6"></a>
### 9.2.6 [HEAVY] 24.16 clause 3 — passage à la clause EXACTE (2026-07-26)

L'implémentation du 2026-07-26 appliquait la borne **conservatrice** « aucune figurine n'a
bougé » faute de distance par figurine. Elle est remplacée par la clause du PDF : **« no model in
that unit has moved more than 3" this turn »**, comparaison **stricte** (3" pile conserve le
bonus). Conséquence de jeu : une escouade qui se repositionne de 2" garde désormais son +1, ce
que le moteur lui refusait à tort.

**La donnée** est la distance de **CHEMIN**, pas l'écart départ↔arrivée — contourner un mur coûte
plus cher. C'est le point qui empêche la règle de devenir laxiste, et il est mesuré **dans les
deux métriques du moteur** :
- métrique `hex` (gym) → BFS géodésique `geodesic_move_reach`, avec la définition **partagée** du
  trajet légal (`build_move_transit_blocked`) ;
- métrique `euclidean` (PvP) → champ any-angle `_euclidean_move_field`, **la primitive même du
  pool de destinations par-figurine**. Sans ce second cas, PvP aurait mesuré à vol d'oiseau et la
  règle serait devenue **laxiste** là-bas (le contraire de la borne d'avant).
- FLY (21.03) traverse tout : le champ sans obstacle redonne la ligne droite, aucun cas
  particulier.

**Périmètre assumé** : seuls les moves de la **phase de mouvement** (`normal`/`advance`/
`fall_back`) sont comptabilisés. Ce n'est pas une omission — l'ordre des phases (**PDF 07.02** :
Commande, Mouvement, **Tir**, Charge, Combat) garantit qu'au moment du tir, aucun move de charge
ni de pile-in n'a pu avoir lieu dans le même tour. Les compter avec la métrique du move donnerait
un chiffre faux (ils relèvent d'une autre géométrie) ; à vol d'oiseau, un chiffre sous-estimé.

`moved_distance_by_model` est remis à zéro **au même endroit que `units_moved`**
(`command_phase_start` + `_tracking_cleanup`) : c'est la version continue du même fait.
Verrou : `test_heavy_shoot.py` passe de 7 à **13** tests (>3" perd / ≤3" garde / 3" pile garde /
une AUTRE figurine de l'escouade suffit à annuler) ; mutation « seuil 3" → seuil 0 » → 2 rouges.

Corrigé en revanche cette nuit : le pipeline mono-figurine legacy **crashait** (`KeyError`) sur
toute unité portant CLEAVE ou PRECISION — donc sur Warboss, Bigboss et PainBoy, tous présents
dans les rosters de training. Les deux canaux sont ajoutés (`obs_size` legacy 357 → **359**) ;
le pipeline squad V11 (199) n'est pas concerné.

<a id="s9.2.8"></a>
### 9.2.8 AUDIT RÈGLE 19 (Attached units) — 19.01/19.02/19.03 conformes ; **19.04 était absent, ✅ LIVRÉ le 2026-07-27** (a/b/c)

> **MAJ 2026-07-27 — le trou décrit ci-dessous est refermé.** Les trois tranches proposées en fin
> de section ont été exécutées et commitées : `abcc80ca` (19.04-a, résolution unit-wide sur
> figurines vivantes, rôles exclus), `57e53318` (19.04-b, extinction à la mort de la dernière
> figurine source, les deux sens), `ee479cb3` (19.04-c, fenêtre « jusqu'à la fin des attaques de
> l'attaquant »). Verrou : `tests/unit/engine/test_attached_units_abilities_19_04.py` (**14**
> tests e2e sur chargement réel de scénario, verts). Détail d'implémentation → ligne « 19.04 » du
> tableau §9.2.1. **Le constat ci-dessous est conservé tel quel comme trace d'audit** (il décrit
> l'état AVANT correction) ; les ❌ de sa table valent au 2026-07-26.

Audit refait de bout en bout après relecture des PDFs **19**, **24** (p5-p8 : LEADER 24.22,
LONE OPERATIVE 24.24, PRECISION 24.28, SUPPORT 24.34), **25** (p1-p3 : starting strength,
destroyed, mixed keywords, revived), **05** p5 et **08** (battle-shock 08.03).

**Conforme (vérifié clause par clause, cf. la table règle 19 d'[AI_TURN.md](../AI_TURN.md)) :**
19.01 (les 4 gardes du fold + les clauses structurelles), 19.02 (T bodyguard + repli
leader-only + trigger de destruction), 19.03 (union des keywords / keywords propres par
figurine). Clauses connexes sans objet et documentées : Lone Operative (aucune donnée),
Revived (aucune mécanique), Starting strength (correct par construction du fold).

**Le trou : 19.04 « Abilities in attached units ».**

Ce que dit le PDF : les règles qui affectent une figurine précise ne valent que pour elle ;
**toutes les autres s'appliquent à chaque figurine de l'unité attachée**, jusqu'à ce que la
source soit détruite — dernière figurine du leader/support, dernière figurine du bodyguard, ou
la figurine porteuse. Et si cette dernière figurine tombe sous une attaque, la règle **survit
jusqu'à ce que l'unité attaquante ait résolu toutes ses attaques**.

Ce que fait le code : [`_fold_attached_characters`](../../engine/game_state.py#L728) replie le
character en figurine ; ses `UNIT_RULES` sont copiées sur `models[i]`
([game_state.py:1019](../../engine/game_state.py#L1019)) et l'escouade garde les seules
`UNIT_RULES` de son propre `unit_type` ([game_state.py:918](../../engine/game_state.py#L918)).
Or **tous** les consommateurs interrogent l'escouade : `_unit_has_rule_effect`
([shared_utils.py:1904](../../engine/phase_handlers/shared_utils.py#L1904)), ses trois
ré-exports (`shooting_handlers:304`, `charge_handlers:52`, `fight_handlers:86`), les lectures
directes de `w40k_core` (2341 / 2426 / 2583) et l'observation IA
([observation_builder.py:2386](../../engine/observation_builder.py#L2386)). Aucun site ne
regarde `models[i]["UNIT_RULES"]`.

Reproduction (Intercessor 101 + `CaptainPowerWeaponBolter` 102 attaché, chargement réel) :

```
UNIT_RULES escouade      : []
UNIT_RULES par figurine  : [[], ['reroll_charge', 'leader']]
unit_can_reroll_charge(101) = False        # le Captain porte bien reroll_charge au registry
```

Ce n'est donc pas « l'unité ne profite pas du leader » mais « **le leader perd sa règle** » :
autonome il relance sa charge, attaché il ne la relance plus. Le scénario PvP de référence
attache un `CaptainTerminatorRelicWeaponBolter` et un `LibrarianTerminator`
([scenario_pvp.json:8-9](../../config/board/44x60x5/scenario/scenario_pvp.json#L8-L9)) : le bug
est vif en PvP **et** en gym.

**Trois manques distincts, à ne pas confondre :**

| # | Manque | État | Impact données actuelles |
|---|---|---|---|
| a | **Montant** — la règle du leader/support ne remonte pas à l'unité | ❌ | `reroll_charge` de 9 characters SM/Ork ; tout `unit_rules.json` futur porté par un character |
| b | **Descendant** — la règle du bodyguard reste active après la mort de sa dernière figurine bodyguard | ❌ | un character survivant seul continue de bénéficier de `charge_impact`, `cunning_hunters`, `closest_target_penetration`… du squad mort |
| c | **Fenêtre 19.04** — la règle survit « until the attacking unit has resolved all of its attacks » | ❌ | conséquence de (a)/(b) ; s'aligne sur la fenêtre déjà utilisée par HAZARDOUS/`_finalize_manual_allocation` |

**Pourquoi une union statique au chargement serait fausse** : 19.04 est dynamique. Fusionner les
`UNIT_RULES` dans `_build_enhanced_unit` réglerait (a) mais **installerait** (b) — la règle
resterait après la mort de sa source. La résolution doit se faire sur les figurines **vivantes**
(`models_cache` + `squad_models`), au point de lecture.

**Deux pièges de conception :**
1. Les rôles `leader` / `support` / `sergeant` / `special_weapon` sont des **marqueurs
   par-figurine** consommés par `ROLE_TIER` / `_is_character_role` (ordre d'allocation 05.03,
   T bodyguard 19.02). Les remonter à l'escouade casserait 19.02. Ils doivent être exclus.
2. Le PDF exclut aussi les règles « affecting a single specified model » (enhancement/wargear).
   `config/unit_rules.json` ne porte aucun marqueur de portée : tout ce qui y figure est
   unit-wide. Écart config/PDF **sans conséquence aujourd'hui** (aucun enhancement modélisé) —
   à trancher le jour où une règle par-figurine sera déclarée. Précédent §9.2.4 : on suit la config.

**Tranches** — ✅ **les trois sont exécutées et commitées le 2026-07-27** (cf. l'encadré MAJ en tête
de section) : **19.04-a** résolution unit-wide sur figurines vivantes, rôles exclus, avec test e2e
sur chargement réel de scénario (`abcc80ca`) ; **19.04-b** extinction à la mort de la dernière
figurine source, les deux sens (`57e53318`) ; **19.04-c** fenêtre « jusqu'à la fin des attaques de
l'attaquant » (`ee479cb3`). Les deux pièges de conception ci-dessus ont été honorés : les rôles
sont strippés à la remontée, et la résolution est dynamique (pas d'union statique au chargement).

<a id="s9.3"></a>
### 9.3 P2 — Mécanisme générique « décision agent » — ✅ LIVRÉ (2026-07-28, cf. §9.3bis)

> 🔴 **PORTÉE RÉDUITE le 2026-07-28 ([§0.41](V11_agent_rework.md#s0.41)) — lire ceci avant d'appliquer cette section.**
> Le `CHOICE_0..K-1` décrit ci-dessous suppose des logits produits par des **colonnes denses de
> `action_net`**. Cette section date du 2026-07-14, donc d'**avant** [§0.30](V11_agent_rework.md#s0.30) T-E (tête pointeur) et
> [§0.32](V11_agent_rework.md#s0.32) T-G (tête 1x1) — qui ont supprimé ce motif : une colonne dense par rang de candidat
> n'apprend rien des autres et ignore *ce qu'est* le candidat qu'elle score.
> - **Candidats = entités déjà observées** (cible de mêlée, de charge, de tir, unité à activer) :
>   ➜ **une dimension d'action par slot + tête pointeur**, PAS `CHOICE_k`. Livré et verrouillé pour
>   la cible de mêlée (P3-1) → **[§0.41](V11_agent_rework.md#s0.41)**. C'est le patron à suivre.
> - **Candidats non-entité** (rule-choice, FLY oui/non, pile-in oui/non) : le mécanisme générique
>   ci-dessous reste pertinent — à ouvrir quand une telle décision est **réellement exercée par les
>   rosters du training** (ce n'est pas le cas du rule-choice, cf. [§0.41](V11_agent_rework.md#s0.41)).
> Le paragraphe `action_net → Linear(320, 18)` ci-dessous reste valide dans son principe (les
> colonnes de move/tir/combat sont inertes) ; le compte « 18 » est périmé.

Un seul mécanisme pour tous les choix joueur, au lieu d'actions ad hoc par décision :
- quand le moteur atteint un point de choix joueur en gym, au lieu d'appeler une heuristique
  `_ai_select_*`, il pousse un `pending_agent_decision` (type + liste ORDONNÉE et STABLE de
  ≤ K candidats) ;
- le masque expose K actions génériques `CHOICE_0..K-1` ; l'observation gagne un bloc
  « contexte de décision » (type one-hot + features par candidat) ;
- l'agent choisit, le moteur applique. **Miroir exact des prompts PvP `waiting_for_player`**
  (même sémantique, consommateur différent) — conforme à la règle projet « le flux gym copie
  le flux PvP » ;
- les heuristiques `_ai_select_*` sont CONSERVÉES pour le bot adversaire (GreedyBot) uniquement.

Impact interface : action_space 41 → 41+K (recommandé K=6, aligné sur les 6 slots figurines ;
actions dédiées plutôt que surcharge des slots tir 19-23, pour la lisibilité du masque) ;
obs_size change → nouveau modèle from scratch (`--new`, déjà acté). Mettre à jour la
`justification` de la config en même temps.

⚠️ **À faire dans cette tranche : remplacer `action_net` par `Linear(320, 18)`.** L'action space
change de toute façon (`TOTAL_ACTION_SIZE` recalculé) ; c'est le bon moment pour supprimer les
~334 k paramètres inertes de `pointer_policy.py`. Aujourd'hui `action_net` est un `Linear(320,
1062)` dont seules 18 colonnes sont lues (wait + charge + fight + zone intent) — les 1044
colonnes move/tir sont écrasées par conv 1×1 et pointeur, et ne reçoivent aucun gradient (verrouillé par
test). Remplacer par `Linear(320, 18)` et assembler manuellement dans `_action_logits`. Aucun
autre impact sur l'initialisation orthogonale ni sur SB3 si la couche est reconstruite à l'init.

<a id="s9.3bis"></a>
### 9.3bis P2 — CE QUI A ÉTÉ LIVRÉ (2026-07-28)

**Livré tel que spécifié en §9.3**, plus le pilote P3 point 0, et **mergé sur `main`** le
2026-07-28 (rebasé sur P3-1, dont il reprend l'action space). Ce qui suit décrit le code en
place, vérifié par tests et par mesure in-engine — pas une intention.

**Le mécanisme** (`engine/agent_decision.py`, ~150 lignes). `game_state["pending_agent_decision"]`
porte `{type, player, unit_id, options[]}`, où chaque candidat est
`{label, effect_ids, payload}`. Trois garde-fous, tous des `raise` :
- **plus de `MAX_DECISION_OPTIONS` candidats → erreur**, jamais de top-K silencieux (§9.0bis
  réserve 2) ;
- **une seconde décision ne peut pas écraser la première** — le moteur rend la main après chacune ;
- **un effet hors du vocabulaire d'observation (`UNIT_RULE_EFFECT_IDS`) → erreur**, plutôt qu'un
  candidat décrit par un vecteur nul que l'agent ne pourrait pas distinguer.

**L'action space** : `CHOICE_BASE = 1082`, `CHOICE_COUNT = 6`, `TOTAL_ACTION_SIZE = 1088`
(`engine/macro_intents.py`). Quand une décision est en attente, le masque n'expose **que** les
`CHOICE_i` correspondant aux candidats réels, et le pool d'unités éligibles est vide : le moteur
est arrêté sur le point de choix, exactement comme le PvP l'est sur un `waiting_for_player`.

**L'observation** : `decision_ctx_bin` (2) + `decision_options_bin` (6 × 14) →
`obs_size` **20654 → 20740** (20654 = valeur après P3-1). Un candidat est décrit par **l'effet qu'il accorde**, dans le même
vocabulaire que les drapeaux `rule_*` d'unité — pas par son index, qui ne veut rien dire d'un
prompt à l'autre. Le bloc reste nul quand la décision appartient à l'autre camp. Détail complet →
[`AI_OBSERVATION.md`](../AI_OBSERVATION.md), section `decision_ctx_bin`.

**La tête d'action** : les logits `CHOICE_i` sortent d'un **pointeur** (`q_choice · c_i / √d`) sur
des embeddings produits par un encodeur PARTAGÉ entre tous les slots de candidats — même
raisonnement que le pointeur de tir (T-E) : le nombre de candidats est gratuit en paramètres, et
une ligne de poids par slot n'aurait rien à généraliser.

**`action_net` est passé de `Linear(320, 1082)` à `Linear(320, 18)`**, comme §9.3 le demandait.
Mesuré sur la config réelle (`x5_debug`, `net_arch [320,320]`, `cnn_features 256`), branche P3-1
comme base : la policy passe de **2 160 828** à **1 928 148** paramètres, soit **−232 680** —
l'économie des ~341 k colonnes inertes moins le coût du bloc de décision. Un test vérifie que **chacune** des 18 colonnes
restantes déplace le logit qu'elle est censée produire, et lui seul.

**Le pilote (P3 point 0)** : en gym, un prompt de rule choice n'est plus tranché par le moteur. Il
est exposé, l'agent le joue, le moteur applique le candidat désigné. Le choix du camp **bot** est
joué par le bot (tirage propre) — auparavant, c'était l'action de l'AGENT qui décidait à la place
de son adversaire. Hors gym (PvP humain, PvE `pve_controller`), le flux est **inchangé**.

**Vérifications.** 25 tests dédiés
(`tests/unit/engine/test_agent_decision_mechanism.py`) + tête d'action
(`tests/unit/ai/test_pointer_head.py`, 3 tests neufs dont l'alignement `CHOICE_i` ↔ candidat `i`) +
wrapper (`tests/unit/ai/test_env_wrappers.py`, 2 tests). **Mesure in-engine** (le seul verdict qui
compte, [§0bis](V11_agent_rework.md#s0bis)) : sur le scénario Tyranid Warrior mêlée — le SEUL roster du jeu portant un rule
choice — **28 décisions exposées et jouées via `CHOICE_i`** sur 2 épisodes, tous terminés, aucun
masque vide ; sur le scénario d'entraînement réel (SM/Orks), 3 épisodes terminés, **0 décision**,
flux nominal intact. Un `MaskablePPO` complet (policy + extracteur + config d'agent réelle)
apprend sur l'env réel (`learn(128)`, gradients finis sur la requête de décision).

⚠️ **Effet de bord trouvé PAR CETTE MESURE, et corrigé** : le flush T6-c re-journalisait chaque
`rule_choice` déjà écrit en direct dans step.log, et cette seconde écriture échouait **en silence**
(clé `selectedRuleName` vs `selected_rule_name` — 16 erreurs avalées pour 16 choix). Le défaut
était latent tant que les choix étaient appliqués hors de la fenêtre de flush ; les faire passer
par un step le rendait systématique. `rule_choice` est sorti de `_STEP_LOG_TYPE_MAP` (corriger le
mapping aurait produit un doublon de chaque ligne), et un test verrouille « une décision = une
ligne ».

🔎 **CONTRE-AUDIT du 2026-07-28 (après merge) — 3 défauts trouvés dans la livraison, tous
corrigés.** Aucun n'avait été vu par les tests de la tranche : ils tenaient à des chemins que le
mécanisme ne traversait pas avant P2.

1. 🔴 **Le mécanisme devenait INERTE après le premier épisode.** `_choice_timing_fired_events`
   indexe `(trigger, tour, phase, joueur, unité, règle)` — **sans le numéro d'épisode** — et
   `reset()` ne le purgeait pas. L'événement du tour 1 de l'épisode 1 faisait donc passer pour
   « déjà tiré » celui du tour 1 de l'épisode 2. **Mesuré sur 3 épisodes enchaînés dans le même
   moteur : 16 décisions, puis 2, puis 0.** Le défaut préexistait (le choix cessait simplement
   d'être proposé), mais il rendait P2 sans objet dès le 2ᵉ épisode d'un run. `reset()` purge
   désormais les 4 clés (`_choice_timing_fired_events`, la file, le prompt actif, la décision
   pendante) ; verrouillé par test avec sa mutation.
   ➜ **Leçon de méthode** : *un smoke à UN épisode ne peut pas voir un état qui fuit ENTRE
   épisodes.* Le smoke initial (2 épisodes, 2 moteurs distincts) montrait 28 décisions et
   validait un mécanisme qui, en run réel, se serait éteint après le premier épisode.
2. 🟠 **Le reward d'une décision était neutre par ACCIDENT.** Le payload `agent_decision` tombait
   dans le chemin « réponse système » **uniquement** parce qu'il contient la clé
   `waiting_for_player` ; retirer cette clé l'aurait basculé dans le chemin « unité agissante »
   (reward d'unité arbitraire, ou `ValueError`). C'est désormais une branche EXPLICITE de
   `RewardCalculator`, à **0.0 en dur** — et non `system_penalties['system_response']`, dont un
   futur tuning aurait rendu les décisions coûteuses sans que personne ne le décide. Deux tests,
   dont un qui retire la clé `waiting_for_player` pour prouver que la neutralité ne tient plus à
   elle.
3. 🟠 **step.log : `Steps=` divergeait de `Total=`.** Une décision consomme un `step()` gym
   complet, mais sa ligne de journal était écrite avec `step_increment=False` : le compteur du
   StepLogger sous-comptait d'exactement le nombre de décisions, et l'écart aurait ressemblé au
   symptôme de T6-c. Le drapeau `consumes_gym_step` distingue désormais le chemin gym (True) des
   chemins PvP/PvE (False, aucun step gym consommé). Deux tests.

Un quatrième trou, du même motif que celui déjà fermé côté bot, a été refermé par symétrie :
`SelfPlayWrapper._get_frozen_model_action` renvoyait `ACTION_WAIT` quand le pool est vide — action
**hors masque** pendant une décision. La branche avec `frozen_model`, elle, passe par
`predict(action_masks=…)` et jouait déjà un `CHOICE_i` correct.

⚠️ **Écart CONNU, hors périmètre P2, à traiter comme un sujet à part** : en **PvE**, un choix de
règle n'emprunte PAS ce mécanisme. `pve_controller.select_rule_choice_with_policy` simule chaque
option et la score avec la **tête de valeur** — une politique différente de celle que
l'entraînement façonne désormais (la tête pointeur de candidats). Le PvE joue donc autre chose que
ce que l'agent a appris, ce que l'en-tête de `make_ai_decision` réprouve explicitement pour les
autres actions. Le rendre cohérent implique de faire remonter un état d'attente jusqu'à
`services/api_server`, dont le flux n'a pas été validé en runtime dans cette session : c'est un
chantier PvE, pas la moitié manquante de P2 (dont la spec §9.3 borne le périmètre au gym).

⚠️ **Ce qui n'est PAS mesuré, et ne peut pas l'être aujourd'hui.** §9.6 exige un win-rate ≥ tranche
précédente. Il est **indisponible** : (1) `TOTAL_ACTION_SIZE` et `obs_size` changent tous les deux
(comme pour P3-1), donc tout modèle existant est incompatible et la comparaison exige un retrain
`--new` complet ;
(2) **aucun roster d'entraînement (SM/Orks) ne porte de rule choice** — sur ces scénarios, le
mécanisme ne se déclenche jamais, et son effet sur le win-rate est **structurellement nul**. Ce
qu'il apporte est l'**infrastructure** des tranches P3 1→8, qui elles auront un effet mesurable.
Ne pas lire l'absence de mesure comme une mesure neutre.

**Reste ouvert** : P3 points 1→8 (une tranche = une décision, cf. §9.4), P4 (features de support
propres à chaque décision branchée), P5 (le cycle de validation, dès qu'une tranche P3 touche un
roster d'entraînement).

<a id="s9.4"></a>
### 9.4 P3 — Branchement décision par décision (une tranche = une décision + validation)

⚠️ Les sites à remplacer sont ceux du PIPELINE VIF gym (vérifiés par contre-review), pas les
heuristiques `_ai_select_*` qui ne sont que des fallbacks/chemins legacy.

Ordre par valeur tactique :
0. **Prompts rule-choice** — ✅ **LIVRÉ le 2026-07-28** (pilote du mécanisme P2 générique, cf.
   [§9.3bis](#s9.3bis) et [§0.42](V11_agent_rework.md#s0.42)). `raw_action_int % len(options)`
   n'existe plus, ni la clé `_last_raw_action_int` qui l'alimentait : le prompt est poussé comme
   `pending_agent_decision`, l'agent le voit dans son observation et le joue par `CHOICE_i` ; le
   choix du camp bot est joué par le bot.
   🔴 **Son étiquette « le plus urgent » était PÉRIMÉE ([§0.41](V11_agent_rework.md#s0.41)) et le reste : ce point est INERTE
   dans le training.** Une seule unité du projet porte un rule-choice (`TyranidWarriorMelee`,
   déclaré dans les rosters **TS**, pas dans `config/unit_rules.json`), et aucun roster
   d'entraînement ArmageddonAgent n'est tyranide. La correction est **structurelle** (le PvE, le
   `rule_checker` et tout futur roster tyranide en bénéficient) ; son effet sur le win-rate est
   **nul par construction**. Ce que P2 apporte vraiment est le mécanisme réutilisable par les
   décisions **non-entité** des tranches suivantes.
1. ✅ **LIVRÉ le 2026-07-28 (mergé sur `main` le soir même) — détail → [§0.41](V11_agent_rework.md#s0.41).** La cible de
   mêlée est désormais une **dimension d'action** (`FIGHT_SLOT` 1046-1065, un par slot ennemi,
   + `ACTION_FIGHT_NO_TARGET` 1066 pour le combat à vide 12.04/12.06), scorée par une **tête
   pointeur** sur les embeddings d'ennemis — pas par des `CHOICE_k` denses. Le masque n'ouvre un
   slot que si sa cible est dans le pool 12.05, et le commit refuse tout slot hors pool.
   `_ai_select_fight_target` reste vive pour le **PvP** uniquement. **Win-rate et regret NON
   mesurés** (l'action space change ⇒ retrain `--new`). Historique du site ci-dessous, conservé :
   **Cible de mêlée** — ⚠️ **MIS À JOUR le 2026-07-16 (le fix du bug `squad_fight` a déplacé ce
   site)** : la boucle `get_best_enemy_score_for_unit` de `squad_fight` **n'existe plus** — elle
   sélectionnait sa cible dans le mapping de slots gelé du tir, sans filtre de zone d'engagement
   (violation 12.05) et crashait quand ce mapping était vide (cf.
   `Implémenté/bug_squad_fight_mask_mismatch.md`). Le site vif est **désormais
   `_ai_select_fight_target`** (fight_handlers ~L1725), que `squad_fight` consomme via
   `_fight_build_valid_target_pool` — en miroir du flux PvP (`_fight_v11_resolve_attacks`).
   Ce n'est donc plus un « fallback » : c'est le sélecteur vif, partagé gym/PvP.
   ⚠️ Il porte un `except Exception: … return valid_targets[0]` (~L1781) qui masque toute erreur
   de config/registry — vérifié : jamais déclenché sur la suite + smoke. Retrait = backend
   partagé, arbitrage requis (cf. `A_faire/bug_pile_in_bfs_clearance_mismatch.md` §dernier).
   La boucle `get_best_enemy_score_for_unit` reste vive pour la **cible de charge** (point 2).
   ~~Pilote du mécanisme P2.~~ → il a été le pilote, et il a **tranché la méthode** : slots +
   pointeur, pas `CHOICE_k` ([§0.41](V11_agent_rework.md#s0.41)). Le point 2 (cible de charge) suit le même patron.
2. ✅ **LIVRÉ le 2026-07-28 (nuit) — détail → [§9.4bis](#s9.4bis) et [§0.43](V11_agent_rework.md#s0.43).**
   La cible de charge est désormais une **dimension d'action** (`CHARGE_SLOT` 1045-1064, un par
   slot ennemi), scorée par une **tête pointeur** sur les embeddings d'ennemis — même patron que
   P3-1, pas des `CHOICE_k`. Le masque n'ouvre un slot que si sa cible est déclarable (11.02) et
   le commit refuse tout slot non déclarable. ⚠️ **Sur la branche `v11-p3-2-charge-target`,
   PAS sur `main`.** Historique du site, conservé : le site vif était la boucle de scoring
   `get_best_enemy_score_for_unit` dans `convert_squad_action` du décodeur (action_decoder
   ~L1000-1030), PAS `charge_handlers:1506` (chemin `convert_gym_action`, hors gym mais encore
   vif en PvE via pve_controller — non touché, comme prévu).
3. **Choix de l'unité à activer** par phase — `eligible_units[0]` a 9 occurrences dans
   action_decoder ; les sites DÉCISIFS du flux vif sont dans `convert_squad_action`
   (~L837, L876), les autres sont dans la construction du masque ; le plus gros gain
   stratégique. Contrainte règles : l'ordre en fight reste borné par Fights First
   (11.04/12.04) et les pools alternés — le choix agent se fait DANS le pool légal courant.
4. **Allocation des pertes défenseur** — remplace `_select_allocation_model`
   (shared_utils ~5643) ; candidats = figurines éligibles 05.03/06.02 ; inclut l'allocation
   hazard ET l'ordre de déclaration des groupes (`declare_order`, décision défenseur 05.03,
   aujourd'hui `_auto_declared_order`).
5. **Pile-in / consolidation** — les sites vifs sont `fight_pile_in_plan`
   (shared_utils ~6708) et `squad_consolidate_plan` (~7038) appelés par `squad_fight`,
   PAS les `_ai_select_*` de fight_handlers ; candidats = top-K destinations du pool.
   NB règles : pile-in/conso sont OPTIONNELS et la consolidation a 3 modes en cascade (dont
   vers objectif) — l'espace de choix doit inclure « ne pas bouger ». ⚠️ Le site vif gym
   `squad_consolidate_plan` n'implémente que le mode (1) (docstring : option (2) « vers
   objectif » déférée) — le flux PvP (fight_handlers ~1161-1176) a la cascade complète :
   écart gym/PvP à combler quand cette tranche s'ouvre.
6. **Move-after-shooting** (destination — remplace
   `_select_move_after_shooting_destination_for_ai`, shooting_handlers ~4961) et
   **reactive_move** (accepter/décliner + destination — protocole `decline_reactive_move`
   déjà formalisé, shared_utils ~2190).
7. **FLY / Take to the skies** — déclaration binaire (aujourd'hui auto pour l'IA,
   movement_handlers ~261/271).
8. **Optionnels, à statuer utilisateur** : split-fire (en gym, l'escouade entière vise UN
   slot ; le PvP a `squad_shoot_assign` par-figurine), choix d'arme — deux régimes distincts
   en gym : RNG = `selectedRngWeaponIndex` pris tel quel (shared_utils ~4489), CC =
   auto-sélection par expected damage `_auto_select_cc_weapon_for_fig` (shared_utils ~6938,
   appel ~7016) — les deux sont des décisions joueur auto-résolues,
   déclaration multi-cibles de charge (PvP oui, gym mono-cible), placement final de charge
   (`charge_build_valid_plan`, shared_utils ~3955), déploiement (les actions 4-8 sont 5
   STRATÉGIES scorées, action_decoder ~1682-1698, pas « les 5 premiers hex » — élargir ou non).

Hors scope A' (reste auto, conforme règles car « un placement légal parmi d'autres ») :
placement par-figurine du move rigide, pivot. Montée d'étage = Phase C.

<a id="s9.4bis"></a>
### 9.4bis P3 point 2 — CE QUI A ÉTÉ LIVRÉ (2026-07-28, branche `v11-p3-2-charge-target`)

**Ce qui était en place.** `charge` était une action **nue** (un seul id, 1045). Le masque disait
« une charge est possible » ; c'est le **décodeur** qui choisissait la cible, en scorant chaque
ennemi déclarable par `get_best_enemy_score_for_unit` (damage_ratio). L'agent déclarait donc une
charge **sans jamais dire qui** — alors que 11.02 (« Declare Charge ») et 11.04 (« BEFORE MOVING:
select one or more enemy units ») font de la sélection de la cible un choix de **joueur**, lu dans
le PDF `11 Charge phase.pdf` avant écriture.

**Ce qui est livré.** Même patron que P3-1, à l'identique — les candidats sont des **entités déjà
observées**, donc slots + pointeur, jamais `CHOICE_k` :

| | Avant | Après |
|---|---|---|
| Action de charge | `ACTION_CHARGE` = 1045 (sans cible) | `CHARGE_SLOT` **1045-1064** (20) |
| `TOTAL_ACTION_SIZE` | 1088 | **1107** |
| `obs_size` | 20740 | **20768** (`charge_reachable_max_roll`) |
| Choix de la cible | décodeur (`damage_ratio`) | **agent** |

- `CHARGE_SLOT_COUNT` est **dérivé** de `SHOOT_SLOT_COUNT`, comme celui de la mêlée : un slot =
  une ligne du tenseur ennemi (invariant D1). Verrouillé par `test_action_space_mirror.py`.
- **Aucune action « charge sans cible »**, contrairement au combat : 12.04/12.06 rendent une
  escouade éligible sans cible (combat à vide), mais 11.02 conditionne la **déclaration** à la
  présence d'un ennemi à 12". Sans cible, aucun slot n'est ouvert et seul WAIT reste — la charge
  restant **optionnelle**, WAIT est ouvert dans tous les cas.
- **Parité masque/commit dans les DEUX sens** : le masque n'ouvre un slot que si
  `charge_check_eligibility` est vraie pour cette cible, et le commit refuse tout slot non
  déclarable ET tout slot vide. Aucun repli sur l'heuristique.
- ⚠️ **Le gym reste MONO-CIBLE**, et cette tranche ne le change pas. 11.04 dit « select one **or
  more** enemy units » ; le PvP le fait (`targetIds`, `charge_handlers`), une action de charge du
  gym ne désigne qu'**un** slot. Ce n'est pas une régression (c'était déjà le cas quand le
  décodeur tranchait) mais, la cible étant devenue une dimension d'action, il faut le dire : la
  déclaration multi-cibles reste au point 8 de [§9.4](#s9.4), « à statuer utilisateur ».
- Pas de garde de troncature ici (la mêlée en a une) : la mêlée confronte **deux** sources (pool
  12.05 et mapping de slots), donc une cible légale peut n'avoir aucun slot. Ici la seule source
  des candidats **est** le mapping — une escouade ennemie sans slot est déjà loguée en amont par
  `_refresh_enemy_slot_mapping`, une seule fois.

**Tête pointeur : une troisième requête, des embeddings PARTAGÉS.** `charge_query_net` est une
`Linear(latent, entity_dim)` de plus, appliquée aux **mêmes** embeddings que le tir et la mêlée.
La dupliquer coûte `entity_dim × latent_dim` paramètres et rien d'autre ; la partager forcerait un
ordre de préférence unique alors que « qui tirer » (portée, LoS, couvert), « qui charger »
(distance à franchir au 2D6, ce que l'engagement me coûte au tour adverse) et « qui frapper »
(valeur de la cible, riposte) sont trois questions différentes. `action_net` passe de
`Linear(320, 18)` à `Linear(320, 17)` — la colonne dense « charge » disparaît.

**P4 (observation de support) — `charge_reachable_max_roll`, sans quoi la tranche était incomplète.**
Un bit par entité **ennemie** : 1 ssi un plan de charge **légal** existe vers cette cible au jet
**maximal** (11.02 étape 2, 2D6 → 12). Une charge ratée coûte l'**activation entière** de l'unité
(11.02 étape 3). Aucun champ existant ne le disait — et ce n'est pas supposé, c'est verrouillé par
une contre-épreuve : `edge_distance` mesure à vol d'oiseau et rend la **même valeur** pour une
cible atteignable et pour la même cible cernée de murs
(`test_zero_when_the_target_has_no_legal_landing_hex`). Les trois causes d'échec structurel
qu'elle ignore : aucune case libre au contact, ER d'une escouade **non** ciblée (11.04 AFTER
MOVING), et la pénalité de descente 13.06, retranchée du jet et exposée nulle part ailleurs.
- **Oracle unique** : `charge_build_valid_plan`, la fonction que le **commit** exécute. Une
  réimplémentation annoncerait une atteignabilité que la résolution ne produirait pas.
- **UNE seule garde, celle de la PHASE** (`phase_charge`, qui est aussi le masque du bit).
  ⚠️ **Une seconde garde, sur l'éligibilité 11.02 de la cible, a été écrite puis RETIRÉE au
  contre-audit** : `charge_build_valid_plan` commence lui-même par `charge_check_eligibility`.
  Le pré-test était donc **double** pour une cible déclarable et **sans gain** pour une cible
  hors portée, qui court-circuite de toute façon. Constaté par **comptage d'appels** (déterministe,
  contrairement au chrono) : **4 appels d'éligibilité pour 2 cibles → 2**. Le gain de temps est
  réel mais petit (~42 µs par cible déclarable, soit 2,9 % de l'observation de charge sur cette
  fixture — du même ordre que la variance de mesure) ; ce qui justifie le retrait est **l'absence
  de tout cas où le pré-test gagne**, pas le chrono.
- **Coût mesuré** (scénario mêlée, 2 cibles déclarables, minimum sur 9 séries de 40 constructions) :
  observation **1,2 ms hors charge → 2,2 ms en phase de charge**, soit **+1,0 ms**, et
  **inchangée aux 5 autres phases**. C'est le poste le plus cher de l'observation quand il
  s'exécute ; il n'a pas été mémoïsé faute de gain démontrable (une escouade ne construit son
  observation qu'une fois par step) et parce qu'un cache d'invalidation est précisément le motif
  qui a produit [§0.26](V11_agent_rework.md#s0.26).
- La parité obs↔masque est une **implication**, pas une équivalence, et c'est voulu : le masque
  suit 11.02 (déclaration possible), le bit suit 11.04 (la charge peut aboutir). Une cible
  déclarable mais inatteignable garde son slot ouvert — l'agent a le droit de tenter, il sait
  seulement que c'est perdu d'avance.

**Reward shaping du choix de cible — STATUÉ (exigence de [§9.6](#s9.6), jamais honorée jusqu'ici).**
§9.6 impose que les heuristiques du `RewardMapper` réutilisées comme shaping des nouvelles
décisions soient tranchées « par tranche, **jamais en silence** ». Ni P3-1 ni P3-2 ne l'avaient
fait ; c'est réparé ici, **par lecture de la config, pas par intention** :
- `RewardCalculator` note une charge réussie par `get_charge_priority_reward(unit, target,
  all_targets, …)` — une fonction qui **récompense la cible** selon l'heuristique « plus haute
  menace / plus bas PV » (`ai/reward_mapper.py`). Elle notait le choix du DÉCODEUR ; depuis cette
  tranche, elle noterait celui de l'AGENT, ce qui l'orienterait vers l'heuristique qu'on vient
  justement de lui retirer.
- **Constat, vérifié dans `ArmageddonAgent_rewards_config.json`** : `charge_priority_1/2/3` valent
  **0.0**, comme `shoot_priority_1/2/3` et `attack_priority_1/2`. La fonction rend donc exactement
  `base_actions.charge_success` (**0.05**), **indépendamment de la cible**. Le shaping directif est
  **INERTE** — le seul agent entraîné ne le subit pas.
- **Décision : ne rien changer.** Retirer l'appel supprimerait un point d'extension pour un gain
  nul, et remettre des poids non nuls guiderait l'agent vers l'heuristique — cet arbitrage
  appartient à l'utilisateur, qui possède la config de rewards. 🔴 **Conséquence à retenir si un
  jour ces poids repassent au-dessus de 0 : le choix de cible de l'agent serait de nouveau tiré
  vers `damage_ratio`, et le win-rate de la tranche mesurerait le shaping, pas la décision.**
- Le même constat vaut pour la mêlée (`get_combat_priority_reward`) et le tir
  (`get_shooting_priority_reward`) : mêmes poids à 0.0, même conclusion.

**Bots d'évaluation — changement de comportement ASSUMÉ.** `_first_charge_action_in` prend le
premier slot ouvert, donc la cible **la plus menaçante** (les slots sont attribués par menace
décroissante) : la même heuristique qu'ils appliquent déjà au tir et à la mêlée. Ils ne passent
donc plus par le `damage_ratio` du décodeur. ⚠️ **Les win-rates mesurés avant cette tranche ne
sont pas comparables à ceux d'après** — la baseline adverse a changé, comme pour P3-1.

**Ce qui reste vif de l'ancien chemin** : `charge_handlers` et le flux **PvP/PvE**, non touchés.
`get_best_enemy_score_for_unit` reste utilisée par les intents de zone (`get_best_enemy_global`,
`get_best_enemy_score`) ; ses deux imports devenus morts (`action_decoder`, `w40k_core`) ont été
supprimés.

**Preuves (tests ciblés, verts — aucune suite complète lancée, c'est l'utilisateur qui la lance).**

| Fichier | Résultat |
|---|---|
| `tests/unit/engine/test_squad_charge_target_parity.py` (**neuf**) | **9 verts** : parité masque/commit sur 3 seeds en marche aléatoire, slots ouverts == cibles déclarables (avec la contre-épreuve « cible éloignée → son slot se ferme »), cible commitée = celle du slot joué (le **dernier** déclarable, pas le premier), refus d'un slot non déclarable, refus d'un slot vide, alignement décodeur `id → slot`, absence de « charge à vide ». |
| `tests/unit/engine/test_squad_obs_charge_target_support.py` (**neuf**) | **7 verts** — verrou de `charge_reachable_max_roll` : cible atteignable, 0 hors phase de charge, 0 au-delà de 12", **0 sur une cible cernée de murs à `edge_distance` identique**, accord avec l'oracle moteur, 0 sur les alliées, implication obs → masque. |
| `tests/unit/ai/test_pointer_head.py` | **20 verts**, dont **3 neufs** (logits de charge issus du pointeur, requête distincte de celles du tir et de la mêlée, coût nul par slot). `test_pointer_logit_is_slot_local` constate maintenant que perturber l'embedding du slot 1 déplace **trois** logits — c'est le partage recherché. |
| `test_action_space_mirror.py` / `test_evaluation_bots.py` | **12** / **17 verts** (miroir étendu aux slots de charge, pavage `[0, SIZE)` re-vérifié). |
| batteries charge (`charge_execution`, `charge_resolution`, `charge_eligibility`, `squad_charge_descent_level`, `charge_oval_base_reverse_bfs`) | **46 verts** |
| batteries boucle moteur (`execute_semantic_action`, `phase_transitions`, `engine_step`, `engine_full_loop`, `t5_bare_loop`, `cross_phase_cascade`) | **71 verts** |
| batterie observation (`structure_doc`, `vector_split`, `enemy_block`, `enemy_cover`, `model_engagement`, `enemy_slot_alignment`, `observation_builder`, `entity_obs_equivalence`, `entity_encoder_extractor`, `fight_target_support`) | **67 verts** |

**Mutation-tests menés** (un test qui passe du premier coup peut passer pour la mauvaise raison) :
masque sans filtre d'éligibilité → 3 tests rouges ; commit sans garde d'éligibilité → 1 rouge ;
décodeur décalé d'un slot → 3 rouges.

**Mesure in-engine** (le seul verdict qui compte, [§0bis](V11_agent_rework.md#s0bis)) : **3 épisodes
ENCHAÎNÉS dans le MÊME moteur** (leçon [§0.42](V11_agent_rework.md#s0.42) — un smoke à un épisode ne voit pas une fuite
d'état), sur le scénario mêlée et sur le scénario d'entraînement réel. Slots de charge exposés et
joués, **plusieurs slots distincts** exercés, tous les épisodes terminés, **aucun masque vide**.
Contre-épreuve explicite de fuite d'état : comptage identique en moteur **neuf** et en moteur
**réutilisé** pour chacun des 3 épisodes.

**🔴 CE QUI N'EST PAS MESURÉ, et ne peut pas l'être avant le prochain retrain.**
1. Le **win-rate** exigé par [§9.6](#s9.6). `TOTAL_ACTION_SIZE` **et** `obs_size` changent ⇒ tout
   modèle existant est incompatible ⇒ `--new` obligatoire.
2. Le **regret** de la décision ([§9.0bis](#s9.0bis) réserve 1) : non mesuré, comme pour P3-1. La
   décision de brancher repose sur le raisonnement — « la cible la plus rentable au damage_ratio »
   ignore la probabilité de réussir la charge, ce que l'agent peut désormais arbitrer — pas sur une
   mesure. **À confronter au premier run** : si le win-rate baisse, c'est la première hypothèse.

<a id="s9.5"></a>
### 9.5 P4 — Observation de support

Bloc décision (P2) + features nécessaires aux choix : LoS/couvert par slot ennemi, portée
effective de l'arme active vs distance du slot, flags advanced/fell_back de l'unité active.
Les niveaux/élévation restent en Phase B (scénarios plats jusque-là).

<a id="s9.6"></a>
### 9.6 P5 — Validation par tranche

> ⚠️ **MAJ 2026-07-28 : ne PAS utiliser `x1_debug` pour le run court.** Ce profil porte
> `n_envs: 48` (vérifié dans la config) → `MemoryError` à l'allocation du rollout buffer
> ([§0.33](V11_agent_rework.md#s0.33) : 46,9 Go demandés pour 29 Go disponibles). Utiliser
> **`x5_debug`** (8 envs) tant que [§0.33](V11_agent_rework.md#s0.33) n'est pas rouvert. La phrase ci-dessous date d'avant
> cette mesure.

Chaque tranche P3 : suite de tests verte + smoke 10 épisodes + run court `x1_debug` +
win-rate vs GreedyBot ≥ tranche précédente. Si l'ajout d'un point de décision DÉGRADE le
win-rate, la décision est mal observée ou mal récompensée → corriger avant d'empiler la
suivante. Interdits : masquer une régression en retirant silencieusement la décision.

Points de vigilance :
- l'ordre des candidats doit être déterministe et stable (sinon l'assignation de crédit PPO
  est brouillée) ;
- chaque décision ajoutée allonge l'épisode en steps → surveiller `episode_steps` vs la
  normalisation `/100` de l'observation globale ;
- les heuristiques du RewardMapper utilisées par les anciens `_ai_select_*`
  (`get_shooting_priority_reward`) peuvent devenir du reward shaping pour guider les
  nouvelles décisions — à statuer par tranche, jamais en silence. NB : un de ses deux
  consommateurs, `_ai_select_shooting_target` (shooting_handlers, def ~2093), est DÉJÀ mort
  (zéro appelant) — à inclure dans la suppression P1.
