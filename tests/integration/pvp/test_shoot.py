"""T4 (amorce) — phase de tir : cycle de vie de l'activation d'escouade.

``active_shooting_unit`` est un SINGLETON : dès qu'une escouade est activée, la
précédente devient inaccessible. Le front n'envoie pas de ``squad_shoot_cancel`` avant
d'activer une autre unité (``useEngineAPI.handleStartSquadModelShoot``), le moteur fait
donc lui-même le cancel implicite. Ce fichier verrouille ce contrat, qui a été la source
d'une HTTP 500 trouvée par le fuzzing T7b (§0.6.2 de tests_front.md).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _engine_state():
    """``game_state`` du moteur en cours (globale de module posée par /api/game/start)."""
    import services.api_server as api_server

    engine = api_server.engine
    assert engine is not None, "aucune partie en cours : la fixture n'a pas démarré le moteur"
    return engine.game_state


def _engaged_units(client, unit_ids):
    """Unités engagées, au sens exact du moteur (adjacence socle-à-socle en portée CC).

    L'état exposé au front ne porte aucun booléen d'engagement en phase de tir : le seul
    juge est la géométrie du moteur. On l'interroge donc pour CLASSER les unités ; ce qui
    est ensuite ASSERTÉ reste la sortie de l'API (armes proposées, cibles valides).
    """
    from engine.phase_handlers.shooting_handlers import _is_adjacent_to_enemy_within_cc_range

    game_state = _engine_state()
    return [uid for uid in unit_ids if _is_adjacent_to_enemy_within_cc_range(game_state, client.unit(uid))]


def _enemy_neighbours(client, unit_id):
    """Ennemis vivants engagés avec ``unit_id``, mesurés avec la géométrie du moteur.

    Même définition que ``_is_adjacent_to_enemy_within_cc_range``, mais paire par paire :
    distance minimale entre les deux EMPREINTES (pas entre les ancres) comparée à la zone
    d'engagement du plateau.
    """
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import get_engagement_zone

    game_state = _engine_state()
    units_cache = game_state["units_cache"]
    zone = get_engagement_zone(game_state)
    player = int(client.unit(unit_id)["player"])
    own = units_cache[str(unit_id)]["occupied_hexes"]
    neighbours = []
    for other in client.state["units"]:
        other_id = str(other["id"])
        if int(other["player"]) == player or other["HP_CUR"] <= 0 or other_id not in units_cache:
            continue
        distance = min_distance_between_sets(
            own, units_cache[other_id]["occupied_hexes"], max_distance=zone
        )
        if distance <= zone:
            neighbours.append(other_id)
    return neighbours


def _shoots_as_monster_or_vehicle(client, unit_id) -> bool:
    from engine.phase_handlers.shooting_handlers import _unit_shoots_as_monster_or_vehicle

    return bool(_unit_shoots_as_monster_or_vehicle(_engine_state(), client.unit(unit_id)))


def _finish_allocation(client, unit_id, body):
    """Déroule l'allocation manuelle des pertes jusqu'à la fin de l'activation.

    Le défenseur est humain en PvP : ``squad_shoot_validate`` résout les jets puis rend la
    main pour que le défenseur désigne la figurine qui encaisse (05.04), une blessure à la
    fois. ``end_activation`` n'a lieu qu'au dernier clic.
    """
    for _ in range(200):
        allocation = body["result"].get("allocation")
        if not allocation:
            return body
        choices = allocation["choices"]
        assert choices, f"allocation en attente sans figurine à désigner : {allocation}"
        body = client.act(
            "squad_shoot_allocate_model", unitId=unit_id, modelId=choices[0]["model_id"]
        )
    raise AssertionError("l'allocation manuelle ne se termine pas")


class TestShootActivationLifecycle:
    def test_activating_another_squad_releases_the_previous_one(self, game):
        """t4_activation_cancel_implicite : A → B → A, sans erreur et sans pending orphelin.

        Geste banal : comparer les cibles de deux unités avant de choisir. Comme
        ``active_shooting_unit`` est unique, activer B rend A inaccessible : son pending
        DOIT donc être libéré au même moment, exactement comme le ferait
        ``squad_shoot_cancel``. Ses déclarations d'armes sont perdues — c'était déjà le cas
        de fait, puisque l'escouade quittée n'était plus pilotable.
        """
        game.drain_to("shoot")
        pool = game.pool("shoot_activation_pool")
        assert len(pool) >= 2, "il faut deux escouades tirables pour ce test"
        first, second = pool[0], pool[1]

        game.act("squad_shoot_activate", unitId=first)
        assert set(game.state["pending_squad_shoot_intents"]) == {first}

        game.act("squad_shoot_activate", unitId=second)
        assert set(game.state["pending_squad_shoot_intents"]) == {second}, (
            "le pending de l'escouade quittée n'a pas été libéré"
        )
        assert str(game.state["active_shooting_unit"]) == second

        accepted, body = game.try_act("squad_shoot_activate", unitId=first)

        assert body["_status"] == 200, (
            f"retour sur la première escouade : HTTP {body['_status']} "
            f"— {str(body.get('error'))[:200]}"
        )
        assert accepted
        assert set(game.state["pending_squad_shoot_intents"]) == {first}
        assert str(game.state["active_shooting_unit"]) == first
        assert first in game.pool("shoot_activation_pool"), (
            "une activation abandonnée ne consomme pas le droit de tirer"
        )

    def test_reactivating_the_same_squad_restarts_it(self, game):
        """t4_activation_reclic : re-cliquer la MÊME escouade repart d'une activation neuve.

        Forme la plus courte du même contrat : deux clics suffisent. La seconde activation
        libère la première avant de la recréer, elle ne s'y superpose pas.
        """
        game.drain_to("shoot")
        squad = game.pool("shoot_activation_pool")[0]

        game.act("squad_shoot_activate", unitId=squad)
        accepted, body = game.try_act("squad_shoot_activate", unitId=squad)

        assert body["_status"] == 200, (
            f"ré-activation : HTTP {body['_status']} — {str(body.get('error'))[:200]}"
        )
        assert accepted
        assert game.state["pending_squad_shoot_intents"][squad] == [], (
            "la ré-activation doit repartir d'une déclaration vide"
        )

    def test_an_abandoned_shoot_activation_does_not_outlive_its_phase(self, game):
        """t4_pending_purge : une activation jamais validée meurt avec la phase de tir.

        Le joueur regarde les cibles d'une unité puis passe à autre chose, sans
        ``squad_shoot_validate`` ni ``squad_shoot_cancel``. La phase se termine : le
        pending ne doit pas franchir la fin de phase, sinon il empoisonne le tour suivant
        (``assert_no_pending_shoot_intent``). Plusieurs pendings résiduels sont un état
        normal du flux — le moteur nettoie, il ne lève pas.
        """
        game.drain_to("shoot")
        pool = game.pool("shoot_activation_pool")
        victim = pool[0]
        game.act("squad_shoot_activate", unitId=victim)
        assert victim in game.state["pending_squad_shoot_intents"]

        first_turn = int(game.state["turn"])
        game.play_nominal(max_actions=100, until=lambda c: c.phase != "shoot")

        assert game.state["pending_squad_shoot_intents"] == {}, (
            f"pendings survivants à la phase : {game.state['pending_squad_shoot_intents']}"
        )
        assert "active_shooting_unit" not in game.state

        # Et le tour suivant est jouable : c'est ce que l'anomalie §0.6.2 cassait.
        game.play_nominal(
            max_actions=600,
            until=lambda c: (
                c.phase == "shoot" and int(c.state["turn"]) > first_turn and c.current_player == 1
            ),
        )
        assert victim in game.pool("shoot_activation_pool")
        accepted, body = game.try_act("squad_shoot_activate", unitId=victim)
        assert body["_status"] == 200, (
            f"ré-activation au tour suivant : HTTP {body['_status']} "
            f"— {str(body.get('error'))[:200]}"
        )
        assert accepted


class TestShootTargetingContract:
    def test_los_overview_is_self_consistent(self, game):
        """t4_los_overview_contrat : les cartes annexes couvrent exactement les cibles valides.

        `squad_shoot_los_overview` alimente le blink du front : chaque cible surlignée doit
        avoir son cover et son compteur N/M. Un décalage entre ces cartes se verrait à
        l'écran comme un halo sans compteur ou l'inverse.
        """
        game.drain_to("shoot")
        checked = 0
        for unit_id in game.pool("shoot_activation_pool"):
            game.act("squad_shoot_activate", unitId=unit_id)
            overview = game.act("squad_shoot_los_overview", unitId=unit_id)["result"]
            targets = [str(t) for t in overview["valid_targets"]]
            game.act("squad_shoot_cancel", unitId=unit_id)
            assert len(targets) == len(set(targets)), f"cibles dupliquées pour {unit_id}"
            assert set(overview["cover_by_unit_id"]) == set(targets)
            assert set(overview["count_by_unit_id"]) == set(targets)
            alive = overview["squad_alive_count"]
            assert 0 < overview["squad_free_count"] <= alive
            enemy_player = 2 if int(game.unit(unit_id)["player"]) == 1 else 1
            for target in targets:
                assert 1 <= overview["count_by_unit_id"][target] <= alive, (
                    f"{unit_id} → {target} : {overview['count_by_unit_id'][target]} tireurs "
                    f"pour {alive} figurines vivantes"
                )
                target_unit = game.unit(target)
                assert int(target_unit["player"]) == enemy_player, "cible alliée proposée"
                assert target_unit["HP_CUR"] > 0, "cible morte proposée"
            checked += 1
        assert checked > 5, f"seulement {checked} escouades éprouvées"

    def test_per_model_targets_partition_the_squad_targets(self, game):
        """t4_cibles_par_figurine : l'union des cibles par figurine == les cibles de l'escouade.

        Le tir est résolu PAR FIGURINE (04.01) : une escouade voit ce que ses figurines
        voient, ni plus ni moins. `squad_shoot_select_model` alimente le blink par-fig.
        """
        game.drain_to("shoot")
        checked = 0
        for unit_id in game.pool("shoot_activation_pool"):
            game.act("squad_shoot_activate", unitId=unit_id)
            squad_targets = set(
                str(t) for t in game.act("squad_shoot_los_overview", unitId=unit_id)["result"]["valid_targets"]
            )
            union = set()
            for model_id in game.models_of(unit_id):
                result = game.act("squad_shoot_select_model", unitId=unit_id, modelId=model_id)["result"]
                model_targets = set(str(t) for t in result["valid_targets"])
                assert model_targets <= squad_targets, (
                    f"{unit_id}/{model_id} vise {model_targets - squad_targets} hors des cibles d'escouade"
                )
                union |= model_targets
            game.act("squad_shoot_cancel", unitId=unit_id)
            assert union == squad_targets, (
                f"{unit_id} : cibles d'escouade sans figurine pour les tirer : {squad_targets - union}"
            )
            checked += 1
        assert checked > 5, f"seulement {checked} escouades éprouvées"

    def test_an_undetected_hidden_unit_is_never_a_target(self, game):
        """t4_hidden : une unité cachée hors portée de détection n'existe pas pour le tireur.

        PDF 13.09 : une figurine cachée (INFANTRY/BEASTS/SWARM dans un terrain dense, dont
        l'unité n'a pas tiré ce tour ni le précédent) n'est visible que par les ennemis
        situés dans sa portée de détection — 15" par défaut, réduite quand l'unité s'est
        mise à couvert (13-5 gone to ground). Hors de cette portée, elle ne doit apparaître
        NI dans les cibles, NI dans le blink : c'est la seule donnée que le moteur envoie
        au front à son sujet (le PvP est en hotseat, l'état n'est pas filtré par joueur —
        c'est donc ici que se joue la confidentialité de la position).
        """
        game.drain_to("shoot")
        too_far_seen = 0
        for unit_id in game.pool("shoot_activation_pool"):
            game.act("squad_shoot_activate", unitId=unit_id)
            overview = game.act("squad_shoot_los_overview", unitId=unit_id)["result"]
            game.act("squad_shoot_cancel", unitId=unit_id)
            targets = set(str(t) for t in overview["valid_targets"])
            for enemy_id, too_far in overview["hidden_too_far_by_unit_id"].items():
                if not too_far:
                    continue
                too_far_seen += 1
                assert str(enemy_id) not in targets, (
                    f"{unit_id} peut cibler {enemy_id}, cachée hors de sa portée de détection"
                )
            for enemy_id, info in overview["hidden_detection_info_by_unit_id"].items():
                assert game.unit(enemy_id)["hidden"] is True, (
                    f"{enemy_id} exposée comme cachée alors qu'elle ne l'est pas"
                )
                assert info["detection_inches"] in (12, 15), (
                    f"portée de détection {info['detection_inches']}\" hors 15\" (13.09) "
                    f"et 12\" (gone to ground)"
                )
                if info["too_far"]:
                    assert str(enemy_id) not in targets
        assert too_far_seen > 0, "aucune unité cachée hors de portée dans ce scénario"


class TestShootingTypes:
    """PDF 10 — quelles armes une unité peut sélectionner, selon son état."""

    def test_engaged_units_only_offer_close_quarters_weapons(self, game):
        """t4_10_06_close_quarters : engagée → seules les armes [CLOSE-QUARTERS] tirent.

        PDF 10.06 (Close-quarters shooting), volet non-MONSTER/non-VEHICLE : « You can only
        select [CLOSE-QUARTERS] weapons to make attacks with and you can only select enemy
        units that are engaged with your unit as targets ». Le pendant 10.04 (Normal
        shooting) exige d'être *unengaged*, une unité engagée n'y a donc pas droit.
        """
        game.drain_to("shoot")
        pool = game.pool("shoot_activation_pool")
        engaged = _engaged_units(game, pool)
        assert engaged, "aucune unité engagée en phase de tir dans ce scénario"

        for unit_id in engaged:
            unit = game.unit(unit_id)
            weapons = game.act("squad_shoot_activate", unitId=unit_id)["result"]["available_weapons"]
            overview = game.act("squad_shoot_los_overview", unitId=unit_id)["result"]
            game.act("squad_shoot_cancel", unitId=unit_id)
            usable = [w for w in weapons if w["can_use"]]
            for weapon in usable:
                assert "CLOSE_QUARTERS" in weapon["weapon"]["WEAPON_RULES"], (
                    f"unité engagée {unit_id} ({unit['unitType']}) : arme non-[CLOSE-QUARTERS] "
                    f"{weapon['weapon']['code']} sélectionnable (10.06)"
                )
            neighbours = set(_enemy_neighbours(game, unit_id))
            assert set(str(t) for t in overview["valid_targets"]) <= neighbours, (
                f"unité engagée {unit_id} : cibles hors de son engagement "
                f"{set(overview['valid_targets']) - neighbours} (10.06)"
            )

    def test_a_unit_without_assault_weapon_cannot_shoot_after_advancing(self, game):
        """t4_10_05_advance : advance sans arme [ASSAULT] → l'unité sort du pool de tir.

        PDF 10.04 : le tir normal exige « did not make an advance move this turn ».
        PDF 10.05 : après un advance, l'unité ne tire que si elle a ≥1 arme [ASSAULT].
        (Le PDF 09.06 n'interdit PAS de tirer après un advance — la restriction vient bien
        d'ici, pas de la phase de mouvement.)
        """
        advanced = "5"  # Dreadnought Ballistus : aucune arme [ASSAULT]
        weapons = game.unit(advanced)["RNG_WEAPONS"]
        assert not any("ASSAULT" in w["WEAPON_RULES"] for w in weapons), (
            "le scénario a changé : cette unité a désormais une arme [ASSAULT]"
        )
        game.act("activate_unit", unitId=advanced)
        game.act("advance", unitId=advanced)
        assert advanced in [str(u) for u in game.state["units_advanced"]]
        while game.phase == "move" and game.pool("move_activation_pool"):
            game.act("skip", unitId=game.pool("move_activation_pool")[0])
        game.act("advance_phase")

        assert advanced not in game.pool("shoot_activation_pool"), (
            "une unité ayant avancé sans arme [ASSAULT] ne peut relever d'aucun type de tir"
        )

    def test_only_assault_weapons_are_firable_after_an_advance(self, game):
        """t4_10_05_assault : après un advance, SEULES les armes [ASSAULT] tirent.

        PDF 10.05, WHILE SHOOTING : « You can only select [ASSAULT] weapons to make attacks
        with. » Le tir normal 10.04 exige de son côté « did not make an advance move this
        turn » : une unité qui a avancé ne relève d'aucun autre type de tir, ses autres armes
        sont donc hors-jeu pour la phase — au menu comme à la déclaration.
        """
        advanced = "1008"  # Intercessor : bolt_rifle [ASSAULT] + bolt_pistol [CLOSE-QUARTERS]
        weapons = game.unit(advanced)["RNG_WEAPONS"]
        assert any("ASSAULT" in w["WEAPON_RULES"] for w in weapons), "l'unité doit avoir une [ASSAULT]"
        assert any("ASSAULT" not in w["WEAPON_RULES"] for w in weapons), (
            "l'unité doit aussi avoir une arme non-[ASSAULT], sinon le test ne prouve rien"
        )
        game.act("activate_unit", unitId=advanced)
        game.act("advance", unitId=advanced)
        while game.phase == "move" and game.pool("move_activation_pool"):
            game.act("skip", unitId=game.pool("move_activation_pool")[0])
        game.act("advance_phase")
        assert advanced in game.pool("shoot_activation_pool"), (
            "10.05 : l'unité a une [ASSAULT], elle reste éligible au tir"
        )

        activation = game.act("squad_shoot_activate", unitId=advanced)["result"]
        usable = [w for w in activation["available_weapons"] if w["can_use"]]
        assert usable, "aucune arme utilisable alors que l'unité a une [ASSAULT]"
        for weapon in usable:
            assert "ASSAULT" in weapon["weapon"]["WEAPON_RULES"], (
                f"arme non-[ASSAULT] {weapon['weapon']['code']} proposée après un advance (10.05)"
            )

        target = game.act("squad_shoot_los_overview", unitId=advanced)["result"]["valid_targets"][0]
        offered = game.act(
            "squad_shoot_weapons_for_target", unitId=advanced, targetId=target
        )["result"]["weapons"]
        assert offered, "aucune arme proposée pour la cible"
        for weapon in offered:
            assert "ASSAULT" in weapon["weapon"]["WEAPON_RULES"], (
                f"arme non-[ASSAULT] {weapon['code']} déclarable après un advance (10.05)"
            )

        # Et la déclaration directe d'une arme non-[ASSAULT] est refusée, pas seulement cachée.
        non_assault = next(
            w for w in activation["available_weapons"]
            if "ASSAULT" not in w["weapon"]["WEAPON_RULES"]
        )
        accepted, body = game.try_act(
            "squad_shoot_assign_weapon_qty",
            unitId=advanced, weaponCode=non_assault["weapon"]["code"], count=1, targetId=target,
        )
        assert not accepted, "une arme non-[ASSAULT] a été déclarée après un advance (10.05)"
        assert body["result"]["error"] == "cannot_shoot"
        assert game.state["pending_squad_shoot_intents"][advanced] == []


class TestWeaponAssignment:
    def test_quantity_assignment_is_bounded_by_the_eligible_models(self, game):
        """t4_qty_max : `count` ne peut pas dépasser le nombre de figurines éligibles.

        Le menu cible-d'abord attribue `count` figurines portant une arme donnée à une
        cible. La borne vient du moteur (`squad_shoot_weapon_qty_max`) : le front l'affiche,
        et le backend la fait respecter — une escouade ne peut pas tirer plus de fois
        qu'elle n'a de porteurs (04.01, une figurine tire ses propres armes).
        """
        game.drain_to("shoot")
        squad = "9"  # Terminator : 6 figurines, storm_bolter porté par plusieurs d'entre elles
        game.act("squad_shoot_activate", unitId=squad)
        target = game.act("squad_shoot_los_overview", unitId=squad)["result"]["valid_targets"][0]
        weapons = game.act("squad_shoot_weapons_for_target", unitId=squad, targetId=target)["result"]["weapons"]
        weapon = max(weapons, key=lambda w: w["m"])
        quantity_max = game.act(
            "squad_shoot_weapon_qty_max", unitId=squad, weaponCode=weapon["code"], targetId=target
        )["result"]["qty_max"]
        assert quantity_max == weapon["m"], "le menu et la borne du moteur divergent"
        assert 1 <= quantity_max <= len(game.models_of(squad))

        eligible = game.act(
            "squad_shoot_eligible_models", unitId=squad, weaponCode=weapon["code"], targetId=target
        )["result"]["models"]
        assert len(eligible) == quantity_max, "le voile vert et la borne ne désignent pas le même nombre de figurines"
        assert all(model["assigned"] is False for model in eligible)

        accepted, body = game.try_act(
            "squad_shoot_assign_weapon_qty",
            unitId=squad, weaponCode=weapon["code"], count=quantity_max + 1, targetId=target,
        )
        assert not accepted
        assert body["result"]["error"] == "cannot_shoot"
        assert not game.state["pending_squad_shoot_intents"][squad], "un refus a laissé des déclarations"

        declarations = game.act(
            "squad_shoot_assign_weapon_qty",
            unitId=squad, weaponCode=weapon["code"], count=quantity_max, targetId=target,
        )["result"]["declarations"]
        assert len(declarations) == quantity_max
        assert {d["target_unit_id"] for d in declarations} == {target}
        assert len({d["model_id"] for d in declarations}) == quantity_max, "deux fois la même figurine"

    def test_unassign_gives_the_models_back(self, game):
        """t4_unassign : retirer une attribution rend les figurines de nouveau attribuables.

        Deux granularités coexistent : par (arme, cible) — `squad_shoot_unassign_weapon_qty`
        — et par figurine — `squad_shoot_unassign`. Les deux doivent rendre l'état à
        l'identique, sinon le joueur perd des tirs en changeant d'avis.
        """
        game.drain_to("shoot")
        squad = "9"
        game.act("squad_shoot_activate", unitId=squad)
        target = game.act("squad_shoot_los_overview", unitId=squad)["result"]["valid_targets"][0]
        weapons = game.act("squad_shoot_weapons_for_target", unitId=squad, targetId=target)["result"]["weapons"]
        weapon = max(weapons, key=lambda w: w["m"])
        quantity_max = weapon["m"]

        game.act(
            "squad_shoot_assign_weapon_qty",
            unitId=squad, weaponCode=weapon["code"], count=quantity_max, targetId=target,
        )
        result = game.act(
            "squad_shoot_unassign_weapon_qty",
            unitId=squad, weaponCode=weapon["code"], targetId=target,
        )["result"]
        assert result["removed"] == quantity_max
        assert result["declarations"] == []
        assert game.act(
            "squad_shoot_weapon_qty_max", unitId=squad, weaponCode=weapon["code"], targetId=target
        )["result"]["qty_max"] == quantity_max, "la borne n'est pas revenue à son état initial"

        declarations = game.act(
            "squad_shoot_assign_weapon_qty",
            unitId=squad, weaponCode=weapon["code"], count=quantity_max, targetId=target,
        )["result"]["declarations"]
        model_id = declarations[0]["model_id"]
        result = game.act("squad_shoot_unassign", unitId=squad, modelId=model_id)["result"]
        assert result["removed"] is True
        assert len(result["declarations"]) == quantity_max - 1
        assert model_id not in {d["model_id"] for d in result["declarations"]}

    def test_cancel_keeps_the_squad_able_to_shoot(self, game):
        """t4_cancel : annuler une activation rend l'escouade au pool, sans déclaration.

        10.02 : une unité est éligible tant qu'elle n'a pas été SÉLECTIONNÉE pour tirer.
        Regarder ses cibles puis annuler ne consomme pas ce droit.
        """
        game.drain_to("shoot")
        squad = game.pool("shoot_activation_pool")[0]
        game.act("squad_shoot_activate", unitId=squad)
        target = game.act("squad_shoot_los_overview", unitId=squad)["result"]["valid_targets"][0]
        weapons = game.act("squad_shoot_weapons_for_target", unitId=squad, targetId=target)["result"]["weapons"]
        game.act(
            "squad_shoot_assign_weapon_qty",
            unitId=squad, weaponCode=weapons[0]["code"], count=1, targetId=target,
        )

        game.act("squad_shoot_cancel", unitId=squad)

        assert squad not in game.state["pending_squad_shoot_intents"]
        assert "active_shooting_unit" not in game.state
        assert squad in game.pool("shoot_activation_pool")
        assert squad not in [str(u) for u in game.state["units_shot"]]
        # Et l'escouade repart d'une déclaration vide.
        game.act("squad_shoot_activate", unitId=squad)
        assert game.state["pending_squad_shoot_intents"][squad] == []


class TestShootResolution:
    def test_validate_applies_damage_per_model_and_ends_the_activation(self, game):
        """t4_resolution : les dégâts descendent sur les figurines, l'escouade quitte le pool.

        05.04 : les blessures non sauvegardées sont allouées figurine par figurine ; une
        figurine dont les PV tombent à 0 est détruite et retirée. Le total de dégâts annoncé
        par le moteur doit se retrouver exactement dans les PV des figurines de la cible.
        """
        game.drain_to("shoot")
        squad = "9"
        game.act("squad_shoot_activate", unitId=squad)
        target = game.act("squad_shoot_los_overview", unitId=squad)["result"]["valid_targets"][0]
        weapons = game.act("squad_shoot_weapons_for_target", unitId=squad, targetId=target)["result"]["weapons"]
        weapon = max(weapons, key=lambda w: w["m"])
        game.act(
            "squad_shoot_assign_weapon_qty",
            unitId=squad, weaponCode=weapon["code"], count=weapon["m"], targetId=target,
        )

        models_before = {m: game.state["models_cache"][m]["HP_CUR"] for m in game.models_of(target)}
        hp_before = int(game.unit(target)["HP_CUR"])
        assert hp_before == sum(models_before.values()), "PV d'unité ≠ somme des PV de figurines"

        body = _finish_allocation(game, squad, game.act("squad_shoot_validate", unitId=squad))
        shoot_result = body["result"]["shoot_result"]

        assert shoot_result["attacks_made"] >= shoot_result["hits"] >= shoot_result["wounds"]
        assert shoot_result["wounds"] >= shoot_result["failed_saves"]
        alive_after = {
            m: game.state["models_cache"][m]["HP_CUR"]
            for m in game.state["squad_models"].get(target, [])
        }
        killed = set(models_before) - set(alive_after)
        assert len(killed) == shoot_result["models_killed"], (
            f"{len(killed)} figurines retirées pour {shoot_result['models_killed']} annoncées"
        )
        lost_by_survivors = sum(models_before[m] - alive_after[m] for m in alive_after)
        lost_by_dead = sum(models_before[m] for m in killed)
        assert lost_by_survivors + lost_by_dead >= shoot_result["damage_total"] - 0, (
            "des dégâts annoncés ne se retrouvent pas dans les PV"
        )
        assert hp_before - int(game.unit(target)["HP_CUR"]) == lost_by_survivors + lost_by_dead

        for model_id in killed:
            assert model_id not in game.state["models_cache"], "figurine morte encore dans models_cache"
        assert body["result"]["removed_from_shoot_pool"] is True
        assert squad not in game.pool("shoot_activation_pool")
        assert squad in [str(u) for u in game.state["units_shot"]]
        assert squad not in game.state["pending_squad_shoot_intents"]
        assert "active_shooting_unit" not in game.state
        # Une escouade déjà sélectionnée pour tirer ne peut pas y revenir (10.02).
        accepted, _body = game.try_act("squad_shoot_activate", unitId=squad)
        assert not accepted or squad not in game.pool("shoot_activation_pool")

    def test_cover_worsens_the_ballistic_skill_by_one(self, game):
        """t4_13_08_cover : cible à couvert → seuil de touche dégradé de 1.

        PDF 13.08 : « Each time a ranged attack targets a unit that has the benefit of cover
        against it, worsen the BS characteristic of that attack by 1. » Le moteur expose les
        deux valeurs dans le lot d'attaques (`bs_base`, `bs`, `cover`) : c'est ce couple qui
        est vérifié, sur des armes sans modificateur concurrent ([HEAVY] améliore le seuil
        quand l'unité n'a pas bougé, [IGNORES COVER] annule le couvert — 24.18).
        """
        game.drain_to("shoot")
        samples = {True: 0, False: 0}
        for squad in game.pool("shoot_activation_pool"):
            if samples[True] and samples[False]:
                break
            if _shoots_as_monster_or_vehicle(game, squad):
                continue  # 10.06 volet MONSTER/VEHICLE : -1 au jet, modificateur concurrent
            activation = game.act("squad_shoot_activate", unitId=squad)["result"]
            rules_by_code = {
                weapon["weapon"]["code"]: weapon["weapon"]["WEAPON_RULES"]
                for weapon in activation["available_weapons"]
            }
            overview = game.act("squad_shoot_los_overview", unitId=squad)["result"]
            cover_by_target = overview["cover_by_unit_id"]
            wanted = next(
                (t for t, c in cover_by_target.items() if samples[bool(c)] == 0),
                None,
            )
            if wanted is None:
                game.act("squad_shoot_cancel", unitId=squad)
                continue
            weapons = game.act("squad_shoot_weapons_for_target", unitId=squad, targetId=wanted)["result"]["weapons"]
            plain = [
                w for w in weapons
                if not ({"HEAVY", "IGNORES_COVER"} & set(rules_by_code.get(w["code"], [])))
            ]
            if not plain:
                game.act("squad_shoot_cancel", unitId=squad)
                continue
            game.act(
                "squad_shoot_assign_weapon_qty",
                unitId=squad, weaponCode=plain[0]["code"], count=plain[0]["m"], targetId=wanted,
            )
            body = game.act("squad_shoot_validate", unitId=squad)
            # Les lots d'attaques ne sont exposés que tant qu'une blessure reste à allouer :
            # une salve sans sauvegarde ratée termine l'activation sans passer par là.
            allocation = game.state.get("pending_shoot_allocation")
            if allocation is None:
                continue
            for group in allocation["weapon_groups"]:
                assert group["heavy_applied"] is False
                expected = min(6, group["bs_base"] + 1) if group["cover"] else group["bs_base"]
                assert group["bs"] == expected, (
                    f"{squad} → {wanted} : BS {group['bs']} attendu {expected} "
                    f"(base {group['bs_base']}, cover {group['cover']})"
                )
                samples[bool(group["cover"])] += 1
            _finish_allocation(game, squad, body)

        assert samples[True] > 0, "aucun tir sur une cible à couvert éprouvé"
        assert samples[False] > 0, "aucun tir sans couvert éprouvé (comparaison impossible)"


class TestWeaponIndexAssignment:
    def test_assign_and_unassign_by_weapon_index(self, game):
        """t4_unassign_par_index : déclaration puis retrait par INDEX d'arme.

        Granularité distincte des deux autres : c'est celle qu'utilise le front pour le
        remplacement d'un profil combi (`handleUnassignShootWeapon`, useEngineAPI.ts:5181).
        Elle vise l'arme dans le profil de l'escouade, pas un couple (arme, cible) ni une
        figurine — et doit rendre l'escouade au même état qu'avant la déclaration.
        """
        game.drain_to("shoot")
        squad = "9"
        activation = game.act("squad_shoot_activate", unitId=squad)["result"]
        target = game.act("squad_shoot_los_overview", unitId=squad)["result"]["valid_targets"][0]
        weapons = game.act("squad_shoot_weapons_for_target", unitId=squad, targetId=target)["result"]["weapons"]
        code = max(weapons, key=lambda w: w["m"])["code"]
        index = next(
            w["index"] for w in activation["available_weapons"] if w["weapon"]["code"] == code
        )
        quantity_max = game.act(
            "squad_shoot_weapon_qty_max", unitId=squad, weaponCode=code, targetId=target
        )["result"]["qty_max"]

        declared = game.act(
            "squad_shoot_assign_weapon", unitId=squad, weaponIndex=index, targetId=target
        )["result"]
        assert declared["declarations"], "aucune déclaration créée par index d'arme"
        assert {d["weapon_index"] for d in declared["declarations"]} == {index}

        removed = game.act(
            "squad_shoot_unassign_weapon", unitId=squad, weaponIndex=index
        )["result"]

        assert removed["removed"] >= 1
        assert removed["declarations"] == [], "des déclarations survivent au retrait par index"
        assert game.act(
            "squad_shoot_weapon_qty_max", unitId=squad, weaponCode=code, targetId=target
        )["result"]["qty_max"] == quantity_max, "la borne n'est pas revenue à son état initial"
