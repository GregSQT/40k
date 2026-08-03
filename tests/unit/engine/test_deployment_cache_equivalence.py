"""Le cache de scoring mis à jour INCRÉMENTALEMENT est-il égal à un cache reconstruit ?

C'EST LE TEST QUI REND LA CORRECTION SÛRE (V11 §0.46, suite). La mise à jour incrémentale a
été généralisée à N poses de delta parce que les joueurs déploient en ALTERNANCE : quand un
joueur revient, il a manqué sa propre pose et celle de l'adversaire. Auparavant elle exigeait
exactement une pose et rendait donc la main dans tous les cas réels — c'est-à-dire qu'elle
n'a jamais tourné en production, et qu'aucun test ne pouvait attester qu'elle était juste.

Plutôt que de raisonner cas par cas sur les mises à jour (retrait des hexes occupés, comptage
des alliés par colonne, recalcul des lignes de vue par ennemi apparu), on COMPARE : à chaque
pose, le cache vivant doit être égal, champ par champ, à ce qu'aurait produit une
reconstruction complète du même état. Une divergence, même d'une unité sur un seul hexe,
serait une observation faussée pour l'agent (§0.40).
"""

import pytest

#: `ally_deployed_hexes` et `enemy_deployed_units` sont construits par APPEND dans la mise à
#: jour incrémentale, et le premier alimente `nearest_ally` dans `_deployment_score_columns`,
#: donc directement l'observation. Les omettre laissait hors du verrou un ingrédient de score
#: que ce chemin fabrique lui-même.
_CHAMPS_COMPARES = (
    "los_exposure_by_hex",
    "potential_los_exposure_by_hex",
    "ally_col_counts",
    "ally_deployed_hexes",
    "enemy_deployed_units",
)


def _rebuild_reference(decoder, game_state, deployer):
    """Cache reconstruit de zéro pour l'état courant — la référence."""
    return decoder._build_deployment_scoring_cache(
        game_state, deployer, decoder.deployment_scoring_hexes(game_state, deployer)
    )


def _compare(vivant, reference, contexte):
    ecarts = []
    for champ in _CHAMPS_COMPARES:
        a, b = vivant[champ], reference[champ]
        if a != b:
            if isinstance(a, list) and isinstance(b, list):
                detail = f"{champ}: {len(a)} elements vivant contre {len(b)} reconstruits"
            elif isinstance(a, dict) and isinstance(b, dict):
                differents = [k for k in set(a) & set(b) if a[k] != b[k]]
                detail = (
                    f"{champ}: {len(set(a) ^ set(b))} cles divergentes, "
                    f"{len(differents)} valeurs differentes (ex: {differents[:3]})"
                )
            else:
                detail = f"{champ}: {len(set(a) ^ set(b))} elements divergents"
            ecarts.append(detail)
    assert not ecarts, f"{contexte} — le cache incremental diverge de la reconstruction :\n" + "\n".join(ecarts)


def test_incremental_matches_a_full_rebuild_at_every_deployment_step(make_active_deployment_engine):
    """À chaque pose, pour CHAQUE joueur, l'incrémental doit égaler la reconstruction."""
    eng = make_active_deployment_engine(seed=1)
    dec = eng.action_decoder
    assert eng.game_state["phase"] == "deployment"

    poses = 0
    for _ in range(400):
        gs = eng.game_state
        if gs["phase"] != "deployment":
            break
        deployer = int(gs["deployment_state"]["current_deployer"])
        # Consultation réelle : c'est elle qui déclenche l'incrémental ou la reconstruction.
        vivant = dec._get_or_build_deployment_scoring_cache(gs, deployer)
        _compare(vivant, _rebuild_reference(dec, gs, deployer), f"pose {poses}, joueur {deployer}")

        mask = eng.get_action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        if not legal:
            break
        eng.step(legal[0])
        poses += 1

    assert poses >= 4, f"trop peu de poses jouees ({poses}) : le test ne verrouille rien"


def test_the_incremental_path_is_actually_taken(make_active_deployment_engine):
    """CONTRE LE VERT VACANT : sans réutilisation, le test précédent ne compare que des rebuilds.

    C'est exactement l'état d'AVANT la correction — `incremental` valait 0 et la comparaison
    aurait été verte sans rien prouver.
    """
    eng = make_active_deployment_engine(seed=1)
    for _ in range(400):
        if eng.game_state["phase"] != "deployment":
            break
        mask = eng.get_action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        if not legal:
            break
        eng.step(legal[0])

    counts = eng.action_decoder.deployment_cache_counts()
    assert counts["incremental"] > 0, (
        f"le chemin incremental n'est jamais pris : {counts} — la correction ne sert a rien"
    )


