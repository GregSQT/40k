#!/usr/bin/env python3
"""Schéma UNIFIÉ d'entité pour l'observation squad (V11 §0.30 — tranche T-D).

L'observation n'est plus un vecteur PLAT où chaque slot ennemi possède ses propres poids de
première couche (`V11_entity_encoder_pointer.md` §1.8 : 640 paramètres par dimension). Elle est
un jeu de **tenseurs d'entités** : chaque unité — la mienne, mes alliées, les ennemies — est
décrite par le **MÊME** schéma de features, encodée par le **MÊME** réseau, et le réseau
généralise donc d'un slot à l'autre (§3.3).

Ce module est la SOURCE UNIQUE du schéma :
- `UNIT_CONT_FIELDS` / `UNIT_BIN_FIELDS` : l'ordre des features d'une unité ;
- `MODEL_TYPE_*` : le sous-registre « types de figurines » d'une unité ;
- `SELF_MODEL_*` : le sous-registre « mes figurines » (positions et engagement individuels) ;
- les profils d'armes viennent de `observation_weapon_profiles` (déjà partagé §9.2.5).

Le code de lecture (tests, outillage) passe par `unit_cont_index("nom")` plutôt que par des
index recopiés : c'est ce qui a permis aux tests d'observation de survivre à §9.2.5 sans
modification, et l'équivalent doit exister pour le format entité (§4 T-D).

⚠️ **Features propres à l'unité ACTIVE** (§3.3 : « les features propres à un camp sont à zéro
pour l'autre, avec leur masque ») : les compteurs d'engagement et les drapeaux de terrain ne
sont émis que pour l'unité observée ; leur masque est le bit `is_active`. Les remplir pour les
25 autres entités exigerait un test d'empreinte par figurine et par entité à chaque step — le
poste dominant du coût d'observation (§1.8) — pour une information que la grille égocentrique
porte déjà en partie.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional, Tuple

#: Clé du cache des sous-tenseurs d'armes dans le `game_state`
#: (posée par `ObservationBuilder._encode_entity_weapons`, vidée par `build_units_cache`).
#: Elle vit ici — module feuille, sans dépendance — pour que les deux côtés lisent la MÊME
#: constante : en deux littéraux, une renommée d'un seul côté laisserait un cache jamais
#: invalidé, donc des armes du roster précédent observées après une rotation.
WEAPON_PROFILE_CACHE_KEY = "_obs_weapon_profiles_cache"

# ---------------------------------------------------------------------------
# Unité (ami ou ennemi — MÊME schéma, cf. §3.3)
# ---------------------------------------------------------------------------

#: Features CONTINUES d'une unité, dans l'ordre d'émission.
UNIT_CONT_FIELDS: Tuple[str, ...] = (
    "alive_models",        # effectif vivant
    "hp_total",            # PV cumulés vivants
    "value_alive",         # VALUE cumulée vivante (somme par figurine)
    "oc_total",            # OC cumulé
    "model_count_ratio",   # effectif vivant / effectif de départ
    "wounded_hp_ratio",    # PV de la figurine entamée / son HP_MAX (1.0 si aucune)
    "col_rel",             # figurine la plus proche du centroïde OBSERVATEUR (subhex bruts)
    "row_rel",
    "edge_distance",       # distance bord-à-bord escouade↔escouade depuis l'unité active
    "move",                # profil de datasheet
    "hp_max",
    "toughness",
    "armor_save",
    "invul_save",
    "moved_max",           # distance géodésique parcourue ce tour : max sur l'escouade
    "moved_sum",           # … et somme
    "n_fight_eligible",    # ⚠ unité ACTIVE uniquement (masque = is_active)
    "n_in_enemy_ez",       # ⚠ unité ACTIVE uniquement
    # ⚠ Entités ENNEMIES uniquement (comme `los_can_see` / `cover_vs_observer`) : c'est une
    # grandeur de PAIRE (mon escouade → cette cible), pas une propriété de la cible.
    #
    # Combien de MES figurines vivantes sont engagées avec cette escouade (04.02), donc
    # combien peuvent réellement porter des attaques contre elle. V11 §9 P3-1 a fait de la
    # cible de mêlée une décision de l'agent ; sans ce champ, la tête pointeur choisirait
    # une cible sans savoir avec quelle FORCE elle serait frappée — or c'est le premier
    # facteur du choix : engagée par 8 figurines ou par 1, la même cible ne vaut pas la même
    # chose. `n_fight_eligible` ne le dit pas : il agrège sur toutes les cibles à la fois.
    # `edge_distance` non plus : la distance à l'escouade ne dit rien du nombre de figurines
    # qui atteignent l'ennemi (05.03/04.02 s'évaluent par figurine, pas par ancre).
    "n_models_engaging",
    # ⚠ Entité ENNEMIE uniquement (même masque que `n_models_engaging`).
    # Portée MAXIMALE (en subhexes) des armes de tir de l'unité OBSERVATRICE. C'est une
    # grandeur de PAIRE : elle dit, pour chaque ennemi, si l'observatrice peut l'atteindre
    # avec ses armes actuelles (comparaison directe avec `edge_distance`).
    # Source : max(RNG × inches_to_subhex) sur les armes de tir de l'unité active.
    # 0 pour une unité corps-à-corps uniquement.
    "effective_range",
    # VERTICALITÉ (13.06) — émis pour TOUTE entité posée, alliée comme ennemie, et c'est ce qui
    # les distingue des drapeaux de terrain voisins : la hauteur d'une figurine est LUE dans
    # `units_cache["floor_height_by_model"]`, déjà calculée par le moteur pour Plunging Fire, et
    # ne coûte donc aucun test d'empreinte par entité.
    #
    # Hauteur (en pouces) de la figurine la PLUS HAUTE de l'unité, normalisée par le seuil de
    # Plunging Fire (22.05) : 1.0 = exactement à la hauteur qui déclenche la règle. Ce n'est pas
    # une échelle arbitraire — c'est le seul seuil que la hauteur franchit dans les règles, et le
    # normaliser par lui rend la feature directement lisible comme « suis-je / est-il en position
    # de tir plongeant ». 0.0 = tout le monde au sol, le cas courant.
    "max_floor_height",
    # Seuil de commandement EN VIGUEUR de l'escouade (01.06) : le Ld le PLUS BAS de ses figurines
    # VIVANTES, donc celui contre lequel 08.03 la fait tester. Source `unit_effective_leadership`
    # (`shared_utils`), l'oracle qu'appelle le jet lui-même : un `min` recopié ici sur les figurines
    # déjà chargées épargnerait une boucle et ferait diverger l'observation du jet le jour où
    # l'extinction 19.04 changerait de règle.
    #
    # Émis pour TOUTE entité PRÉSENTE, réserve comprise (le seuil d'une escouade qui n'est pas
    # encore posée est déjà celui de sa composition) : le seuil de l'ennemi décide de ce que vaut une réduction sous
    # demi-effectif (2D6 < Ld, soit 17 % à Ld 5+ et 58 % à Ld 8+ — les quatre valeurs portées par
    # les rosters joués), celui de mes escouades de ce que je risque à en exposer une.
    #
    # ⚠️ DÉRIVABLE, et non invisible — c'est assumé, contrairement aux champs voisins qui, eux,
    # comblaient un écart d'observation mesuré à 0.0. Mesuré le 2026-09-09 sur TOUS les rosters de
    # `config/agents/` — agent, adversaire et benchmarks, 31 compositions d'escouade distinctes,
    # 26 signatures une fois retirés les agrégats de points/PV/OC : aucune paire ne partage sa
    # signature observée (stats d'unité + multiset des types) avec un Ld effectif différent, et le
    # Ld effectif n'a varié dans AUCUNE des 66 escouades suivies pas à pas sur 6 épisodes gym. Ce
    # champ n'achète donc rien sur ce corpus : il achète que la valeur reste juste sur un roster
    # jamais vu, là où la table « profil → Ld », mémorisable en 26 lignes, se périme à la première
    # faction ajoutée.
    "leadership",
)

#: Règles d'UNITÉ (`config/unit_rules.json`) exposées à l'agent.
#:
#: Ne figurent ici que les règles à EFFET RÉEL — même critère que les règles d'armes, qui
#: excluait délibérément [INDIRECT FIRE] tant qu'elle était inerte ; elle y est entrée le
#: 2026-08-16, quand 10.07 a été implémentée — le critère n'a pas bougé, c'est la règle qui a
#: cessé d'être inerte.
#: Vérifié par lecture le 2026-07-27 : chacune est consultée dans un handler vif.
#:
#: Ce sont les EFFETS, pas les capacités nommées. `unit_has_rule_effect` résout les règles
#: SOURCES vers eux, donc ces entrées couvrent aussi les capacités composites des datasheets —
#: vérifié sur les unités réelles : `cunning_hunters` → shoot_after_advance + shoot_after_flee,
#: `targeted_intercession` → les deux rerolls to-wound, `adaptable_predators` et
#: `target_priority` → charge_after_flee + shoot_after_flee, `aggression_imperative` →
#: reroll_1_tohit_fight, `preservation_imperative` → reroll_1_save_fight. Exposer les sources
#: EN PLUS serait redondant ; n'exposer que les sources manquerait les règles directes.
#:
#: Absents : les marqueurs de RÔLE (`leader`, `sergeant`, `support`, `special_weapon`) — le
#: sous-registre « types de figurines » les porte déjà en one-hot ; et `adrenalised_onslaught`,
#: qui n'est pas une règle mais un CHOIX de joueur (Aggression OU Preservation Imperative, au
#: début de la phase de combat) : sans le mécanisme générique de décision agent (P2), elle ne
#: produit aujourd'hui aucun effet — candidate à une tranche P3, pas à une capacité observée.
#:
#: Elles décrivent l'union EN VIGUEUR (19.04) : une escouade menée par un character porte les
#: règles de son leader et les perd à sa mort. C'était le sens même du trou fermé ici —
#: l'agent subissait ces règles, chez lui comme chez l'ennemi, sans jamais les percevoir : le
#: pipeline squad n'avait aucun champ de règle d'unité, et `unit_has_rule_effect` n'était
#: appelée que par le pipeline mono-figurine legacy (359-d), supprimé depuis.
#:
#: ⚠️ Ce tuple n'ordonne PLUS rien dans l'observation (chantier 01) : les capacités y sont
#: écrites en `obs_id` triés croissant (`UNIT_ABILITY_SLOTS` ci-dessous), pas en bits positionnels.
#: Il reste le VOCABULAIRE — la liste de ce qui est observable — et l'allonger coûte
#: EXACTEMENT ZÉRO scalaire. Ce n'était pas vrai avant le 2026-08-04 : le registre de candidats
#: de décision (`DECISION_OPTION_BIN_FIELDS`) était bâti sur CE tuple, donc chaque entrée y
#: coûtait 6 bits positionnels (un par slot de candidat) — la promesse « une capacité est
#: gratuite » du chantier 01 était fausse d'un facteur 6. Les deux registres sont séparés depuis
#: (cf. `DECISION_GRANTABLE_EFFECT_IDS`).
UNIT_RULE_EFFECT_IDS: Tuple[str, ...] = (
    "charge_after_advance",
    "charge_after_flee",
    "charge_impact",
    "closest_target_penetration",
    # Thievin' Scavengers (chantier 02) : la seule capacité du vocabulaire qui n'agit pas sur un
    # jet mais sur les CP. Observée parce que l'agent doit pouvoir ATTRIBUER le gain à l'unité
    # qui tient l'objectif ; ses CP seuls ne disent pas d'où ils viennent.
    "cp_gain_on_objective",
    # Deep Strike (24.09, chantier 04) : la SEULE capacité du vocabulaire qui ne change ni un
    # jet ni un mouvement, mais l'AIRE DE MISE EN PLACE d'un ingress move (20.04). Deux escouades
    # en réserves sont indiscernables sans elle, alors que l'une arrive dans la bande de 6" au
    # bord et l'autre n'importe où sur le plateau, zone adverse comprise
    # (`movement_handlers.unit_has_deep_strike`, qui bascule le pool). L'agent la subissait sans
    # la percevoir — c'est le trou que la section « Observation » du chantier 04 prescrivait de
    # fermer et qui ne l'avait pas été.
    "deep_strike",
    # Primitive A (chantier 06, passe 1) : les trois MODIFICATEURS de jet portés par une
    # datasheet — +1 touche mêlée (Might Is Right), +1 blessure mêlée (Litany of Hate), +1 au
    # jet de charge (Somethin' to Prove). Ils changent directement l'espérance d'une attaque ou
    # d'une charge, chez moi comme chez l'ennemi : les taire ferait subir à l'agent une escouade
    # qui touche sur 2+ là où sa datasheet dit 3+.
    #
    # ⚠️ `hit_roll_malus_suppressed` N'ENTRE PAS ici, et ce n'est pas un oubli : aucune datasheet
    # ne le porte, il est l'effet du STATUT `suppressed` (`UNIT_STATUS_SLOTS`, registre
    # `config/unit_statuses.json`). Il est donc déjà observable, par l'autre registre.
    "hit_roll_bonus_fight",
    "wound_roll_bonus_fight",
    "charge_roll_bonus",
    "move_after_shooting",
    "reactive_move",
    "reroll_1_save_fight",
    "reroll_1_tohit_fight",
    "reroll_1_towound",
    "feel_no_pain",
    "reroll_charge",
    "reroll_towound_target_on_objective",
    "shoot_after_advance",
    "shoot_after_flee",
    # Primitive F (chantier 06, passe 6) : effets d'état d'unité.
    # `invul_save_override` : confère une InSv à TOUTE l'unité via 19.04 (BannerNob 5+, Librarian 4+).
    # `toughness_bonus_while_waaagh` : +1 T pendant le Waaagh! (BannerNob).
    # `suppress_target_on_shooting` : pose le statut `suppressed` sur la cible après le tir (WarTrakk).
    # `return_destroyed_models` : Grot Orderly — 1×/partie, D3 figurines restituées (PainBoy).
    # `once_per_battle_melee_buff` : Finest Hour — observable ET absent quand dépensé (Captain, passe 2+6).
    "invul_save_override",
    "toughness_bonus_while_waaagh",
    "suppress_target_on_shooting",
    "return_destroyed_models",
    "once_per_battle_melee_buff",
    # Reste du chantier 06 (2026-09-08) : les 14 règles qui portaient un `obs_id` dans
    # `config/unit_rules.json` sans figurer ici. Leur `obs_id` existait donc, mais
    # `unit_ability_obs_ids` ne construit sa table QUE sur ce tuple : elles étaient appliquées
    # par le moteur et invisibles à l'agent — le trou même que V11 §0.30 a fermé pour les armes,
    # et `deep_strike` pour les réserves. Chacune est vive, vérifiée par LECTURE du site qui
    # l'applique (pas de sa seule déclaration) le 2026-09-08 :
    #   deadly_demise                             `shared_utils.destroy_model` (§24.08, D6 puis MW
    #                                             dans les 6") — WeirdBoy
    #   grant_weapon_rule_melee                   `attack_sequence.build_weapon_attack_profile`
    #                                             (SUSTAINED HITS 1) — Bigboss
    #   grant_weapon_rule_melee_after_charge      idem (LETHAL HITS au tour de charge) — Vanguard
    #   grant_weapon_rule_vs_designated_target    `shared_utils._manual_roll_intent` (BLAST 1
    #                                             hors MONSTER/VEHICLE) — Eradicator
    #   weapon_attacks_bonus_vs_keyword           idem (+A hors keywords exclus) — BigMekDakkarig
    #   weapon_attacks_bonus_vs_designated_target idem (+A sur la cible) — Intercessor
    #   weapon_profile_scaling_by_model_count     idem (+F/+D par tranche de figurines) — WeirdBoy
    #   melee_attacks_bonus_while_waaagh          `fight_handlers._manual_roll_fight_intent`
    #                                             (+A pendant le Waaagh!) — Warboss
    #   feel_no_pain_vs_psychic                   `shared_utils._collect_fnp_thresholds_mortal`
    #                                             (seuil FNP si source PSYCHIC) — Librarian
    #   feel_no_pain_near_objective               idem (seuil FNP près d'un objectif) — Ancient
    #   mortal_wounds_on_critical_wound           `fight_handlers._manual_roll_fight_intent`
    #                                             (D6 MW, séquence terminée) — PainBoy
    #   mortal_wounds_on_fight_activation         `w40k_core._check_and_trigger_exhortation_de_rage`
    #                                             (D6 ≥ 4 → MW à l'activation) — ChaplainJumpPack
    #   secure_objective_on_control               `game_state.apply_secure_objective_on_control`
    #                                             (14.03, fin de phase de commandement) — Boyz,
    #                                             Intercessor
    #   oc_bonus                                  `game_state.unit_effective_oc`, source UNIQUE de
    #                                             l'OC pour le contrôle (14.02) — Ancient
    #
    # Restent DEHORS, sans `obs_id`, pour la même raison qu'avant : les capacités SOURCES
    # (`adaptable_predators`, `cunning_hunters`, `target_priority`, `targeted_intercession`,
    # `oath_of_moment`, `waaagh`, `adrenalised_onslaught`) — exposées par leurs effets — et les
    # marqueurs de RÔLE. Le verrou qui interdit qu'un `obs_id` soit à nouveau déclaré sans être
    # observé est `test_every_registered_obs_id_is_in_the_vocabulary`.
    "deadly_demise",
    "grant_weapon_rule_melee",
    "grant_weapon_rule_melee_after_charge",
    "grant_weapon_rule_vs_designated_target",
    "weapon_attacks_bonus_vs_keyword",
    "weapon_attacks_bonus_vs_designated_target",
    "weapon_profile_scaling_by_model_count",
    "melee_attacks_bonus_while_waaagh",
    "feel_no_pain_vs_psychic",
    "feel_no_pain_near_objective",
    "mortal_wounds_on_critical_wound",
    "mortal_wounds_on_fight_activation",
    "secure_objective_on_control",
    "oc_bonus",
)

class OncePerBattleSpent(NamedTuple):
    """Où lire, dans `game_state`, qu'un effet 1×/partie n'est PLUS EN VIGUEUR.

    `spent_key` porte les escouades qui l'ont dépensé. `still_in_effect_key` est l'exception :
    une capacité peut être dépensée ET continuer d'agir — Finest Hour consomme son usage à la
    première activation, mais accorde [DEVASTATING WOUNDS] jusqu'à la fin de cette phase de
    combat. Le prédicat du moteur (`shared_utils`, `attack_sequence`) est donc à DEUX ensembles,
    et l'observation ne peut pas n'en lire qu'un sans mentir pendant toute une phase.

    `still_in_effect_phase` est obligatoire dès qu'il y a une seconde clé, et n'est pas une
    précaution : `finest_hour_active_this_phase` n'est purgé qu'à l'ENTRÉE de la fight phase
    suivante (`fight_handlers.fight_v11_start`), donc il reste peuplé pendant les phases de
    commandement, mouvement et tir intermédiaires. Le moteur ne s'en aperçoit pas — il ne le lit
    qu'en combat, où la purge a déjà eu lieu ; l'observation, elle, est construite à CHAQUE step.
    """

    spent_key: str
    still_in_effect_key: Optional[str] = None
    still_in_effect_phase: Optional[str] = None


#: Effets 1×/PARTIE, et les clés de `game_state` qui disent s'ils sont encore en vigueur.
#: Registre du filtre d'observation : tant qu'un effet n'y figure pas, sa capacité reste écrite
#: dans les `ability_ids` d'une escouade qui ne peut plus l'employer, et l'agent perçoit un
#: avantage éteint.
#:
#: Le trou était là : `once_per_battle_melee_buff` était effacé par une lecture de
#: `finest_hour_used` écrite EN DUR dans le contexte d'observation, alors que
#: `return_destroyed_models` (Grot Orderly, même mention « 1×/partie » dans
#: `config/unit_rules.json`) ne l'était par rien — son `obs_id` restait visible après
#: restitution. Cette table remplace ce cas particulier : le filtre ne connaît plus aucune règle
#: par son nom.
#:
#: N'entre en `spent_key` qu'un ensemble d'`id` d'ESCOUADE DÉFINITIF pour la partie. Un ensemble
#: vidé en cours de partie — `_grot_orderly_skipped_this_phase`, remis à zéro à chaque début de
#: phase de commandement — décrit un renoncement temporaire, pas une dépense : l'inscrire
#: rendrait la capacité invisible un tour puis la ferait réapparaître.
ONCE_PER_BATTLE_SPENT_STATE_KEYS: Dict[str, OncePerBattleSpent] = {
    # Finest Hour (CaptainRelicShield) — les DEUX ensembles sont posés par `fight_handlers` à la
    # première activation, et c'est le second qui maintient [DEVASTATING WOUNDS] jusqu'à la fin
    # de la phase.
    "once_per_battle_melee_buff": OncePerBattleSpent(
        "finest_hour_used", "finest_hour_active_this_phase", "fight"
    ),
    # Grot Orderly (PainBoy) — posé par `command_handlers.apply_returned_models_placement`, et
    # relu par le balayage de la phase de commandement pour ne jamais reproposer la capacité.
    # Aucune rémanence : la restitution est instantanée, la capacité s'éteint avec son usage.
    "return_destroyed_models": OncePerBattleSpent("return_destroyed_models_used"),
}

_extra_once_per_battle = set(ONCE_PER_BATTLE_SPENT_STATE_KEYS) - set(UNIT_RULE_EFFECT_IDS)
if _extra_once_per_battle:
    raise ValueError(
        f"ONCE_PER_BATTLE_SPENT_STATE_KEYS reference des effets absents de "
        f"UNIT_RULE_EFFECT_IDS (rien ne les observerait, donc rien a effacer) : "
        f"{sorted(_extra_once_per_battle)}"
    )

_phaseless_still_in_effect = sorted(
    rule_id for rule_id, spec in ONCE_PER_BATTLE_SPENT_STATE_KEYS.items()
    if (spec.still_in_effect_key is None) != (spec.still_in_effect_phase is None)
)
if _phaseless_still_in_effect:
    raise ValueError(
        f"ONCE_PER_BATTLE_SPENT_STATE_KEYS : `still_in_effect_key` et `still_in_effect_phase` "
        f"vont par paire — sans la phase, un ensemble non purge ferait reapparaitre la capacite "
        f"hors de la phase ou elle agit : {_phaseless_still_in_effect}"
    )

#: Effets qu'un CANDIDAT DE DÉCISION peut accorder — sous-ensemble STRICT de
#: `UNIT_RULE_EFFECT_IDS`, et registre PROPRE du bloc `decision_options_bin`.
#:
#: POURQUOI SÉPARÉ. Un candidat de `rule_choice` est décrit POSITIONNELLEMENT (un bit par effet
#: accordable, × `MAX_DECISION_OPTIONS` slots). Tant que ce registre était le vocabulaire ENTIER,
#: toute capacité ajoutée à l'observation payait 6 bits qui restaient nuls à vie — mesuré le
#: 2026-08-04 : 6 des 13 effets n'étaient accordables par AUCUN `grantsRuleIds` de roster, soit
#: 36 scalaires morts. Séparer rend `obs_size` insensible au vocabulaire observé, ce qui est
#: précisément ce que le gel du chantier 01 existe pour garantir.
#:
#: SOURCE. Les effets TECHNIQUES atteignables depuis les `grantsRuleIds` déclarés dans les
#: rosters (`frontend/src/roster/**`), après résolution des sources composites par
#: `_resolve_unit_rule_entry_effect_rule_ids`. Recopié ici et non calculé, pour la MÊME raison
#: que `OBS_PHASE_IDS` : ce module est une FEUILLE, lire le registre y créerait un cycle. La
#: dérive est interdite par un test de contrat qui recalcule le tuple depuis les rosters —
#: déclarer un `grantsRuleIds` vers un effet absent d'ici fait échouer ce test ET lève au
#: moment de poser la décision (`agent_decision.normalize_decision_options`).
DECISION_GRANTABLE_EFFECT_IDS: Tuple[str, ...] = (
    "charge_after_flee",
    "reroll_1_save_fight",
    "reroll_1_tohit_fight",
    "reroll_1_towound",
    "reroll_towound_target_on_objective",
    "shoot_after_advance",
    "shoot_after_flee",
)

_extra_grantable = set(DECISION_GRANTABLE_EFFECT_IDS) - set(UNIT_RULE_EFFECT_IDS)
if _extra_grantable:
    raise ValueError(
        f"DECISION_GRANTABLE_EFFECT_IDS contient des effets absents de UNIT_RULE_EFFECT_IDS "
        f"(le moteur ne les appliquerait jamais) : {sorted(_extra_grantable)}"
    )

#: Drapeaux d'une unité, dans l'ordre d'émission.
#: CONVENTION (uniforme depuis §0.37) : le masque `present` est le DERNIER champ de CHAQUE
#: registre (unités, figurines self, armes, types) — il était ici en premier, seule exception,
#: et les lecteurs positionnels (`[..., 0]` vs `[..., -1]`) portaient deux conventions.
UNIT_BIN_FIELDS: Tuple[str, ...] = (
    "is_ally",             # 1 = mon camp, 0 = ennemi
    "is_active",           # 1 = l'unité observée (masque des features ci-dessus)
    "moved",
    "shot",
    "fought",
    "advanced",
    "fled",
    "charged",           # a fait une charge move ce tour (requis pour HI §15.11 Leap to Defend)
    "coherent",
    "engaged",             # dans la zone d'engagement d'une unité ADVERSE de cette unité
    # 13.09, émis pour TOUTE entité posée (masque = `present` ET NON `deploy_not_on_board`).
    # Ce n'est pas une propriété décorative : 13.09 conditionne la VISIBILITÉ elle-même, donc
    # `los_can_see` ci-dessous. Le lire sur `unit['hidden']` est INTERDIT — le moteur suit les
    # pertes (`destroy_model`) mais aucun mouvement, ce champ est donc périmé pendant le move et
    # après un pile-in adverse ; l'observation le recalcule à chaud (`_squad_terrain_flags`,
    # mode `hidden_only`).
    "hidden",
    "gone_to_ground",      # ⚠ unité ACTIVE uniquement (13.5)
    "in_cover",            # ⚠ unité ACTIVE uniquement (13.08)
    "deploy_not_on_board",  # one-hot mise en place (source `deployed_on_turn`)
    "deploy_pre_battle",
    "deploy_in_battle",
    "deployed_this_turn",  # clause 2 de [HEAVY] 24.16
    # Mots-clés de CATÉGORIE de la datasheet (PDF 02 Datasheets), valables pour TOUTE entité —
    # alliée, ennemie ou active. Ils décrivent l'entité seule, jamais une paire, donc leur masque
    # est `present` et rien d'autre.
    #
    # POURQUOI DES BITS POSITIONNELS, et non un troisième registre d'`obs_id` comme les capacités
    # et les statuts : le chantier 01 a sorti les 13 bits `rule_*` parce que leur vocabulaire
    # croît avec CHAQUE DATASHEET — 17 capacités pour Armageddon, autant à chaque faction
    # ajoutée — donc `obs_size` bougeait sans fin. Les mots-clés de catégorie sont fixés par le
    # LIVRE DE RÈGLES DE BASE : ajouter une faction entière n'en crée aucun. La cause qui
    # justifiait les identifiants est donc absente ici, et un `EmbeddingBag` n'aurait rien à
    # compresser sur un vocabulaire de 5 — il ajouterait une indirection (démêler une somme de
    # vecteurs) et un mode de défaillance (débordement de slots) que des bits n'ont pas.
    # Mesuré avant de trancher : 4 slots d'ids auraient coûté 128 scalaires contre 160 pour ces
    # bits, soit 0,19 % de l'observation — l'écart ne décide de rien.
    #
    # LA LISTE EST CLOSE PAR LA CONSOMMATION DU MOTEUR, pas par le livre : un mot-clé que rien
    # ne lit n'entre pas, sous peine d'un canal constant que le réseau ne peut relier à aucune
    # conséquence. Chacun cite ici le site qui le consomme, et c'est la condition d'entrée.
    #
    # ⚠️ CETTE CLÔTURE EST TENUE PAR UN TEST, pas par ce commentaire (2026-09-09) :
    # `test_squad_obs_category_keywords.py` dérive les mots-clés consommés des sources DÉCLARÉES
    # du moteur — `_HIDEABLE_KEYWORDS` et `_FLOOR_CAPABLE_KEYWORDS` (`game_state`),
    # `_MONSTER_OR_VEHICLE_KEYWORDS` (`shared_utils`), `ANTI_RULE_IDS` (`attack_sequence`) et les
    # littéraux passés à `_unit_has_keyword` (`movement_handlers`) — et exige de chacun un bit
    # ci-dessous ou une exclusion actée. Tant que rien ne le dérivait, la liste ne pouvait que se
    # périmer en silence : les tests parcouraient une table recopiée dans le test, donc un
    # mot-clé ajouté côté moteur n'en faisait échouer aucun.
    #
    # Sa portée est DÉCLARÉE et non totale : trois comparaisons écrites sur place lui échappent
    # (`shared_utils` ~5805 et ~11137, `fight_handlers` ~4706), toutes sur `monster`/`vehicle`,
    # qui ont leur bit. Le docstring du test en porte la liste à jour.
    #
    # N'y sont donc PAS : CHARACTER — l'allocation 19.02/19.04 lit le RÔLE de la figurine
    # (`_is_character_role`, shared_utils) et non le mot-clé, et les rôles sont déjà observés par
    # `MODEL_TYPE_BIN_FIELDS` ; BEASTS/SWARM — aucune datasheet JOUÉE n'en porte (mesuré le
    # 2026-09-09 : 42 unités des rosters d'agent ET d'adversaire, zéro porteur, et zéro écart
    # entre `hideable` et `INFANTRY` sur ce périmètre), si bien que le bit vaudrait colonne pour
    # colonne la copie de `kw_infantry` pour 32 scalaires et un retrain `--new` ; cette
    # exclusion-là est DATÉE, pas définitive — `test_no_played_roster_unit_carries_an_excluded_keyword`
    # tombe le jour où un roster joué en porte un ; BATTLELINE, WALKER, MOUNTED, GRENADES —
    # présents sur les datasheets, lus par aucune règle du moteur.
    "kw_infantry",   # 13.06/13.08/13.09 via `_HIDEABLE_KEYWORDS` (game_state) + [ANTI-INFANTRY]
    "kw_vehicle",    # volet MONSTER/VEHICLE de 10.06 (shooting_handlers) + [ANTI-VEHICLE]
    "kw_monster",    # volet MONSTER/VEHICLE de 10.06 + 13.06 via `_FLOOR_CAPABLE_KEYWORDS`
    "kw_fly",        # 13.06 via `_FLOOR_CAPABLE_KEYWORDS` + [ANTI-FLY]
    "kw_psyker",     # [ANTI-PSYKER] — `ANTI_RULE_IDS` (attack_sequence), `config/weapon_rules.json`
    # ⚠ Entités ENNEMIES uniquement (masque = `present` ET NON `is_ally`) : ces deux bits
    # décrivent une PAIRE (l'unité observatrice → cette entité), pas l'entité seule. Ils n'ont
    # aucun sens pour une alliée, et pour l'unité active la question n'est pas définie (contre
    # quel tireur ?) — son couvert intrinsèque, lui, reste porté par `in_cover`.
    #
    # Source : `compute_unit_los(observateur, cible)`, la source AUTORITATIVE du moteur — la
    # même que la résolution du `-1 BS` (`_cover_worsened_bs`) et que l'affichage frontend.
    # Ne PAS réimplémenter ici la branche « toutes mes figurines dans une terrain area » de
    # 13.08 : elle ne couvre qu'une des deux conditions alternatives, donc un bit à 0 voudrait
    # dire « indéterminé » au lieu de « pas de couvert ».
    # VISIBLE **ET** DÉTECTABLE — 06.01 ET 13.09, pas 06.01 seul. 13.09 dit « while a model is
    # hidden, it can only be visible to enemy models that are within its detection range » : une
    # cible cachée au-delà de la detection range n'est pas visible, et le moteur la REFUSE
    # (`valid_target_pool_build`). Tant que ce bit ne portait que la géométrie, l'observation
    # annonçait `1` sur une cible que l'action de tir rejetait — l'agent ne pouvait pas apprendre
    # à entrer dans les 15" ni à se cacher au-delà. Oracles moteur, non réimplémentés :
    # `compute_unit_los` pour 06.01, `hidden_enemy_out_of_detection` pour 13.09/13.5.
    #
    # ⚠️ À 0, ce bit ne distingue pas ses trois causes (masqué, hors détection, pas encore posé).
    # C'est voulu et sans perte : `hidden` (émis pour toute entité) et `edge_distance` les
    # séparent, pour ZÉRO scalaire de plus.
    "los_can_see",
    "cover_vs_observer",    # 13.08 EXACT : la cible a le bénéfice du couvert contre mon tir
    # ⚠ Entité ENNEMIE et phase de CHARGE uniquement (masque = `phase_charge` du contexte
    # global). V11 §9 P3-2 a fait de la cible de charge une décision de l'agent ; la tête
    # pointeur scorerait sinon des cibles sans savoir laquelle est ATTEIGNABLE.
    #
    # 1 ssi il existe un plan de charge LÉGAL vers cette cible au jet MAXIMAL (11.02 : 2D6, donc
    # 12"). À 0, déclarer la charge est perdu d'avance quel que soit le jet — l'unité perd son
    # activation entière. Rien d'autre ne le dit : `edge_distance` mesure une distance à vol
    # d'oiseau et ignore les trois causes réelles d'échec structurel — aucune case libre au
    # contact (cible encerclée ou collée à un mur), ER d'une escouade NON ciblée qui interdit le
    # placement (11.04 AFTER MOVING), et surtout la pénalité de descente 13.06, qui retranche du
    # jet une hauteur que l'observation n'expose nulle part.
    #
    # L'oracle est `charge_build_valid_plan`, la fonction MOTEUR qu'exécute le commit : une
    # réimplémentation annoncerait une atteignabilité que la résolution ne produirait pas.
    "charge_reachable_max_roll",
    # ⚠ Entité ENNEMIE et point d'arrêt de SÉLECTION D'ARME CC uniquement (V11 §0.69).
    # 1 = c'est cette escouade que le combat en cours va frapper. La cible est DÉJÀ fixée
    # (`pending_fight_weapon_select`, posé par `_fight_resolve_with_target`), et le choix demandé
    # à l'agent porte sur l'ARME — donc sur un jugement qui dépend entièrement de l'endurance, de
    # la sauvegarde et de l'effectif d'en face.
    #
    # Rien d'autre ne le disait, MESURÉ le 2026-09-09 : deux états ne différant que par la cible
    # désignée produisaient des observations IDENTIQUES au moment du `FIGHT_WEAPON_SLOT` (28 clés
    # comparées, écart maximal 0,0). La politique n'est pas récurrente (MaskablePPO) : elle ne se
    # souvient pas du `FIGHT_SLOT` joué au step précédent, l'observation doit donc porter le
    # contexte du point d'arrêt elle-même. Jumeau côté tir : `shoot_weapon_selected`
    # (`observation_weapon_profiles`), qui marque l'arme armée quand c'est la cible qui reste à
    # choisir.
    #
    # AUCUN bit de contexte global ne l'accompagne, et c'est délibéré : quand la sélection d'arme
    # est armée, la cible occupe TOUJOURS un slot ennemi observé — `_continue_squad_fight` lève
    # sinon (« cible(s) infrappable(s) ») et `FIGHT_SLOT_COUNT` vaut `K_ENEMY_SLOTS`. Le bit est
    # donc auto-porteur : hors de ce point d'arrêt, aucune entité ne le porte.
    "fight_target_selected",
    # VERTICALITÉ (13.06 / 22.05) — émis pour TOUTE entité posée. C'est le PRÉDICAT EXACT que
    # Plunging Fire interroge sur la CIBLE (« la cible contient >= 1 figurine au sol »), et non un
    # « niveau » générique : une unité peut être à cheval sur deux étages (03.03 tolère 5" de
    # dénivelé), donc un scalaire de niveau perdrait justement l'information dont la règle a
    # besoin. Avec `max_floor_height` ci-dessus, l'agent voit les DEUX faces de 22.05 : sa propre
    # hauteur de tir, et l'éligibilité de la cible.
    #
    # 1 par défaut au sens propre : une unité entièrement au sol contient bien >= 1 figurine au
    # sol. 0 signifie « toute l'unité est en hauteur », ce qui la met hors d'atteinte du tir
    # plongeant.
    "has_ground_model",
    # ⚠ Entités ENNEMIES et split-fire en cours uniquement (P3-8). Le bit `i` vaut 1 ssi l'arme
    # du slot de profil RNG `i` est DÉJÀ assignée à cette escouade. C'est la transposée exacte
    # de la table `assignments` : sur la ligne de la cible, quelles de mes armes la visent déjà.
    #
    # Rien d'autre ne le disait, MESURÉ le 2026-09-09 sur le chemin de production
    # (`_process_squad_action` puis `_build_observation_and_mask`) : après un premier couple
    # arme→cible commité, deux états ne différant que par CETTE cible produisaient des
    # observations identiques — 0 clé sur 28 — et aux DEUX sous-états, celui qui demande l'arme
    # suivante comme celui qui demande sa cible. Le masque ne le disait pas non plus : une cible
    # déjà prise reste éligible pour l'arme suivante (`shoot_weapon_eligible_target_slots`).
    #
    # POURQUOI 10 BITS ET NON UN SEUL « déjà ciblée » : 04.03 « Gather Attack Dice » cumule les
    # dés des armes faisant des IDENTICAL ATTACKS sur une même cible, donc la conséquence de
    # règle dépend de QUELLE arme y est déjà, pas du seul fait qu'une y soit. Un bit unique
    # suffirait à deux armes et perdrait l'appariement au-delà — or 55 % des escouades Armageddon
    # portent >= 3 profils de tir distincts, jusqu'à 6, soit 75 % de celles qui peuvent seulement
    # fractionner leur tir (mesuré le 2026-09-09 sur les 11 escouades SM+Orks des `config/armies/`,
    # attachements 19.04 compris). Le joueur humain, lui, voit toutes ses déclarations : 04.02 les
    # demande toutes AVANT la moindre résolution.
    #
    # POURQUOI SUR L'ENTITÉ et non dans un bloc dédié (10 x 20) : c'est la tête pointeur qui
    # score les lignes ennemies pour choisir la cible. L'information est ainsi portée par la
    # ligne même que la tête évalue, au lieu d'exiger une jointure avec un bloc séparé — et le
    # schéma d'entité est déjà lu génériquement par `ai/spatial_extractor` (`_UNIT_FAMILIES`),
    # donc aucun encodeur nouveau. Coût 10 x 32 = 320 scalaires.
    #
    # Le slot vient de `assignments[code]["weapon_slot"]`, RECOPIÉ du `pending_weapon_slot` du
    # moteur : le re-dériver du code d'arme ici ferait diverger l'obs et le commit (invariant D1).
    #
    # ⚠️ Leur NOMBRE est verrouillé sur `K_WEAPONS_RANGED` par un test
    # (`test_split_assigned_bits_cover_every_ranged_slot`), pas par ce commentaire : ces noms
    # sont littéraux parce que `K_WEAPONS_RANGED` est défini plus bas dans ce module, et un
    # littéral figé se périmerait en silence le jour où la cardinalité bouge.
    "split_assigned_w0",
    "split_assigned_w1",
    "split_assigned_w2",
    "split_assigned_w3",
    "split_assigned_w4",
    "split_assigned_w5",
    "split_assigned_w6",
    "split_assigned_w7",
    "split_assigned_w8",
    "split_assigned_w9",
    # L'unité fera-t-elle un test de Battle-shock au prochain 08.03 ? PRÉDICAT EXACT du moteur
    # (`command_handlers.command_step_battle_shock`) : `battle_shocked` OU
    # `is_unit_at_or_below_half_strength`. Le premier terme ne double PAS le statut `battle_shock` —
    # il porte la clause de sortie de 08.03 : une unité choquée reteste à chaque phase de
    # commandement et peut cesser de l'être, donc « choquée » et « va tester » ne sont pas le même
    # fait.
    #
    # Ce qu'il ajoute à `model_count_ratio` n'est PAS la clause de parité de l'appendice 25 :
    # mesuré par mutation le 2026-09-09, `restant / départ <= 0,5` lui est ÉQUIVALENT sur un
    # effectif en figurines — la parité ne peut jouer que là où `2 × restant == départ` est
    # arithmétiquement impossible. Ce qu'il ajoute, c'est la BASCULE DE MESURE : à force de départ
    # 1, l'appendice 25 compte les POINTS DE VIE, et un Warboss à 3 PV sur 6 doit tester alors
    # qu'`alive_models` et `model_count_ratio` valent exactement ce qu'ils valaient intact. Le bit
    # porte donc le prédicat ENTIER — union des deux mesures et clause de retest — au lieu d'un
    # branchement que le réseau aurait à reconstruire sur `alive_models`.
    "battle_shock_test_due",
    "present",             # masque d'entité (0 = slot vide / unité morte) — DERNIER, cf. ci-dessus
)

#: Nom du bit portant « l'arme du slot RNG `slot` est déjà assignée à cette escouade » (P3-8).
#: SOURCE UNIQUE du nom, partagée par l'observation et ses tests : deux constructions du même
#: nom écrites séparément divergeraient au premier renommage.
def split_assigned_field(slot: int) -> str:
    """Champ `split_assigned_w<slot>`. Slot hors des profils de tir -> IndexError explicite."""
    if not 0 <= int(slot) < K_WEAPONS_RANGED:
        raise IndexError(
            f"split_assigned_field: slot {slot!r} hors des {K_WEAPONS_RANGED} slots "
            f"de profils de tir"
        )
    return f"split_assigned_w{int(slot)}"

UNIT_CONT_SIZE = len(UNIT_CONT_FIELDS)
UNIT_BIN_SIZE = len(UNIT_BIN_FIELDS)

# ---------------------------------------------------------------------------
# Capacités et statuts d'une unité — ENSEMBLES D'IDENTIFIANTS (chantier 01)
# ---------------------------------------------------------------------------
#
# Les 13 bits `rule_<id>` ont vécu dans `UNIT_BIN_FIELDS` jusqu'au chantier 01. Le schéma
# grossissait LINÉAIREMENT avec le nombre de capacités du jeu : chaque capacité ajoutée changeait
# `UNIT_BIN_SIZE`, donc `obs_size`, donc invalidait tout modèle entraîné (`retrain --new`). Les
# 17 capacités Armageddon auraient coûté 17 × 28 = 476 scalaires et un retrain, et chaque faction
# ultérieure un retrain de plus.
#
# Une unité porte désormais deux ENSEMBLES D'ENTIERS (`obs_id`, registres `config/unit_rules.json`
# et `config/unit_statuses.json`), lus comme des lignes de deux `EmbeddingBag` distinctes
# (`ai/spatial_extractor.py`). Ajouter une capacité, un statut ou une faction entière ne change
# alors NI `obs_size`, NI le nombre de paramètres du réseau.
#
# ⚠️ Aucun one-hot n'est jamais matérialisé : un `EmbeddingBag` fait une LECTURE DE LIGNE. C'est
# ce qui rend la longueur du vecteur indépendante du nombre de capacités existantes.
#
# DEUX tables, pas une : « cette unité a Feel No Pain » et « cette unité est la cible Oath
# adverse » ne sont pas de même nature. Un pooling commun les additionnerait dans le même espace
# et le réseau ne pourrait plus les distinguer.
#
# Pooling SOMME (côté réseau) : invariant par permutation — {A, B} écrit (slot0, slot1) ou
# (slot1, slot0) donne le même vecteur, la propriété qui disqualifiait les slots naïfs — et il
# préserve la MULTIPLICITÉ, là où la moyenne confondrait un ensemble de 1 et un de 3.
#
# Les ids sont malgré tout écrits TRIÉS CROISSANT : le pooling rend l'ordre indifférent au
# réseau, pas au debug. Sans tri, l'observation ne serait plus reproductible bit à bit d'un run
# à l'autre et les diffs de replay deviendraient illisibles.

#: Capacités EN VIGUEUR (19.04) portées par une unité.
#:
#: DEUX chiffres, et il faut les distinguer — ce slot garde un chemin de crash dur (débordement
#: = `raise`), donc sa marge doit être lue sur la MESURE, pas sur la projection :
#:
#: - **Mesuré le 2026-08-04 sur le dépôt réel** (`UnitRegistry` + `unit_has_rule_effect` sur les
#:   13 effets, 179 datasheets, puis les unions 19.04 légales — 70 paires et 50 trios
#:   bodyguard + leader + support validés par les règles d'attachement 19.01/24.22/24.34) :
#:   **2** effets au maximum par datasheet, **3** au maximum en vigueur sur une entité
#:   (`AssaultIntercessor + CaptainPowerWeaponBolter [+ Ancient]` → `reroll_1_towound`,
#:   `reroll_charge`, `reroll_towound_target_on_objective`). Marge actuelle : 5 slots.
#: - **Projeté** une fois les capacités Armageddon livrées (chantier 06) : 6 en vigueur sur
#:   une même entité (`Boyz + Warboss + Painboy` → Get da Good Bitz, Might Is Right, Da Biggest
#:   and da Best, Dok's Toolz, Hold Still and Say Aargh, Grot Orderly ;
#:   `Intercessor + Captain Relic Shield + Ancient` → Objective Secured, Hail of Bolts, Finest
#:   Hour, Rites of Battle, Relic Banner, Unbreakable Resolve). Ces capacités N'EXISTENT PAS
#:   encore dans le moteur : c'est une projection de la conception du chantier 06, pas une mesure.
#:   Recalculé le 2026-08-30 sur les 25 capacités actées (contrainte 19.01 : max 1 leader +
#:   1 support par escouade ; Da Jump = action active, pas d'obs_id — même logique que Waaagh!
#:   en global_bin) : 6 au maximum sur une entité, marge 2 slots.
#:   UNIT_ABILITY_SLOTS = 8 tient pour l'intégralité du chantier 06.
#:   Détail : Documentation/Reference/moteur/capacites.md § « Dimensionnement des slots ».
#:
#: 8 et non 6 : dimensionner sur la projection laisserait ZÉRO marge le jour où elle se réalise —
#: une seule capacité ajoutée à une figurine rattachée ferait déborder. 8 coûte 2 × 28 = 56
#: scalaires (0,3 % de l'observation) pour supprimer un mode de défaillance dur.
#:
#: ⚠️ Débordement = ERREUR, jamais troncature (`observation_builder`) : tronquer ferait subir à
#: l'agent des règles qu'il ne perçoit pas — exactement le trou que V11 §0.30 avait fermé.
#:
#: ⚠️ Les effets de FACTION n'entrent PAS ici (chantier 03) : Waaagh! accorde quatre effets
#: identiques à TOUTES les unités orkes. Les inscrire par unité, c'est répéter 4 ids sur 28
#: entités et faire déborder les slots pour zéro information — le réseau reconstitue l'effet à
#: partir de « cette unité est orke » + « Waaagh! actif », deux informations GLOBALES. Ils vont
#: donc dans `GLOBAL_BIN_FIELDS`.
UNIT_ABILITY_SLOTS = 8

#: Statuts EN VIGUEUR portés par une unité (`battle_shock`, `oath_target`, `suppressed`).
#: Déclarés ici AVANT leurs chantiers respectifs (02, 03, 06) : c'est ce qui garantit qu'aucun
#: d'eux ne retouchera `obs_size`, donc qu'un SEUL retrain clôt la séquence.
UNIT_STATUS_SLOTS = 4

#: Domaine des identifiants écrits dans ces slots. C'est une dimension du SCHÉMA d'observation,
#: au même titre que les deux constantes ci-dessus : le registre (`config/unit_rules.json`,
#: `config/unit_statuses.json`) valide contre elles au chargement, l'écrivain
#: (`observation_builder._fill_id_slots`) les fait respecter à l'écriture, l'espace d'observation
#: (`w40k_core`) les déclare comme bornes, et le réseau (`ai/spatial_extractor`) dimensionne ses
#: tables dessus. Elles vivent donc ICI, dans le module FEUILLE que ces quatre consommateurs
#: importent déjà — et non dans `config_loader`, qu'`engine` et `ai` ne peuvent pas importer au
#: niveau module sans cycle (vérifié : `import config_loader` en premier casse alors sur
#: `pve_controller`).
#:
#: `0` est RÉSERVÉ au padding (`padding_idx` des tables d'embedding) : un slot vide doit
#: contribuer exactement zéro au pooling, sinon « pas de capacité » deviendrait une capacité.
OBS_ID_PADDING = 0
OBS_ID_MIN = 1
OBS_ID_MAX = 127
#: Nombre de lignes des tables d'embedding : padding + [OBS_ID_MIN, OBS_ID_MAX]. PRÉ-DIMENSIONNÉ,
#: jamais ajusté au nombre de capacités existantes — c'est ce qui rend l'ajout d'une capacité
#: gratuit en paramètres, donc sans retrain.
OBS_ID_VOCAB_SIZE = OBS_ID_MAX + 1

_UNIT_CONT_INDEX: Dict[str, int] = {name: i for i, name in enumerate(UNIT_CONT_FIELDS)}
_UNIT_BIN_INDEX: Dict[str, int] = {name: i for i, name in enumerate(UNIT_BIN_FIELDS)}


def unit_cont_index(field: str) -> int:
    """Index d'une feature continue d'unité. Nom inconnu -> KeyError explicite."""
    if field not in _UNIT_CONT_INDEX:
        raise KeyError(
            f"Feature continue d'unité inconnue : {field!r}. Champs : {UNIT_CONT_FIELDS}"
        )
    return _UNIT_CONT_INDEX[field]


def unit_bin_index(field: str) -> int:
    """Index d'un drapeau d'unité. Nom inconnu -> KeyError explicite."""
    if field not in _UNIT_BIN_INDEX:
        raise KeyError(
            f"Drapeau d'unité inconnu : {field!r}. Champs : {UNIT_BIN_FIELDS}"
        )
    return _UNIT_BIN_INDEX[field]


# ---------------------------------------------------------------------------
# Sous-registre « types de figurines » d'une unité
# ---------------------------------------------------------------------------

MODEL_TYPE_CONT_FIELDS: Tuple[str, ...] = (
    "hp_max", "toughness", "armor_save", "invul_save", "alive_count",
)
#: Rôles d'allocation (règle 19), ordre FIGÉ du one-hot. SOURCE UNIQUE des DEUX registres qui les
#: portent — le bloc TYPES ci-dessous et le bloc « mes figurines » (`SELF_MODEL_BIN_FIELDS`) : deux
#: tuples écrits à la main auraient pu diverger d'un rôle ou d'un ordre, et rien ne l'aurait dit.
#: Ce sont les valeurs du champ `role` d'une figurine, donc les clés de `ROLE_TIER`
#: (`phase_handlers/shared_utils`), verrouillé par test.
MODEL_ROLES: Tuple[str, ...] = ("special_weapon", "sergeant", "support", "leader")
#: 4 rôles d'allocation (règle 19) en one-hot + le masque de slot. Aucun bit = figurine de base.
MODEL_TYPE_BIN_FIELDS: Tuple[str, ...] = tuple(
    f"role_{role}" for role in MODEL_ROLES
) + ("present",)
MODEL_TYPE_CONT_SIZE = len(MODEL_TYPE_CONT_FIELDS)
MODEL_TYPE_BIN_SIZE = len(MODEL_TYPE_BIN_FIELDS)


# ---------------------------------------------------------------------------
# Sous-registre « mes figurines » (irréductiblement individuel, unité active seule)
# ---------------------------------------------------------------------------

#: ⚠️ `col_rel` / `row_rel` sont exprimés dans la projection `_hex_center` — la MÊME que la
#: grille égocentrique et que les directions d'objectif (V11 §0.32 T-I). Ce ne sont PAS des
#: différences de coordonnées offset : en offset, deux voisins hexagonaux de parités de ligne
#: différentes n'ont pas la même norme, et l'observation portait alors deux géométries.
#: `hp_ratio` : `HP_CUR / HP_MAX` de CETTE figurine. Le retrait pour cohérence (03.03) DÉTRUIT la
#: figurine désignée : sacrifier une figurine déjà entamée coûte moins que d'en sacrifier une
#: intacte, et rien d'autre dans l'observation ne le dit — le bloc TYPES ne porte que `hp_max`, par
#: type et non par figurine. Continu et non binaire parce qu'un Warboss à 5/6 et à 1/6 n'a pas la
#: même valeur restante ; le bit `wounded` ci-dessous en garde la version robuste (cf. son commentaire).
SELF_MODEL_CONT_FIELDS: Tuple[str, ...] = ("col_rel", "row_rel", "hp_ratio")
#: `present` est le masque de ce bloc, et il est EXPLICITE (V11 §0.32 T-H) : une figurine posée
#: sur le centroïde arrondi et sans aucun drapeau a une ligne entièrement nulle, donc un masque
#: déduit de la ligne (`(|cont| + |bin|) > 0`) la comptait ABSENTE — effectif faux servi sans
#: erreur, dans l'agrégation comme dans le dénominateur de `EntityRunningNorm`. Il est en DERNIÈRE
#: position, comme les masques des registres d'armes et de types (`[..., -1]`).
SELF_MODEL_BIN_FIELDS: Tuple[str, ...] = (
    # `elevated` : CETTE figurine finit-elle en hauteur (13.06, niveau >= 1) ? Irréductiblement
    # individuel, comme les deux bits qui le précèdent — depuis la déclaration de montée, une
    # escouade peut être à cheval sur le sol et un étage (03.03 tolère 5" de dénivelé), et
    # l'agrégat d'unité (`max_floor_height`, `has_ground_model`) ne dit pas LAQUELLE est en haut.
    # C'est pourtant ce qui décide, figurine par figurine, du +1 BS de 22.05 au tir suivant et du
    # coût de descente (13.06) au move suivant.
    "fight_eligible", "in_enemy_ez", "elevated",
) + tuple(
    # Rôle d'allocation (règle 19) de CETTE figurine, MÊME one-hot que le bloc TYPES. Il y était
    # déjà, mais AGRÉGÉ PAR TYPE : rien ne reliait le type « leader » à une ligne de ce bloc-ci.
    # Or `COHERENCY_SLOT_i` (P3-0) désigne la LIGNE i, et `pointer_policy._point` la score par un
    # produit scalaire nu sur son seul embedding, sans biais de slot : deux figurines de valeur
    # très différente sortaient des logits égaux. MESURÉ le 2026-09-09 (16 épisodes gym du pool
    # `training`, 8 points d'arrêt de cohérence) : 67 paires de figurines de valeur différente
    # sur 67 avaient une ligne `self_models_bin` IDENTIQUE — seule leur position les séparait,
    # alors que 4 des 8 pools mélangeaient un personnage attaché et des figurines de base.
    #
    # ⚠️ Le TRI de `_squad_models_for_observation` place déjà les rôles en tête, mais la tête
    # pointeur ne lit aucun index de slot : un rang non lu n'est pas une information observée.
    f"role_{role}" for role in MODEL_ROLES
) + (
    # `wounded` : `HP_CUR < HP_MAX`. Redondant avec `hp_ratio` par construction, et gardé quand
    # même : les continus de ce bloc passent par `EntityRunningNorm`, dont la variance est
    # minuscule sur une colonne quasi constante (la plupart des figurines sont intactes, et une
    # figurine à 1 PV max n'est jamais entamée), donc `hp_ratio` y sature vite à ±10. Le fait
    # « entamée » doit survivre à cette saturation ; le degré, lui, reste porté par `hp_ratio`.
    "wounded",
    "present",
)
SELF_MODEL_CONT_SIZE = len(SELF_MODEL_CONT_FIELDS)
SELF_MODEL_BIN_SIZE = len(SELF_MODEL_BIN_FIELDS)

_SELF_MODEL_CONT_INDEX: Dict[str, int] = {n: i for i, n in enumerate(SELF_MODEL_CONT_FIELDS)}
_SELF_MODEL_BIN_INDEX: Dict[str, int] = {n: i for i, n in enumerate(SELF_MODEL_BIN_FIELDS)}


def self_model_cont_index(field: str) -> int:
    """Index d'une feature continue de figurine. Nom inconnu -> KeyError explicite."""
    if field not in _SELF_MODEL_CONT_INDEX:
        raise KeyError(
            f"Feature continue de figurine inconnue : {field!r}. "
            f"Champs : {SELF_MODEL_CONT_FIELDS}"
        )
    return _SELF_MODEL_CONT_INDEX[field]


