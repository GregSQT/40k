"""T5 — phase de charge (PDF 11).

Déterminisme : le jet 2D6 est remplaçable par ``charge_roll_override``, transporté au
PREMIER niveau du corps de l'action (comme ``shoot_pool_require_los``, api_server.py:2392)
et pris en compte dès l'activation — c'est là que le moteur fait le jet en PvP, conformément
à 11.02 (jet AVANT la déclaration des cibles). Les scénarios sont donc exacts : « jet forcé à
N » et non « jet observé ».
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _engine_state():
    import services.api_server as api_server

    engine = api_server.engine
    assert engine is not None, "aucune partie en cours"
    return engine.game_state


def _footprint_distance(client, first_id, second_id) -> int:
    """Distance minimale entre les EMPREINTES de deux unités, en sous-hexes.

    Même brique que le moteur (``min_distance_between_sets`` sur ``occupied_hexes``) : les
    distances de charge se mesurent socle à socle, jamais entre les ancres d'escouade.
    """
    from engine.hex_utils import min_distance_between_sets

    units_cache = _engine_state()["units_cache"]
    return min_distance_between_sets(
        units_cache[str(first_id)]["occupied_hexes"],
        units_cache[str(second_id)]["occupied_hexes"],
    )


def _engagement_zone() -> int:
    from engine.spatial_relations import get_engagement_zone

    return get_engagement_zone(_engine_state())


def _engaged_pairs(client, unit_id):
    zone = _engagement_zone()
    player = int(client.unit(unit_id)["player"])
    return {
        str(other["id"])
        for other in client.state["units"]
        if int(other["player"]) != player
        and other["HP_CUR"] > 0
        and _footprint_distance(client, unit_id, other["id"]) <= zone
    }


class TestChargeEligibility:
    def test_the_charge_pool_follows_rule_11_02(self, game):
        """t5_11_02_pool : le pool de charge respecte les exclusions de 11.02.

        PDF 11.02 : « A unit is eligible to declare a charge if it is on the battlefield »,
        sauf notamment : pas à moins de 12" d'une unité ennemie, déjà engagée, ou ayant fait
        un mouvement d'advance ou de fall-back ce tour.
        """
        game.drain_to("charge")
        pool = game.pool("charge_activation_pool")
        assert pool, "pool de charge vide"
        player = game.current_player
        alive = set(game.alive_ids(player))
        twelve_inches = 12 * int(game.state["inches_to_subhex"])

        assert set(pool) <= alive, "unité morte ou adverse dans le pool de charge"
        assert not set(pool) & set(str(u) for u in game.state["units_advanced"])
        assert not set(pool) & set(str(u) for u in game.state["units_fled"])
        for unit_id in pool:
            assert not _engaged_pairs(game, unit_id), (
                f"{unit_id} est déjà engagée et reste dans le pool de charge (11.02)"
            )
            nearest = min(
                _footprint_distance(game, unit_id, enemy)
                for enemy in game.alive_ids(game.enemy_player())
            )
            assert nearest <= twelve_inches, (
                f"{unit_id} : ennemi le plus proche à {nearest} sous-hexes > 12\" (11.02)"
            )

    def test_units_that_advanced_are_excluded_from_the_charge_pool(self, game):
        """t5_11_02_advance : une unité qui a avancé ne peut pas déclarer de charge."""
        unit_id = game.pool("move_activation_pool")[0]
        game.act("activate_unit", unitId=unit_id)
        game.act("advance", unitId=unit_id)
        assert unit_id in [str(u) for u in game.state["units_advanced"]]

        game.drain_to("charge")

        assert unit_id not in game.pool("charge_activation_pool")


class TestChargeRoll:
    @pytest.mark.parametrize("roll", [4, 8, 12])
    def test_the_forced_roll_bounds_the_declarable_targets(self, game, roll):
        """t5_11_04_portee : aucune cible déclarable au-delà du jet de charge.

        PDF 11.04, BEFORE MOVING : « Select one or more enemy units that are within 12" of
        your unit and within the maximum distance of your unit » — la distance maximale
        étant le jet de charge (11.02, étape 2). La distance à parcourir pour déclarer une
        cible n'est pas la distance socle-à-socle brute : l'unité s'arrête à la zone
        d'engagement, et elle ne peut PAS y être déjà (encadré FAILED CHARGES de 11.02).
        Le budget nécessaire est donc ``distance − zone d'engagement``.

        Mesuré : le moteur est plus strict que la lettre de 11.04 — il n'offre que les
        cibles qu'il peut réellement engager (empreinte finale légale). Deux ennemis à
        portée d'un jet de 12 sont ainsi écartés faute de placement possible. C'est le
        résultat correct (11.04 AFTER MOVING exige l'engagement de TOUTES les cibles), donc
        seul le sens « pas de cible hors de portée » est assertable.
        """
        game.drain_to("charge")
        unit_id = game.pool("charge_activation_pool")[0]
        scale = int(game.state["inches_to_subhex"])
        zone = _engagement_zone()
        budget = roll * scale

        activation = game.act("activate_unit", unitId=unit_id, charge_roll_override=roll)["result"]
        assert activation["charge_roll"] == roll
        targets = {str(t["id"]) for t in (activation.get("valid_targets") or [])}

        out_of_reach = 0
        for enemy in game.alive_ids(game.enemy_player()):
            distance = _footprint_distance(game, unit_id, enemy)
            assert distance > zone, "l'unité est déjà engagée : elle n'aurait pas dû charger"
            if distance - zone > budget:
                out_of_reach += 1
                assert enemy not in targets, (
                    f"jet {roll} : cible {enemy} déclarable alors qu'il faut parcourir "
                    f"{distance - zone} sous-hexes pour un budget de {budget}"
                )
            assert distance <= 12 * scale or enemy not in targets, (
                f"cible {enemy} au-delà de 12\" (11.02)"
            )
        assert out_of_reach > 0, (
            f"jet {roll} : aucun ennemi hors de portée, la borne n'est pas éprouvée"
        )

    def test_a_roll_of_two_fails_the_charge_without_moving(self, game):
        """t5_11_02_echec : jet de 2 → charge ratée, l'unité ne bouge pas.

        PDF 11.02 (encadré FAILED CHARGES) : « in the absence of modifiers to the charge
        roll, a result of 2 (a double 1) is never sufficient for a unit to complete a charge
        move, as a unit cannot be within engagement range (2") when it attempts a charge.
        Such a roll would therefore result in a failed charge, and the unit would not move. »
        """
        game.drain_to("charge")
        unit_id = game.pool("charge_activation_pool")[0]
        before = game.unit(unit_id)
        origin = (before["col"], before["row"])
        models_before = {
            m: (game.state["models_cache"][m]["col"], game.state["models_cache"][m]["row"])
            for m in game.models_of(unit_id)
        }

        result = game.act("activate_unit", unitId=unit_id, charge_roll_override=2)["result"]

        assert result["charge_roll"] == 2
        assert result["charge_failed"] is True
        assert result["charge_failed_reason"]
        assert result["removed_from_charge_pool"] is True
        after = game.unit(unit_id)
        assert (after["col"], after["row"]) == origin, "l'unité a bougé malgré la charge ratée"
        assert {
            m: (game.state["models_cache"][m]["col"], game.state["models_cache"][m]["row"])
            for m in game.models_of(unit_id)
        } == models_before, "une figurine a bougé malgré la charge ratée"
        assert unit_id not in game.pool("charge_activation_pool")
        assert unit_id not in [str(u) for u in game.state["units_charged"]]
        assert not _engaged_pairs(game, unit_id), "l'unité est engagée après une charge ratée"


class TestChargeMove:
    def test_a_committed_charge_engages_every_declared_target(self, game):
        """t5_11_04_apres_mouvement : après la charge, l'unité engage TOUTES ses cibles.

        PDF 11.04, AFTER MOVING : « Your unit must be engaged with all of the charge
        targets » et « Your unit cannot be engaged with one or more enemy units that are not
        charge targets ». WHILE MOVING : « Each model must end its move closer to one or
        more charge targets ».
        """
        game.drain_to("charge")
        unit_id = game.pool("charge_activation_pool")[0]
        activation = game.act("activate_unit", unitId=unit_id, charge_roll_override=12)["result"]
        target = str(activation["valid_targets"][0]["id"])
        distance_before = _footprint_distance(game, unit_id, target)

        declaration = game.act("charge", unitId=unit_id, targetId=target)["result"]
        assert declaration["valid_destinations"], "aucune destination pour une charge à 12\""
        assert game.state["charge_target_selections"][unit_id] == [target]

        plan = game.act("charge_autoplace", unitId=unit_id, mode="offensive")["result"]["plan"]
        assert plan, "autoplace n'a produit aucun placement"
        assert {str(entry[0]) for entry in plan} == set(game.models_of(unit_id)), (
            "le plan d'auto-placement ne couvre pas toutes les figurines"
        )

        result = game.act("commit_charge_plan", unitId=unit_id, plan=plan)["result"]

        assert result["charge_succeeded"] is True
        assert result["removed_from_charge_pool"] is True
        assert unit_id in [str(u) for u in game.state["units_charged"]]
        assert unit_id not in game.pool("charge_activation_pool")
        engaged = _engaged_pairs(game, unit_id)
        assert target in engaged, "la cible déclarée n'est pas engagée après la charge (11.04)"
        assert engaged == {target}, (
            f"l'unité engage des ennemis non déclarés : {engaged - {target}} (11.04)"
        )
        assert _footprint_distance(game, unit_id, target) < distance_before, (
            "l'unité ne s'est pas rapprochée de sa cible (11.04, WHILE MOVING)"
        )

    def test_the_charge_plan_refuses_a_destination_outside_the_engine_pool(self, game):
        """t5_plan_rejet : un plan hors du pool par figurine est refusé, l'unité reste au pool.

        Le placement de charge est par FIGURINE (comme le move) : ``charge_plan_state``
        publie le pool d'ancres légales de la figurine courante. Une destination hors de ce
        pool ne doit jamais être committée — sinon le plan manuel serait plus permissif que
        l'autoplace, ce que 11.04 interdit (mêmes contraintes pour les deux).
        """
        game.drain_to("charge")
        unit_id = game.pool("charge_activation_pool")[0]
        activation = game.act("activate_unit", unitId=unit_id, charge_roll_override=12)["result"]
        target = str(activation["valid_targets"][0]["id"])
        game.act("charge", unitId=unit_id, targetId=target)

        state = game.act("charge_plan_state", unitId=unit_id)["result"]
        assert state["eligible_models"], "aucune figurine éligible au plan de charge"
        assert state["can_validate"] is False, "un plan vide ne peut pas être validé"
        assert state["unsatisfied_targets"] == [target]

        origin = game.unit(unit_id)
        illegal = [[model_id, 0, 0] for model_id in game.models_of(unit_id)]
        accepted, body = game.try_act("commit_charge_plan", unitId=unit_id, plan=illegal)

        assert not accepted, "un plan hors pool a été accepté"
        assert body["_status"] == 200, f"refus attendu en 200, obtenu {body['_status']}"
        assert body["result"]["error"]
        after = game.unit(unit_id)
        assert (after["col"], after["row"]) == (origin["col"], origin["row"])
        assert unit_id in game.pool("charge_activation_pool"), "l'unité a quitté le pool sur un refus"
        assert unit_id not in [str(u) for u in game.state["units_charged"]]