def test_each_player_keeps_its_own_cache(make_active_deployment_engine):
    """Un cache par joueur : les pools diffèrent, un cache unique se ferait invalider à chaque pose."""
    from engine.action_decoder import ActionDecoder

    eng = make_active_deployment_engine(seed=1)
    for _ in range(6):
        if eng.game_state["phase"] != "deployment":
            break
        mask = eng.get_action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        if not legal:
            break
        eng.step(legal[0])

    caches = eng.game_state[ActionDecoder.DEPLOYMENT_SCORING_CACHE_KEY]
    assert set(caches) == {1, 2}, f"un cache par joueur attendu, obtenu : {sorted(caches)}"
    assert set(caches[1]["scoring_hexes"]) != set(caches[2]["scoring_hexes"]), (
        "les deux joueurs auraient le meme ensemble d'hexes : le pool n'est pas propre au joueur"
    )


def test_repositioning_an_already_deployed_unit_forces_a_rebuild(make_active_deployment_engine):
    """Un REPOSITIONNEMENT doit reconstruire, jamais être servi comme « cache à jour ».

    `deployment_recommit_plan` déplace une unité déjà posée : l'ensemble des ids ne change
    pas, seules les positions bougent. Un cache qui se déclare à jour sur ce seul critère sert
    des expositions calculées depuis l'ANCIENNE position — soit une observation fausse pour
    l'agent (§0.40), sur un handler atteignable par l'API.

    Ce cas était couvert par accident tant que l'incrémental exigeait exactement une pose ;
    généraliser à N ajouts a rouvert le trou, et ce test est ce qui le referme.
    """
    eng = make_active_deployment_engine(seed=1)
    dec = eng.action_decoder
    gs = eng.game_state

    for _ in range(3):
        if gs["phase"] != "deployment":
            break
        mask = eng.get_action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        if not legal:
            break
        eng.step(legal[0])

    deployer = int(gs["deployment_state"]["current_deployer"])
    dec._get_or_build_deployment_scoring_cache(gs, deployer)

    posees = [u for u in gs["units"] if int(u["col"]) >= 0 and int(u["row"]) >= 0]
    assert posees, "aucune unite posee : le test ne construit pas la situation qu'il observe"
    cible = posees[0]
    ancienne = (int(cible["col"]), int(cible["row"]))
    libres = [
        h for h in dec.deployment_scoring_hexes(gs, int(cible["player"]))
        if h != ancienne
    ]
    cible["col"], cible["row"] = libres[len(libres) // 2]

    cache = dec._get_or_build_deployment_scoring_cache(gs, deployer)
    reference = _rebuild_reference(dec, gs, deployer)
    _compare(cache, reference, "apres repositionnement d'une unite deja posee")


def test_valid_hexes_are_always_inside_the_scoring_superset(make_active_deployment_engine):
    """L'INVARIANT qui rend le filtrage à la lecture sûr : `valid_hexes ⊆ scoring_hexes`.

    S'il tombe, le consommateur lève un `KeyError` sur un hexe absent du cache — c'est déjà sa
    garde. Ce test le vérifie AVANT, pour toutes les unités et à chaque étape du déploiement,
    y compris multi-hex (socle > 1) où la validité passe par une érosion morphologique.
    """
    eng = make_active_deployment_engine(seed=1)
    dec = eng.action_decoder

    verifications = 0
    for _ in range(400):
        gs = eng.game_state
        if gs["phase"] != "deployment":
            break
        deployer = int(gs["deployment_state"]["current_deployer"])
        superset = set(dec.deployment_scoring_hexes(gs, deployer))
        for unit_id in gs["deployment_state"]["deployable_units"][deployer]:
            valides = set(dec._get_valid_deployment_hexes(gs, deployer, str(unit_id)))
            hors = valides - superset
            assert not hors, (
                f"unite {unit_id} (joueur {deployer}) : {len(hors)} hexes valides HORS du "
                f"sur-ensemble, ex. {sorted(hors)[:3]}"
            )
            verifications += 1
        mask = eng.get_action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        if not legal:
            break
        eng.step(legal[0])

    assert verifications >= 8, f"trop peu de verifications ({verifications}) : test creux"