def self_model_bin_index(field: str) -> int:
    """Index d'un drapeau de figurine. Nom inconnu -> KeyError explicite."""
    if field not in _SELF_MODEL_BIN_INDEX:
        raise KeyError(
            f"Drapeau de figurine inconnu : {field!r}. Champs : {SELF_MODEL_BIN_FIELDS}"
        )
    return _SELF_MODEL_BIN_INDEX[field]


# ---------------------------------------------------------------------------
# Décision agent (V11 §9.3 — P2, mécanisme générique « décision agent »)
# ---------------------------------------------------------------------------

#: Types de points de décision exposés à l'agent, ordre FIGÉ du one-hot de contexte.
#: `rule_choice` est le pilote P3 point 0 ; `waaagh_call` est la décision binaire d'appel du
#: Waaagh! (chantier 03) ; `fly_declaration` est la déclaration « take to the skies » 21.03
#: (élément `L6`). Les tranches suivantes (allocation de pertes…) s'ajoutent ICI, jamais
#: en dupliquant le mécanisme.
#:
#: ✅ Ajouter un type ne change plus `obs_size` : le one-hot fait `AGENT_DECISION_TYPE_SLOTS`
#: colonnes, PRÉ-DIMENSIONNÉES (cf. plus bas). C'est l'arbitrage 2 de V11 §0.48 appliqué ici —
#: L3 (allocation de pertes), L4 (pile-in), L5 (move réactif), L6 (FLY 21.03), L7 (choix d'arme)
#: et L10 (placement de charge) ouvrent chacun un type, et aucun ne coûtera de retrain.
#:
#: ⚠️ `waaagh_call` est le premier type dont les DEUX candidats portent un `effect_ids` VIDE :
#: `DECISION_GRANTABLE_EFFECT_IDS` est dérivé des `grantsRuleIds` des rosters (verrouillé par
#: test de contrat), or aucun roster n'accorde les effets du Waaagh! — ils viennent de la
#: faction, pas d'une datasheet. Ce qui les distingue est le drapeau `declines` du bloc candidat
#: (`DECISION_OPTION_BIN_FIELDS`), et surtout PAS leur index.
#:
#: Ce fut écrit ici le contraire — « ce qui les distingue est le couple (type, INDEX) » — et
#: c'était FAUX, mesuré : l'index n'est écrit dans AUCUN scalaire d'observation, et la tête
#: pointeur score chaque candidat par un produit scalaire nu, sans biais par slot
#: (`pointer_policy._point`), donc délibérément agnostique à la position. Les deux lignes
#: sortaient `[0…0, present=1]` à l'identique : logits égaux, gradients égaux, symétrie
#: incassable — l'appel du Waaagh! était un pile-ou-face que PPO ne pouvait pas apprendre.
#:
#: ⚠️ `fly_declaration` (`L6`) est dans le MÊME cas, et son entrée portait la MÊME erreur (« ce
#: qui les distingue est le couple (type, INDEX) ») : « take to the skies » n'est accordé par
#: aucune datasheet — c'est le mot-clé FLY qui l'ouvre et 21.03 qui en fixe le prix —, donc ses
#: deux candidats portent eux aussi un `effect_ids` VIDE. C'est `declines` qui les sépare :
#: `CHOICE_1` renonce au vol, et le renoncement est précisément « ne rien faire ».
AGENT_DECISION_TYPE_IDS: Tuple[str, ...] = ("rule_choice", "waaagh_call", "fly_declaration", "allocation_model", "charge_placement", "mortal_wounds_target", "returned_models_placement", "returned_models_profile", "ascent_declaration", "move_after_shooting", "reactive_move")

