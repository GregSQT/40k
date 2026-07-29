"""T6 (amorce) — phase de mêlée : cycle de vie des déclarations d'attaque.

Jumeau strict du tir : ``pending_squad_fight_intents`` est créé à l'activation d'une
escouade et consommé par la résolution (``_build_manual_allocation``, shared_utils.py:8043).
Ce fichier verrouille les deux chemins où l'activation redémarre sans que la précédente
ait été résolue — le cas où le pending survivait et faisait lever
``assert_no_pending_fight_intent``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _engine_state():
    import services.api_server as api_server

    engine = api_server.engine
    assert engine is not None, "aucune partie en cours"
    return engine.game_state


def _footprint_distance(first_id, second_id) -> int:
    from engine.hex_utils import min_distance_between_sets

    units_cache = _engine_state()["units_cache"]
    return min_distance_between_sets(
        units_cache[str(first_id)]["occupied_hexes"],
        units_cache[str(second_id)]["occupied_hexes"],
    )


def _engaged_enemies(client, unit_id):
    from engine.spatial_relations import get_engagement_zone

    zone = get_engagement_zone(_engine_state())
    player = int(client.unit(unit_id)["player"])
    return {
        str(other["id"])
        for other in client.state["units"]
        if int(other["player"]) != player
        and other["HP_CUR"] > 0
        and str(other["id"]) in _engine_state()["units_cache"]
        and _footprint_distance(unit_id, other["id"]) <= zone
    }


def _drive_to_subphase(client, subphase: str) -> list[str]:
    """Amène la partie à une sous-phase de mêlée donnée, avec des unités éligibles.

    Chaque sous-phase a son propre verbe de sortie (cf. ``FIGHT_SUBPHASE_EXIT`` dans
    ``conftest.py``) ; ``nominal_action`` les enchaîne, ce qui traverse la phase dans l'ordre
    12.02 → 12.04 → 12.07.
    """
    for _ in range(400):
        if (
            client.phase == "fight"
            and client.state["fight_subphase"] == subphase
            and client.state["fight_eligible_units"]
        ):
            return [str(uid) for uid in client.state["fight_eligible_units"]]
        action, payload = client.nominal_action()
        client.act(action, **payload)
    raise AssertionError(f"sous-phase {subphase!r} avec unités éligibles jamais atteinte")


def _model_positions(client, unit_id):
    models_cache = client.state["models_cache"]
    return {
        m: (models_cache[m]["col"], models_cache[m]["row"])
        for m in client.state["squad_models"][str(unit_id)]
        if m in models_cache
    }


def _model_hitpoints(client, unit_id):
    models_cache = client.state["models_cache"]
    return {
        m: models_cache[m]["HP_CUR"]
        for m in client.state["squad_models"][str(unit_id)]
        if m in models_cache
    }


def _resolve_manual_allocation(client, unit_id, body):
    """Déroule la résolution d'un combat déclaré jusqu'à la fin de l'activation.

    Deux temps distincts côté défenseur (05.03/05.04) : d'abord l'ORDRE des groupes de
    figurines qui encaisseront (``squad_fight_declare_order`` — demandé seulement quand la
    cible a plusieurs groupes), puis une désignation de figurine par blessure
    (``squad_fight_manual_alloc``).
    """
    for _ in range(200):
        result = body["result"]
        if result.get("action") == "squad_fight_declare_order":
            order = [group["group_id"] for group in result["order_request"]["groups"]]
            body = client.act("squad_fight_declare_order", unitId=unit_id, order=order)
            continue
        allocation = result.get("allocation")
        if not allocation:
            return body
        body = client.act(
            "squad_fight_manual_alloc", unitId=unit_id, modelId=allocation["choices"][0]["model_id"]
        )
    raise AssertionError("la résolution du combat ne se termine pas")


class TestFightActivationRestart:
    def test_declaring_then_clicking_the_target_restarts_the_activation(self, game):
        """t6_fight_reactivation : assign par figurine puis clic direct sur la cible.

        Le flux manuel (``squad_fight_assign``) ouvre l'activation de l'escouade et pose son
        pending. Le clic direct sur une cible (``fight``) est l'autre chemin de résolution :
        il redéclare TOUTES les figurines éligibles contre cette cible, donc il redémarre
        l'activation. Il doit donc libérer le pending posé par le flux manuel, exactement
        comme ``squad_shoot_activate`` libère celui de l'escouade quittée en tir.

        Régression : sans cette libération, ``squad_fight_unit_activation_start``
        (fight_handlers.py:5774) levait ``assert_no_pending_fight_intent`` → HTTP 500.
        """
        eligible = _drive_to_subphase(game, "fight")
        attacker = eligible[0]
        game.act("activate_unit", unitId=attacker)
        targets = [str(t) for t in game.state["valid_fight_targets"]]
        assert targets, f"unité {attacker} activée sans cible valide"

        model_id = game.models_of(attacker)[0]
        game.act("squad_fight_assign", unitId=attacker, modelId=model_id, targetId=targets[0])
        assert attacker in game.state["pending_squad_fight_intents"], (
            "squad_fight_assign n'a pas ouvert d'activation"
        )

        accepted, body = game.try_act("fight", unitId=attacker, targetId=targets[0])

        assert body["_status"] == 200, (
            f"clic-cible après déclaration : HTTP {body['_status']} — {str(body.get('error'))[:200]}"
        )
        assert accepted

    def test_an_abandoned_fight_declaration_does_not_outlive_its_phase(self, game):
        """t6_fight_pending_purge : une déclaration jamais validée meurt avec la phase.

        Le joueur peut légitimement déclarer des attaques puis quitter la sous-phase sans
        valider. Ces pendings ne doivent pas franchir la fin de la phase de mêlée, sans quoi
        ils empoisonnent l'activation de la même escouade au tour suivant.
        """
        eligible = _drive_to_subphase(game, "fight")
        attacker = eligible[0]
        game.act("activate_unit", unitId=attacker)
        targets = [str(t) for t in game.state["valid_fight_targets"]]
        assert targets, f"unité {attacker} activée sans cible valide"
        model_id = game.models_of(attacker)[0]
        game.act("squad_fight_assign", unitId=attacker, modelId=model_id, targetId=targets[0])
        assert game.state["pending_squad_fight_intents"], "aucun pending à éprouver"

        game.play_nominal(max_actions=400, until=lambda c: c.phase != "fight")

        assert game.state["pending_squad_fight_intents"] == {}, (
            f"pendings survivants à la phase : {game.state['pending_squad_fight_intents']}"
        )


class TestFightSubphases:
    def test_each_subphase_only_answers_to_its_own_exit_verb(self, game):
        """t6_sous_phases : le verbe de sortie d'une autre sous-phase est un no-op silencieux.

        PDF 12 : la phase se déroule en PILE IN (12.02) → FIGHT (12.04) → CONSOLIDATE
        (12.07). Le dispatch du moteur accepte n'importe quel verbe et renvoie
        ``success: true`` sans rien faire quand il n'appartient pas à la sous-phase courante.
        C'est un piège documenté : un pilote automatique qui envoie le mauvais verbe boucle
        indéfiniment sans jamais voir d'erreur.
        """
        _drive_to_subphase(game, "pile_in")

        accepted, body = game.try_act("end_consolidation")
        assert accepted, "le moteur refuse désormais un verbe étranger : mettre à jour le piège"
        assert body["_status"] == 200
        assert game.state["fight_subphase"] == "pile_in", "un verbe étranger a fait avancer la phase"

        # 12.02 : « The player whose turn it is resolves all of their moves first, followed
        # by their opponent » — le pas de pile-in a donc DEUX moitiés, une par joueur, et
        # chacune se ferme par son propre end_pile_in.
        for _ in range(4):
            if game.state["fight_subphase"] != "pile_in":
                break
            game.act("end_pile_in")
        assert game.state["fight_subphase"] in ("fight", "consolidate"), (
            "end_pile_in n'a pas fait sortir de la sous-phase pile-in"
        )

    def test_eligible_units_to_fight_are_engaged_or_chargers(self, game):
        """t6_12_04_eligibilite : sont éligibles les unités engagées ou ayant chargé.

        PDF 12.04 : « A unit is eligible to fight if it has not already been selected to
        fight this phase and one or more of the following apply to it: it is engaged, or it
        was engaged at the start of this step; it made a charge move this turn. » Les
        chargeurs sont traités d'abord (Fights First, 11.04 AFTER MOVING), et les DEUX
        joueurs y figurent — l'alternance 12.04 est le cœur de la phase.
        """
        eligible = _drive_to_subphase(game, "fight")
        charged = {str(u) for u in game.state["units_charged"]}
        selected = {str(u) for u in game.state["units_selected_to_fight"]}

        for unit_id in eligible:
            assert unit_id not in selected, f"{unit_id} déjà sélectionnée pour combattre (12.04)"
            assert game.unit(unit_id)["HP_CUR"] > 0
            assert _engaged_enemies(game, unit_id) or unit_id in charged, (
                f"{unit_id} éligible sans être engagée ni avoir chargé (12.04)"
            )


class TestPileIn:
    def test_a_pile_in_move_stays_within_three_inches_and_keeps_engagements(self, game):
        """t6_12_03_pile_in : pile-in de 3" max, par figurine, engagements conservés.

        PDF 12.03 : MAXIMUM DISTANCE 3". BEFORE MOVING : « If your unit is engaged, select
        every enemy unit it is engaged with. » AFTER MOVING : « Your unit must be engaged »
        et « Each model that started this move engaged with an enemy unit must still be
        engaged with that enemy unit ».

        Borne assertée en hexes : chaque pas de BFS coûte au moins un sous-hex, donc
        ``hex_distance ≤ 3 × inches_to_subhex`` est vrai quel que soit le coût du terrain.
        """
        from engine.hex_utils import hex_distance

        eligible = _drive_to_subphase(game, "pile_in")
        scale = int(game.state["inches_to_subhex"])
        unit_id = eligible[0]

        state = game.act("activate_unit", unitId=unit_id)["result"]
        assert state["fight_subphase"] == "pile_in"
        assert state["pile_in_model_move"] is True, "le pile-in de référence est le par-figurine"
        targets = {str(t) for t in state["pile_in_targets"]}
        engaged_before = _engaged_enemies(game, unit_id)
        assert targets == engaged_before, (
            f"cibles de pile-in {targets} ≠ ennemis engagés {engaged_before} (12.03)"
        )

        plan = game.act(
            "pile_in_autoplace", unitId=unit_id, targetId=sorted(targets)[0]
        )["result"]["plan"]
        origins = _model_positions(game, unit_id)
        for model_id, col, row in [(str(e[0]), int(e[1]), int(e[2])) for e in plan]:
            assert model_id in origins, f"plan sur une figurine inconnue {model_id}"
            distance = hex_distance(origins[model_id][0], origins[model_id][1], col, row)
            assert distance <= 3 * scale, (
                f"{model_id} déplacée de {distance} sous-hexes, maximum 3\" = {3 * scale} (12.03)"
            )

        game.act("commit_pile_in_plan", unitId=unit_id, plan=plan)

        assert _engaged_enemies(game, unit_id) >= engaged_before, (
            "une unité a perdu un engagement pendant son pile-in (12.03, AFTER MOVING)"
        )


class TestFightResolution:
    def test_declared_attacks_damage_the_target_and_consume_the_activation(self, game):
        """t6_12_05_resolution : les attaques déclarées frappent, l'unité est consommée.

        PDF 12.04 : une unité ne peut être sélectionnée pour combattre qu'une fois par
        phase. 12.05 : le combat normal résout les attaques comme Making Attacks (04) ; les
        pertes sont allouées par le défenseur (05.03 ordre des groupes, 05.04 figurine par
        figurine).
        """
        eligible = _drive_to_subphase(game, "fight")
        attacker = eligible[0]
        game.act("activate_unit", unitId=attacker)
        targets = [str(t) for t in game.state["valid_fight_targets"]]
        assert targets, f"{attacker} activée sans cible valide"
        target = targets[0]
        assert target in _engaged_enemies(game, attacker), (
            "cible de mêlée hors engagement (12.05)"
        )

        game.act(
            "squad_fight_assign", unitId=attacker, modelId=game.models_of(attacker)[0], targetId=target
        )
        declarations = game.state["pending_squad_fight_intents"][attacker]
        assert declarations and declarations[0]["target_unit_id"] == target

        # Les PV sont comparés FIGURINE par FIGURINE : le total porté par l'unité diverge
        # du sien dès qu'un personnage est attaché (anomalie §0.6.4), il ne peut donc pas
        # servir de référence ici.
        hp_before = _model_hitpoints(game, target)
        _resolve_manual_allocation(game, attacker, game.act("squad_fight_validate", unitId=attacker))

        assert attacker in [str(u) for u in game.state["units_selected_to_fight"]]
        assert attacker not in [str(u) for u in game.state["fight_eligible_units"]], (
            "l'unité reste éligible après avoir combattu (12.04)"
        )
        assert attacker not in game.state["pending_squad_fight_intents"], (
            "les déclarations survivent à la résolution"
        )
        hp_after = _model_hitpoints(game, target)
        assert set(hp_after) <= set(hp_before), "une figurine est apparue dans la cible"
        for model_id, points in hp_after.items():
            assert points <= hp_before[model_id], f"{model_id} a regagné des PV en mêlée"
        killed = set(hp_before) - set(hp_after)
        for model_id in killed:
            assert model_id not in game.state["models_cache"], "figurine morte encore en cache"
            assert hp_before[model_id] > 0, "figurine déjà morte comptée comme tuée"
        assert sum(hp_before.values()) - sum(hp_after.values()) - sum(
            hp_before[m] for m in killed
        ) >= 0


class TestConsolidation:
    def test_an_engaged_unit_consolidates_in_ongoing_mode_only(self, game):
        """t6_12_08_consolidation : engagée → mode « ongoing » imposé, 3" par figurine.

        PDF 12.08, BEFORE MOVING : les trois modes sont mutuellement exclusifs et ordonnés —
        « Ongoing Consolidation: If your unit is engaged, you MUST select this mode and
        select every enemy unit it is engaged with », sinon « Engaging » (ennemis à 3"),
        sinon « Objective » (objectif à 3"). MAXIMUM DISTANCE : 3".
        """
        from engine.hex_utils import hex_distance

        eligible = _drive_to_subphase(game, "consolidate")
        scale = int(game.state["inches_to_subhex"])
        unit_id = next((u for u in eligible if _engaged_enemies(game, u)), None)
        assert unit_id is not None, "aucune unité engagée à la consolidation"

        state = game.act("activate_unit", unitId=unit_id)["result"]
        assert state["consolidation_mode"] == "ongoing", (
            f"mode {state['consolidation_mode']!r} pour une unité engagée (12.08)"
        )
        assert {str(t) for t in state["consolidation_targets"]} == _engaged_enemies(game, unit_id)
        assert state["awaiting_target_selection"] is False
        assert state["awaiting_objective_selection"] is False
        assert state["engaging_candidates"] == [], "candidats « engaging » exposés en mode ongoing"
        assert state["objective_candidates"] == [], "candidats « objective » exposés en mode ongoing"

        plan = game.act("consolidate_autoplace", unitId=unit_id)["result"]["plan"]
        origins = _model_positions(game, unit_id)
        for model_id, col, row in [(str(e[0]), int(e[1]), int(e[2])) for e in plan]:
            distance = hex_distance(origins[model_id][0], origins[model_id][1], col, row)
            assert distance <= 3 * scale, (
                f"{model_id} consolidée de {distance} sous-hexes, maximum 3\" = {3 * scale} (12.08)"
            )

        engaged_before = _engaged_enemies(game, unit_id)
        game.act("commit_consolidation_plan", unitId=unit_id, plan=plan)
        assert _engaged_enemies(game, unit_id) >= engaged_before, (
            "la consolidation « ongoing » a rompu un engagement (12.08)"
        )