#: Nombre MAXIMAL de candidats exposés à l'agent — le K de `CHOICE_0..K-1`
#: (`macro_intents.CHOICE_SLOTS`). Il vaut 6, l'alignement retenu par §9.3 sur les 6 slots
#: figurines. ⚠️ Ce n'est PAS une troncature silencieuse : une décision qui présenterait plus de
#: K candidats LÈVE (`agent_decision.set_pending_agent_decision`), conformément à la réserve 2 de
#: §9.0bis — une décision à grand espace se paramètre en INTENTIONS scorées, pas en top-K tronqué.
MAX_DECISION_OPTIONS = 6

#: Contexte de la décision (ce qui n'appartient à aucun candidat). Discret : jamais normalisé.
#: `decision_pending` vaut 0 tant qu'aucune décision n'est en attente POUR L'OBSERVATEUR — c'est
#: le masque du bloc entier, et l'unique bit qui distingue « pas de décision » de « décision de
#: type 0 ». Le nombre de candidats n'y figure pas : il est porté, candidat par candidat, par le
#: masque `present` du registre ci-dessous.
#: Nombre de colonnes du one-hot de TYPE de décision. Pré-dimensionné, jamais ajusté au nombre de
#: types déclarés : c'est ce qui rend l'ouverture d'un type gratuite en `obs_size`, exactement
#: comme `OBS_ID_VOCAB_SIZE` la rend gratuite pour une capacité. Les colonnes en trop restent à
#: zéro et ne reçoivent aucun gradient.
#:
#: 16 et non 8 : 8 types actuels (P3 complet, Grot Orderly) + 8 réservés pour J4/J5. Estimé :
#: fire_overwatch + heroic_intervention + da_jump_target (3) + 5 de marge. Le coût par type
#: ajouté est 1 scalaire par observation ; le coût d'un --new est plusieurs dizaines d'heures
#: à x1 et plusieurs centaines à x5 — la marge large est délibérée.
#: Dépasser ce nombre LÈVE ci-dessous — jamais de troncature, un type non observé serait une
#: décision que l'agent prend sans savoir laquelle on lui demande.
AGENT_DECISION_TYPE_SLOTS = 16

if len(AGENT_DECISION_TYPE_IDS) > AGENT_DECISION_TYPE_SLOTS:
    raise ValueError(
        f"{len(AGENT_DECISION_TYPE_IDS)} types de décision déclarés pour "
        f"{AGENT_DECISION_TYPE_SLOTS} colonnes de one-hot (AGENT_DECISION_TYPE_SLOTS). "
        f"Augmenter la constante — ce qui change obs_size et impose un retrain `--new`."
    )

#: Les types DÉCLARÉS gardent leur nom de champ (`decision_type_<id>`) et donc leur index : un
#: type ajouté s'insère APRÈS eux et ne déplace que des colonnes réservées, encore vides.
DECISION_CTX_BIN_FIELDS: Tuple[str, ...] = (
    ("decision_pending",)
    + tuple(f"decision_type_{decision_type}" for decision_type in AGENT_DECISION_TYPE_IDS)
    + tuple(
        f"decision_type_reserved_{i}"
        for i in range(AGENT_DECISION_TYPE_SLOTS - len(AGENT_DECISION_TYPE_IDS))
    )
)

#: Un CANDIDAT de décision, MÊME schéma pour tous les types (comme une unité, cf. §3.3) : c'est
#: ce qui permet à un encodeur PARTAGÉ de le lire et à la tête pointeur de le scorer, donc au
#: réseau de généraliser d'un slot de candidat à l'autre.
#:
#: Pour `rule_choice`, un candidat EST la règle qu'il accorde : le décrire par le one-hot de son
#: effet (`DECISION_GRANTABLE_EFFECT_IDS`) dit à l'agent CE QU'IL GAGNE. Un index de candidat,
#: lui, ne dit rien : l'ordre des options dépend du prompt.
#:
#: ⚠️ Ce bloc reste POSITIONNEL — un bit par effet ACCORDABLE — là où les capacités d'unité sont
#: passées aux ensembles d'`obs_id` (chantier 01). Ce n'est PAS un oubli de migration : un
#: candidat de décision accorde UN effet, jamais un ensemble, et il n'y a que
#: `MAX_DECISION_OPTIONS = 6` candidats. Ce qui a changé le 2026-08-04, c'est sa SOURCE : elle
#: était le vocabulaire observé ENTIER, si bien que le bloc grossissait à chaque capacité
#: ajoutée à l'observation, pour des bits jamais mis à 1 (6 effets sur 13 dans ce cas, 36
#: scalaires). Il ne grossit désormais que si une datasheet accorde un effet NOUVEAU par
#: `grantsRuleIds` — la seule condition sous laquelle un bit de plus porte de l'information.
#:
#: Aucun champ CONTINU n'existe aujourd'hui : `rule_choice` n'a aucune grandeur continue à
#: décrire, et en inventer une, remplie de zéros, serait une valeur par défaut sans signifiant.
#: Les tranches P3 qui en auront besoin (distance d'une destination, dégâts attendus sur une
#: cible) ouvriront un registre `DECISION_OPTION_CONT_FIELDS` à ce moment-là.
#:
#: ⚠️ `declines` n'est PAS un effet : c'est le seul champ qui décrive un candidat qui ne fait
#: RIEN. Une décision optionnelle (« you CAN call a Waaagh! », « you CAN take to the skies »)
#: oppose un candidat qui agit à un candidat qui passe, et le second n'accorde par construction
#: aucun effet — sans ce bit il est décrit par le vecteur nul, donc indiscernable de tout autre
#: candidat sans effet accordable. C'est exactement ce qui rendait `waaagh_call` inapprenable.
#:
#: POURQUOI PAS les effets. Les effets du Waaagh! sont DÉJÀ observés ailleurs, et mieux :
#: `my_waaagh_active` / `enemy_waaagh_active` (`GLOBAL_BIN_FIELDS`) portent son état d'armée, et
#: la 5+ invulnérable est déjà repliée dans l'invulnérable observée de chaque unité
#: (`ObservationBuilder`). Les redécrire par candidat aurait dupliqué cette information, fait
#: entrer des effets de FACTION dans un vocabulaire de règles d'UNITÉ, et coûté 3 bits × 6 slots
#: au lieu d'un seul — pour dire moins.
#:
#: POURQUOI PAS l'index du candidat. Il ne serait lisible qu'en donnant une sémantique de
#: position aux slots, ce que l'encodeur de candidat PARTAGÉ et la tête pointeur refusent par
#: construction (§9.3 P2) — et à raison : l'option 0 d'un prompt n'a rien à voir avec l'option 0
#: d'un autre. `declines` porte le sens lui-même, donc il généralise à toute décision optionnelle
#: (L4 pile-in, L5 move réactif, L6 FLY 21.03) sans rien ajouter.
#:
#: Il vaut 0 pour les DEUX candidats de `rule_choice` : ce choix-là n'a pas d'option « ne rien
#: faire », et c'est une information juste, pas un remplissage.
DECISION_OPTION_BIN_FIELDS: Tuple[str, ...] = tuple(
    f"grants_{rule_id}" for rule_id in DECISION_GRANTABLE_EFFECT_IDS
) + (
    "declines",  # ce candidat n'applique AUCUN effet : il passe (cf. bloc ci-dessus)
    "present",  # masque de candidat (0 = slot vide) — DERNIER, convention uniforme §0.37
)

DECISION_CTX_BIN_SIZE = len(DECISION_CTX_BIN_FIELDS)
DECISION_OPTION_BIN_SIZE = len(DECISION_OPTION_BIN_FIELDS)

#: Champs CONTINUS par candidat — ouverts par P3-4 (allocation des pertes défenseur, §9.4 pt 4),
#: élargis quand les cinq types dont les candidats n'accordent AUCUN effet ont dû devenir
#: discernables (mesuré : deux candidats à ligne binaire identique sortaient de
#: `SpatialCombinedExtractor` à un écart d'embedding de 0.0, et la tête pointeur les score par un
#: produit scalaire nu — logits égaux, donc pile-ou-face inapprenable).
#:
#: ⚠️ UNE COLONNE = UNE GRANDEUR, jamais « la première valeur de ce type-là ». Deux types qui
#: décrivent la MÊME grandeur écrivent dans la MÊME colonne (`dist_enemy_norm` sert à l'allocation
#: comme au placement des figurines rendues) ; deux grandeurs différentes ne partagent jamais une
#: colonne, même si aucun type ne les remplit ensemble. C'est ce qui rend légitime l'encodeur de
#: candidat PARTAGÉ (§3.3) : il ne voit pas le type de décision, seulement la ligne, et une
#: colonne au sens variable lui demanderait de deviner laquelle on lui présente.
#:
#: Les colonnes qu'un type ne remplit pas restent à zéro — même convention que les bits
#: `grants_*` d'un candidat qui n'accorde rien, et non une valeur par défaut inventée : c'est le
#: motif des colonnes remplies qui identifie la famille.
#:
#: ⚠️ TOUTES sont normalisées dans [0, 1] À LA SOURCE, et ce n'est pas une préférence de style :
#: le bloc N'EST PAS passé à une `EntityRunningNorm`. Ses statistiques glissantes excluent les
#: candidats absents (masque `present`) mais PAS les colonnes muettes d'un type ; avec six
#: colonnes à zéro sur huit, elles mélangeraient « sans objet » et vraies valeurs et fausseraient
#: l'échelle des deux. Un producteur qui émettrait une grandeur brute casserait donc l'échelle de
#: tout le bloc.
#:
#: `role_tier_norm` : ROLE_TIER de la figurine divisé par 4 (max du tier = 4, pour "leader").
#: Distingue base < special_weapon < sergeant < support < leader. (`allocation_model`)
#: `dist_enemy_norm` : distance (hex) du candidat à l'ennemi le plus proche, divisée par
#: (board_cols + board_rows) — borne conservative de la diagonale. Le « candidat » est la figurine
#: pour `allocation_model`, le centroïde du plan pour `returned_models_placement` : même grandeur,
#: même colonne. Les candidats blessés ne parviennent JAMAIS à l'allocation (05.04 les force
#: avant), donc HP_CUR = HP_MAX pour tous — inutile de le coder là.
#: `obj_dist_norm` : distance du centroïde du plan à l'objectif le plus proche, même borne.
#: (`charge_placement`, `returned_models_placement`)
#: `nontgt_dist_norm` : distance du centroïde du plan à l'ennemi NON déclaré comme cible de la
#: charge, même borne. Propre à `charge_placement` : hors d'une charge, « ennemi non ciblé » n'a
#: pas de référent, et le confondre avec `dist_enemy_norm` donnerait deux sens à une colonne.
#: `profile_value_norm` : VALUE d'une figurine du profil rendu, divisée par la plus forte VALUE
#: parmi les profils proposés — 1.0 = le profil le plus cher. (`returned_models_profile`)
#: `profile_count_norm` : nombre de figurines détruites de ce profil, divisé par le quota à
#: rendre, borné à 1.0 — 1.0 = ce profil peut remplir le quota à lui seul.
#: (`returned_models_profile`)
#: `target_wounded_hp_norm` : PV de la figurine la plus entamée de la cible divisés par son
#: HP_MAX (1.0 si aucune n'est entamée) — même grandeur que `wounded_hp_ratio` d'une unité, ici
#: portée par le candidat. Proche de 0 = les blessures mortelles achèvent une figurine.
#: (`mortal_wounds_target`)
#: `target_value_norm` : VALUE vivante de l'escouade cible, divisée par la plus forte parmi les
#: cibles proposées — 1.0 = la cible la plus précieuse. (`mortal_wounds_target`)
DECISION_OPTION_CONT_FIELDS: Tuple[str, ...] = (
    "role_tier_norm",
    "dist_enemy_norm",
    "obj_dist_norm",
    "nontgt_dist_norm",
    "profile_value_norm",
    "profile_count_norm",
    "target_wounded_hp_norm",
    "target_value_norm",
)
DECISION_OPTION_CONT_SIZE = len(DECISION_OPTION_CONT_FIELDS)

_DECISION_CTX_BIN_INDEX: Dict[str, int] = {
    name: i for i, name in enumerate(DECISION_CTX_BIN_FIELDS)
}
_DECISION_OPTION_BIN_INDEX: Dict[str, int] = {
    name: i for i, name in enumerate(DECISION_OPTION_BIN_FIELDS)
}
_DECISION_OPTION_CONT_INDEX: Dict[str, int] = {
    name: i for i, name in enumerate(DECISION_OPTION_CONT_FIELDS)
}


def decision_ctx_bin_index(field: str) -> int:
    """Index d'un drapeau de contexte de décision. Nom inconnu -> KeyError explicite."""
    if field not in _DECISION_CTX_BIN_INDEX:
        raise KeyError(
            f"Drapeau de contexte de décision inconnu : {field!r}. "
            f"Champs : {DECISION_CTX_BIN_FIELDS}"
        )
    return _DECISION_CTX_BIN_INDEX[field]


def decision_option_bin_index(field: str) -> int:
    """Index d'un drapeau de candidat de décision. Nom inconnu -> KeyError explicite."""
    if field not in _DECISION_OPTION_BIN_INDEX:
        raise KeyError(
            f"Drapeau de candidat de décision inconnu : {field!r}. "
            f"Champs : {DECISION_OPTION_BIN_FIELDS}"
        )
    return _DECISION_OPTION_BIN_INDEX[field]


def decision_option_cont_index(field: str) -> int:
    """Index d'un champ continu de candidat de décision. Nom inconnu -> KeyError explicite."""
    if field not in _DECISION_OPTION_CONT_INDEX:
        raise KeyError(
            f"Champ continu de candidat de décision inconnu : {field!r}. "
            f"Champs : {DECISION_OPTION_CONT_FIELDS}"
        )
    return _DECISION_OPTION_CONT_INDEX[field]


def decision_option_cont_row(values: Dict[str, float]) -> List[float]:
    """Ligne continue d'UN candidat, bâtie depuis des champs NOMMÉS.

    Le producteur nomme les grandeurs qu'il connaît ; les colonnes des autres familles restent à
    zéro. C'est le seul point où l'ordre de `DECISION_OPTION_CONT_FIELDS` est matérialisé : sans
    lui, chaque producteur recopierait une liste positionnelle de la longueur du registre, six
    zéros compris, et l'ajout d'une colonne demanderait de retoucher les cinq producteurs — le
    genre de recopie qui diverge en silence, puisqu'une ligne de la bonne longueur mais aux
    valeurs décalées passe toutes les validations.

    Un nom inconnu LÈVE (`decision_option_cont_index`) : une faute de frappe ne doit pas devenir
    une colonne muette, qui rendrait deux candidats à nouveau indiscernables sans rien casser.
    Une valeur hors [0, 1] LÈVE aussi — le bloc n'est pas normalisé en aval (cf. le registre),
    donc une grandeur brute casserait l'échelle de toutes les autres colonnes.
    """
    row = [0.0] * DECISION_OPTION_CONT_SIZE
    for field, value in values.items():
        val = float(value)
        if not 0.0 <= val <= 1.0:
            raise ValueError(
                f"decision_option_cont_row: {field!r} vaut {val}, hors [0, 1]. Les champs "
                f"continus de candidat sont normalisés À LA SOURCE — aucune normalisation "
                f"n'intervient en aval."
            )
        row[decision_option_cont_index(field)] = val
    return row


# ---------------------------------------------------------------------------
# Choix de l'escouade à ACTIVER (V11 §0.48 élément L2 / §9 P3-3)
# ---------------------------------------------------------------------------

#: Lignes du tenseur d'entités ALLIÉES : ligne 0 = l'escouade active, lignes 1..K-1 = mes autres
#: escouades. Vit ICI et non dans `observation_builder` parce que `macro_intents` en DÉRIVE
#: `ACTIVATE_SLOT_COUNT` (une action d'activation par ligne alliée) et ne peut pas importer
#: l'observation sans cycle — ce module est une FEUILLE, c'est ce qui le rend importable des deux
#: côtés. Les désolidariser ferait pointer le slot d'activation `i` et la ligne alliée `i` sur
#: deux escouades différentes sans que rien ne lève : c'est l'invariant D1, côté allié.
#:
#: 8 → 12 : à 8, la valeur ne portait qu'une marge d'observation (« au plus 6 escouades par camp
#: sur les rosters d'entraînement »). Depuis L2 elle porte le NOMBRE DE CANDIDATS D'ACTIVATION
#: adressables, ce qui la met en face de formats plus grands que les rosters courants. Le
#: sur-dimensionnement ne coûte AUCUN paramètre — les lignes passent par un encodeur PARTAGÉ
#: (`ai/spatial_extractor.py`), mesure de V11 §0.32 — seulement des scalaires d'observation
#: (511 par ligne) et du forward. Tout dépassement reste LOGUÉ, jamais silencieux.
K_ALLY_SLOTS = 12

#: Nombre de lignes du bloc figurines de l'escouade active (P3-0 — source unique partagée par
#: `observation_builder.ObservationBuilder.SQUAD_TOP_K`, `macro_intents.COHERENCY_SLOT_COUNT`
#: et `ai/spatial_extractor.py`). Le slot i de la tranche COHERENCY désigne la ligne i de
#: `_squad_models_for_observation(alive_mids)` — invariant D1 côté figurines.
SQUAD_TOP_K = 20

#: Nombre de slots de profils d'armes de MÊLÉE par entité (§0.69 — source unique pour que
#: `macro_intents.FIGHT_WEAPON_SLOT_COUNT` et `observation_builder.K_WEAPONS_MELEE` restent
#: synchronisés). Doit égaler `SquadObservationBuilder.K_WEAPONS_MELEE`.
K_WEAPONS_MELEE = 10

#: Nombre de slots de profils d'armes de TIR par entité (P3-8 — source unique pour que
#: `macro_intents.SHOOT_WEAPON_SEL_SLOT_COUNT` et `observation_builder.K_WEAPONS_RANGED` restent
#: synchronisés). Doit égaler `SquadObservationBuilder.K_WEAPONS_RANGED`.
K_WEAPONS_RANGED = 10


# ---------------------------------------------------------------------------
# Décision de DÉPLOIEMENT (V11 §0.40 point 3)
# ---------------------------------------------------------------------------

#: Nombre de slots de déploiement décrits. DOIT valoir `macro_intents.DEPLOY_SLOT_COUNT` (une
#: action `DEPLOY_SLOT_BASE + i` par slot) — verrouillé par test de contrat, comme
#: `N_OBJECTIVE_SLOTS` ↔ `MAX_OBJECTIVES`. La constante est recopiée ici et non importée parce
#: que ce module est une FEUILLE (cf. `OBS_PHASE_IDS`).
#:
#: 8 slots pour 7 STRATÉGIES définies (`macro_intents.DEPLOY_STRATEGY_COUNT`) : c'est
#: l'arbitrage 2 de V11 §0.48 appliqué au déploiement (élément `L11` de son inventaire). Le
#: slot en trop est RÉSERVÉ — le masque ne l'ouvre jamais (`open_deploy_slot_count` borne
#: au nombre de stratégies), sa ligne d'observation reste nulle, et son id d'action tombe dans
#: la plage des cellules de move, donc `TOTAL_ACTION_SIZE` ne bouge pas. Définir une 8ᵉ stratégie
#: se fera alors en incrémentant `DEPLOY_STRATEGY_COUNT`, sans toucher `obs_size` ni retrain.
#:
#: ⚠️ Réserver ici a un sens que réserver un bit de règle n'a pas : un slot de déploiement est une
#: ACTION. Le pré-dimensionnement ne vaut donc que parce que le masque garde la borne — sans elle,
#: l'agent pourrait jouer un slot sans stratégie derrière.
N_DEPLOY_SLOTS = 8

#: Ce que le slot `i` (action `DEPLOY_SLOT_BASE + i`) POSERAIT s'il était joué.
#:
#: Le défaut fermé ici : les 5 actions du déploiement ne sont pas « les 5 premiers hexes
#: valides » mais 5 STRATÉGIES (front agressif, pression sur objectif, sûr/cohésion, flanc
#: gauche, flanc droit) évaluées sur TOUS les hexes valides — et l'observation n'en décrivait
#: AUCUN. L'agent choisissait entre cinq boîtes noires : ni position, ni distance aux objectifs,
#: ni couvert, ni exposition. Depuis §0.40 points 1/2/4 il sait où est sa zone et voit le terrain
#: autour ; il ne savait toujours pas ce que chaque slot en ferait.
#:
#: DOCTRINE (la même que les candidats de décision §9.3 et que les slots ennemis) : un candidat
#: se décrit par L'EFFET qu'il accorde, jamais par son index. Deux raisons ici, et la seconde est
#: décisive : le masque n'ouvre que `min(5, n_hexes)` slots, donc en fin de déploiement ce sont
#: les stratégies d'INDICES BAS qui survivent — le lien slot ↔ stratégie n'est pas stable, et un
#: réseau qui aurait appris « le slot 7 va à gauche » se tromperait précisément là.
#:
#: SOURCE : `ActionDecoder.deployment_slot_candidates`, celle-là même que le commit exécute.
#: Aucune géométrie n'est recalculée — décrire les candidats depuis un second calcul aurait
#: laissé l'agent choisir d'après un hexe que le moteur n'aurait pas posé (motif D1).
DEPLOY_CAND_CONT_FIELDS: Tuple[str, ...] = (
    # Position de l'hexe candidat RELATIVEMENT à l'origine de mesure de l'observation
    # (`ObservationBuilder.squad_grid_anchor`, l'ancre de la zone tant que l'unité n'est pas
    # posée), dans la projection `_hex_center` — le repère UNIQUE de §0.32 T-I, celui de la
    # grille et des directions d'objectif. C'est ce qui rend les candidats comparables à la
    # fenêtre égocentrique : un candidat de flanc extrême tombe hors de la grille (limite
    # assumée du point 2), et ces deux nombres sont alors la SEULE chose qui le situe.
    "col_rel",
    "row_rel",
    # Grandeurs qui ont PRODUIT le choix de la stratégie, telles quelles (entiers, subhex) —
    # elles sortent du cache de scoring du décodeur, pas d'un second calcul.
    "objective_distance",       # hex le plus proche d'un CENTRE d'objectif
    "enemy_distance",           # … d'une référence ennemie (unités posées, sinon zone ennemie)
    "ally_distance",            # … d'un allié déjà posé (masque : `has_deployed_ally`)
    "los_exposure",             # nb d'ennemis DÉJÀ POSÉS qui voient cet hexe (06.01)
    "potential_los_exposure",   # nb d'ancres de la zone ennemie qui le voient (menace à venir)
    "ally_col_count",           # nb d'alliés déjà posés sur la même colonne (étalement)
)

DEPLOY_CAND_BIN_FIELDS: Tuple[str, ...] = (
    # Masque d'`ally_distance` : sans lui, 0 voudrait dire à la fois « collé à un allié » et
    # « aucun allié posé », deux situations opposées pour une stratégie de cohésion.
    "has_deployed_ally",
    # 14.02 : l'hexe est un hexe d'objectif. 13.08 : il donne le bénéfice du couvert. Les deux
    # viennent des MÊMES ensembles que les canaux « objectifs » et « couvert » de la grille
    # (`_grid_static_hex_arrays`) : une lecture, pas une géométrie.
    "on_objective",
    "in_cover",
    "present",  # slot OUVERT par le masque (0 = fermé) — DERNIER, convention uniforme §0.37
)

DEPLOY_CAND_CONT_SIZE = len(DEPLOY_CAND_CONT_FIELDS)
DEPLOY_CAND_BIN_SIZE = len(DEPLOY_CAND_BIN_FIELDS)

_DEPLOY_CAND_CONT_INDEX: Dict[str, int] = {n: i for i, n in enumerate(DEPLOY_CAND_CONT_FIELDS)}
_DEPLOY_CAND_BIN_INDEX: Dict[str, int] = {n: i for i, n in enumerate(DEPLOY_CAND_BIN_FIELDS)}


def deploy_cand_cont_index(field: str) -> int:
    """Index d'une feature continue de candidat de déploiement. Nom inconnu -> KeyError."""
    if field not in _DEPLOY_CAND_CONT_INDEX:
        raise KeyError(
            f"Feature continue de candidat de deploiement inconnue : {field!r}. "
            f"Champs : {DEPLOY_CAND_CONT_FIELDS}"
        )
    return _DEPLOY_CAND_CONT_INDEX[field]


def deploy_cand_bin_index(field: str) -> int:
    """Index d'un drapeau de candidat de déploiement. Nom inconnu -> KeyError."""
    if field not in _DEPLOY_CAND_BIN_INDEX:
        raise KeyError(
            f"Drapeau de candidat de deploiement inconnu : {field!r}. "
            f"Champs : {DEPLOY_CAND_BIN_FIELDS}"
        )
    return _DEPLOY_CAND_BIN_INDEX[field]


# ---------------------------------------------------------------------------
# Contexte global (ce qui n'appartient à aucune entité)
# ---------------------------------------------------------------------------

#: Nombre d'objectifs décrits par le contexte global. DOIT valoir `macro_intents.MAX_OBJECTIVES`
#: (l'action space offre 3 intents de zone par objectif) — verrouillé par test de contrat.
N_OBJECTIVE_SLOTS = 5

GLOBAL_CONT_FIELDS: Tuple[str, ...] = (
    "turn", "episode_steps", "my_victory_points", "enemy_victory_points",
    "my_value_ratio", "enemy_value_ratio",
    # Points de commandement des DEUX joueurs (08.02). Grandeur globale, pas une propriété
    # d'entité : les CP appartiennent au joueur, jamais à une unité. Les deux sont observés —
    # le stock adverse conditionne ce que l'adversaire pourra dépenser, exactement comme ses
    # points de victoire. Déclarés ici et non dans un bloc d'entité pour la même raison que
    # `my_victory_points`.
    "my_command_points", "enemy_command_points",
    # Distance de l'escouade OBSERVATRICE à chaque objectif, en subhex bruts (hex le plus proche
    # de la zone). Sans elle, un objectif hors de la grille égocentrique — dont la demi-étendue
    # vaut le budget d'Advance, soit 12" mesuré sur le board x5 — n'existe nulle part dans
    # l'observation, alors que 15 actions de zone le désignent : mesuré au reset, 1 à 2
    # objectifs sur 5 seulement tombent dans la fenêtre. L'agent choisissait une destination
    # qu'il ne percevait pas.
    "objective_distance_0", "objective_distance_1", "objective_distance_2",
    "objective_distance_3", "objective_distance_4",
    # OC LIVE par objectif (14.02, calculé sur les positions COURANTES) — sémantique DIFFÉRENTE de
    # objective_control_{i} dans GLOBAL_BIN_FIELDS, qui est la vérité 14.02 de FRONTIÈRE (relue de
    # objective_controllers, mis à jour à la fin de chaque phase/tour).
    # Ici : « si la phase finissait maintenant », sans attendre la frontière. Utile en phase de
    # move : l'agent voit l'OC évoluer à chaque déplacement. Valeurs brutes (VecNormalize).
    # Objectif absent → 0.0 (bit objective_present_{i} = 0 l'indique déjà).
    "objective_my_oc_0", "objective_my_oc_1", "objective_my_oc_2",
    "objective_my_oc_3", "objective_my_oc_4",
    "objective_enemy_oc_0", "objective_enemy_oc_1", "objective_enemy_oc_2",
    "objective_enemy_oc_3", "objective_enemy_oc_4",
)
#: Phases du moteur, dans l'ordre FIGÉ du one-hot `phase_*` de `GLOBAL_BIN_FIELDS`. DOIT valoir
#: `engine.action_decoder.GAME_PHASES` — verrouillé par test de contrat, comme
#: `N_OBJECTIVE_SLOTS` ↔ `macro_intents.MAX_OBJECTIVES`. La constante est recopiée ici et non
#: importée parce que ce module est une FEUILLE (aucune dépendance) : importer `action_decoder`,
#: qui tire tout le moteur, créerait un cycle.
OBS_PHASE_IDS: Tuple[str, ...] = (
    "deployment", "command", "move", "shoot", "charge", "fight",
)

#: La phase est un ONE-HOT de 6 bits (V11 §0.32 T-J). Elle vit avec les drapeaux car elle ne doit
#: JAMAIS être normalisée par des statistiques glissantes (V11 §9.5). L'encodage ordinal précédent
#: (0 / .25 / .5 / .75 / 1) avait deux défauts : il imposait une métrique entre phases qui n'a
#: aucun sens, et il donnait la MÊME valeur 0.0 à `deployment` et `command` — deux phases où les
#: ids d'action 4–8 signifient l'un « slot de déploiement », l'autre « cellule de move ».
#: Les sin/cos de direction d'objectif sont ici pour la MÊME raison de non-normalisation : déjà
#: bornés dans [-1,1] et centrés, les passer à `VecNormalize` ne ferait qu'amplifier leur bruit.
#: Slots pré-alloués pour les missions primaires (J4). Même logique que AGENT_DECISION_TYPE_SLOTS :
#: la taille reste stable à l'implémentation — les réservés se remplacent par des champs réels.
GLOBAL_BIN_MISSION_SLOTS = 48

GLOBAL_BIN_FIELDS: Tuple[str, ...] = (
    "is_my_turn",
    # SIÈGE — 1 ssi l'observateur joue PREMIER dans le battle round. `is_my_turn`, juste au-dessus,
    # dit qui a la main MAINTENANT ; il ne dit pas si l'adversaire rejoue APRÈS moi dans ce round.
    # Rien d'autre ne le disait : les onze registres d'observation sont égocentriques (`my_` /
    # `enemy_`, `ally` / `enemy`, positions relatives), aucun ne nomme le joueur.
    #
    # CE QUE LA RÈGLE EN FAIT DÉPENDRE. `turn` est le BATTLE ROUND et non le tour de joueur
    # (`_fight_end_progression_v10` ne l'incrémente qu'après le tour de P2) et P1 ouvre toujours
    # le round (`w40k_core` pose `current_player: 1`). Or le primaire se marque à la command phase
    # pour le premier joueur et à la FIGHT phase pour le second au round 5
    # (`round5_second_player_phase`, `config/primary_objective/Objectives_Control.json`) : au
    # round 5, le premier joueur a DÉJÀ marqué et son dernier tour ne lui rapporte plus de
    # primaire, le second joue le sien après. Deux états identiques à l'écran n'ont donc pas la
    # même valeur selon le siège, et l'agent ne pouvait pas les distinguer.
    #
    # LE SEUL SIGNAL EXISTANT ÉTAIT UN PROXY, ET IL SE DÉGRADE LÀ OÙ ÇA COMPTE : les zones de
    # déploiement sont attachées au joueur (`dz_p1` / `dz_p2` des mission cards) et
    # `objective_dir_cos/sin` sont calculés dans le repère ABSOLU du board
    # (`_squad_objective_geometry`), donc le réseau pouvait inférer son côté de carte tant que ses
    # unités restaient près de leur zone — partout SAUF au round 5, quand elles l'ont traversée.
    #
    # Dans global_bin et non global_cont pour la raison de tout ce bloc : `VecNormalize` ne
    # normalise que `global_cont` (`ai/train._vec_norm_obs_keys`), et recentrer un drapeau 0/1 par
    # des statistiques glissantes détruirait sa sémantique.
    "i_play_first",
) + tuple(f"phase_{phase}" for phase in OBS_PHASE_IDS) + (
    "objective_control_0", "objective_control_1", "objective_control_2",
    "objective_control_3", "objective_control_4",
    "objective_present_0", "objective_present_1", "objective_present_2",
    "objective_present_3", "objective_present_4",
    # Direction de l'escouade observatrice vers l'objectif (vecteur unitaire dans l'espace
    # projeté `_hex_center`, celui de la grille et du rendu). La distance seule ne dit pas où
    # aller ; c'est le couple des deux qui rend un objectif hors fenêtre navigable.
    "objective_dir_cos_0", "objective_dir_sin_0",
    "objective_dir_cos_1", "objective_dir_sin_1",
    "objective_dir_cos_2", "objective_dir_sin_2",
    "objective_dir_cos_3", "objective_dir_sin_3",
    "objective_dir_cos_4", "objective_dir_sin_4",
    # Statut SECURED (14.03) par objectif — un objectif sécurisé reste tenu même sans OC présent,
    # jusqu'à ce que l'adversaire ait STRICTEMENT plus d'OC à la fin d'une phase. Dans global_bin
    # (et non global_cont) : VecNormalize ne normalise que global_cont ; des slots toujours 0/1
    # y auraient variance ≈ 0 → clipping ±10. Ici les valeurs restent brutes.
    "objective_secured_mine_0", "objective_secured_mine_1", "objective_secured_mine_2",
    "objective_secured_mine_3", "objective_secured_mine_4",
    "objective_secured_enemy_0", "objective_secured_enemy_1", "objective_secured_enemy_2",
    "objective_secured_enemy_3", "objective_secured_enemy_4",
    # ---------------------------------------------------------------------------------------
    # CAPACITÉS DE FACTION (chantier 03) — Waaagh! et Oath of Moment
    # ---------------------------------------------------------------------------------------
    # Elles sont GLOBALES par construction : une capacité de faction s'applique uniformément à
    # toutes les unités de l'armée qui la portent. Les inscrire par unité répéterait les mêmes
    # ids sur 28 entités, ferait déborder `UNIT_ABILITY_SLOTS` et n'apporterait rien — le réseau
    # reconstitue l'effet à partir de « cette unité est orke » (ses ids de capacité) et de
    # « Waaagh! actif », qui est ici.
    #
    # QUATRE bits pour le Waaagh!, pas deux. Sa durée court « until the start of your next
    # Command phase » : elle ENJAMBE le tour adverse. Un Waaagh! ennemi actif pendant MON tour
    # change ce que je dois faire (l'armée d'en face a une invulnérable 5+ et +1 S/A en mêlée) ;
    # un Waaagh! ennemi encore DISPONIBLE change ce que je dois craindre au tour suivant. Les
    # deux faits sont distincts et aucun ne se déduit de l'autre.
    "my_waaagh_available", "my_waaagh_active",
    "enemy_waaagh_available", "enemy_waaagh_active",
    # Oath : DEUX bits seulement, parce que l'identité de la cible n'est pas ici — elle est
    # portée par le statut `oath_target` de l'entité visée (`enemies_status_ids` /
    # `allies_status_ids`), donc là où le réseau la lit avec l'unité qu'elle qualifie. Ces deux
    # bits ne disent que « une désignation est en vigueur », ce qu'aucun slot d'entité ne dirait
    # si toutes les cibles possibles étaient hors des K slots observés.
    "my_oath_target_selected", "enemy_oath_target_selected",
    # Clause CONDITIONNELLE du +1 au jet de blessure d'Oath : « If you are using a Codex: Space
    # Marines Detachment and your army does not include one or more units with the BLOOD ANGELS,
    # DARK ANGELS, DEATHWATCH or SPACE WOLVES keywords ». La relance de touche, elle, ne dépend
    # d'aucune des deux moitiés — d'où un bit distinct de `*_oath_target_selected`.
    #
    # POURQUOI DANS L'OBS. La clause dépend du ROSTER, que l'agent ne construit pas et ne peut
    # déduire d'aucune autre feature : les mots-clés de sous-faction des unités ALLIÉES ne sont
    # pas observés, et l'armée compte les unités MORTES. Sans ce bit, deux parties identiques à
    # l'écran n'ont pas la même règle, et l'agent ne peut pas distinguer « Oath faible » (relance
    # seule) d'« Oath fort » (relance + 1). Le gain du +1 est d'autant plus grand que la cible est
    # coriace (6+ -> 5+ double les blessures, 3+ -> 2+ ne les augmente que d'un cinquième) : les
    # deux régimes n'ont donc pas la même politique de DÉSIGNATION, et c'est ce choix-là que
    # l'agent joue par `OATH_SLOT_i`.
    #
    # Côté ENNEMI pour la même raison que le Waaagh! : savoir que l'adversaire blesse mieux ma
    # cible désignée change ce que je dois protéger. Aucun des deux ne se déduit de l'autre.
    "my_oath_wound_bonus_active", "enemy_oath_wound_bonus_active",
    # -----------------------------------------------------------------------
    # RETRAIT POUR COHÉRENCE 03.03 (P3-0) — un point d'arrêt EN COURS
    # -----------------------------------------------------------------------
    # « L'escouade observée doit désigner une figurine à DÉTRUIRE, maintenant. » MESURÉ le
    # 2026-09-09 sur les 8 points d'arrêt rencontrés : l'observation de la même escouade, avec et
    # sans `pending_coherency_removal` armé, est STRICTEMENT identique (écart 0.0 sur toutes les
    # clés). Le masque, lui, n'ouvre que les slots COHERENCY (vérifié au même endroit), donc la
    # POLITIQUE ne peut pas se tromper d'action ; c'est la VALEUR de l'état qui était fausse — un
    # état où une figurine est perdue d'office valait autant que le même état sans retrait.
    #
    # Un seul bit, et il concerne l'escouade OBSERVÉE : pendant un retrait, l'observateur EST
    # l'escouade en attente (`PLAYER_CHOICE_MECHANISMS`, `observer_squad_key="squad_id"`), donc un
    # bit « un retrait est en attente quelque part » aurait dit autre chose que ce qu'il nomme.
    "coherency_removal_pending",
    # -----------------------------------------------------------------------
    # RÉSERVÉ — missions primaires (J4). global_bin est délibérément choisi
    # (et non global_cont) : VecNormalize normalise UNIQUEMENT global_cont ;
    # des slots toujours nuls y auraient une variance ≈ 0 → clipping à ±10.0
    # au --append. Dans global_bin, les valeurs restent brutes — pas de risque.
    # Capacité : type mission (one-hot ~5), triggers par round, flags objectif,
    # VP primaire quantifié (ex. 6 niveaux → 6 bits par joueur). 48 slots
    # couvrent largement ces besoins (estimation : ~35 bits réels).
    # -----------------------------------------------------------------------
    *tuple(f"reserved_mission_bin_{i}" for i in range(GLOBAL_BIN_MISSION_SLOTS)),
)
GLOBAL_CONT_SIZE = len(GLOBAL_CONT_FIELDS)
GLOBAL_BIN_SIZE = len(GLOBAL_BIN_FIELDS)

_GLOBAL_CONT_INDEX: Dict[str, int] = {name: i for i, name in enumerate(GLOBAL_CONT_FIELDS)}
_GLOBAL_BIN_INDEX: Dict[str, int] = {name: i for i, name in enumerate(GLOBAL_BIN_FIELDS)}


def global_cont_index(field: str) -> int:
    """Index d'une feature continue globale. Nom inconnu -> KeyError explicite."""
    if field not in _GLOBAL_CONT_INDEX:
        raise KeyError(
            f"Feature continue globale inconnue : {field!r}. Champs : {GLOBAL_CONT_FIELDS}"
        )
    return _GLOBAL_CONT_INDEX[field]


def global_bin_index(field: str) -> int:
    """Index d'un drapeau global. Nom inconnu -> KeyError explicite."""
    if field not in _GLOBAL_BIN_INDEX:
        raise KeyError(
            f"Drapeau global inconnu : {field!r}. Champs : {GLOBAL_BIN_FIELDS}"
        )
    return _GLOBAL_BIN_INDEX[field]
