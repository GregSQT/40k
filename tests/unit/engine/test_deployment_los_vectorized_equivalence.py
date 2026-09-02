"""Le tracé VECTORISÉ de la LoS de déploiement rend-il EXACTEMENT ce que rend la règle scalaire ?

C'EST LE TEST QUI REND L'OPTIMISATION ACCEPTABLE (V11 §0.64, suite). §0.64 vient d'aligner
l'exposition de déploiement sur `compute_unit_los`, la règle du moteur, et a payé cet alignement
en temps : la moitié de la phase de déploiement partait dans 146 781 tracés scalaires. Le tracé
est désormais vectorisé (`shooting_handlers.batch_ground_hex_can_see`).

Une optimisation qui change ne serait-ce qu'UNE exposition n'est pas un compromis, c'est un
échec : le bloc « candidats de déploiement » de l'observation (§0.40) vient de changer, ce qui
impose déjà un ré-entraînement `--new` ; un second changement de valeurs en imposerait un autre.

Écrire un second chemin de LoS est par ailleurs EXACTEMENT la faute que §0.64 a réparée — deux
implémentations qui divergent en silence. La contrepartie est ici : les deux chemins sont
comparés HEXE PAR HEXE sur la TOTALITÉ du pool (16 104 hexes), sur DEUX terrains, depuis des
sources choisies pour couvrir les cas qui font diverger (dans une area obscurante, contre un
mur, aux coins du pool). Si un jour le modèle de LoS évolue d'un seul côté, ces tests virent au
rouge — c'est leur seule raison d'être.
"""

import json
import os

import numpy as np
import pytest

from engine.phase_handlers.shooting_handlers import (
    _get_obscuring_area_sets,
    _get_wall_set,
    compute_unit_los,
    ground_los_blocking_signature,
)

#: Second TERRAIN (pas seulement un second roster) : le tracé ne dépend que des murs et des areas
#: obscurantes, donc deux scénarios sur `terrain-mc1` ne prouveraient qu'une fois la même chose.
SECOND_TERRAIN_REF = "terrain-mc2.json"


def _scalar_can_see(game_state, source, hexes):
    """La RÈGLE, une paire à la fois : `compute_unit_los` sur des dicts coordonnées-seules.

    C'est littéralement ce que faisait `deployment_los` avant la vectorisation (via
    `has_line_of_sight`), et ce que fait encore tout le reste du moteur.
    """
    src = {"col": int(source[0]), "row": int(source[1])}
    return np.array(
        [
            compute_unit_los(game_state, src, {"col": int(c), "row": int(r)})["can_see"]
            for c, r in hexes
        ],
        dtype=bool,
    )


def _sources_a_couvrir(game_state, hexes):
    """Sources CONSTRUITES, pas espérées : chaque cas qui peut faire diverger les deux tracés.

    Un test qui se contenterait des unités posées ne verrait jamais une source DANS une area
    obscurante — donc jamais l'exclusion 13.10 côté source, qui est justement la partie de la
    règle que le tracé 2D historique ignorait.
    """
    sources = []
    etiquettes = []
    for unit in game_state["units"]:
        if int(unit["col"]) >= 0 and int(unit["row"]) >= 0:
            sources.append((int(unit["col"]), int(unit["row"])))
            etiquettes.append(f"unite {unit['id']}")

    pool = set(hexes)
    for area_id, area_hexes in _get_obscuring_area_sets(game_state)[:3]:
        dans_le_pool = sorted(h for h in area_hexes if h in pool) or sorted(area_hexes)
        sources.append(dans_le_pool[0])
        etiquettes.append(f"dans l'area obscurante {area_id}")

    murs = _get_wall_set(game_state)
    voisins_de_mur = sorted(
        h for h in hexes if (h[0] + 1, h[1]) in murs or (h[0] - 1, h[1]) in murs
    )
    if voisins_de_mur:
        sources.append(voisins_de_mur[0])
        etiquettes.append("colle a un mur")

    cols = [h[0] for h in hexes]
    rows = [h[1] for h in hexes]
    sources.append((min(cols), min(rows)))
    etiquettes.append("coin bas du pool")
    sources.append((max(cols), max(rows)))
    etiquettes.append("coin haut du pool")
    return list(zip(sources, etiquettes))


def _compare_sur_tout_le_pool(engine, contexte):
    game_state = engine.game_state
    decoder = engine.action_decoder
    deployer = int(game_state["deployment_state"]["current_deployer"])
    hexes = decoder.deployment_scoring_hexes(game_state, deployer)
    assert len(hexes) > 1000, f"{contexte} : pool de {len(hexes)} hexes, test creux"
    arr = np.array(hexes, dtype=np.int64)

    couples = _sources_a_couvrir(game_state, hexes)
    obscurantes = [e for _s, e in couples if e.startswith("dans l'area")]
    assert obscurantes, (
        f"{contexte} : aucune source dans une area obscurante — l'exclusion 13.10 cote source "
        f"n'est pas observee, le test afficherait « tout va bien » sans la regarder"
    )

    vus_total = 0
    for source, etiquette in couples:
        attendu = _scalar_can_see(game_state, source, hexes)
        obtenu = decoder.deployment_los(game_state, source, arr)
        divergents = np.flatnonzero(attendu != obtenu)
        assert not len(divergents), (
            f"{contexte}, source {source} ({etiquette}) : {len(divergents)} hexes divergent "
            f"entre le trace scalaire et le trace vectorise, ex. "
            f"{[hexes[i] for i in divergents[:5]]}"
        )
        vus_total += int(attendu.sum())

    # CONTRE LE VERT VACANT : deux tracés qui ne voient JAMAIS rien seraient d'accord partout.
    assert vus_total > 0, (
        f"{contexte} : aucune des sources ne voit un seul hexe — la comparaison ne compare rien"
    )


def test_le_vectorise_egale_la_regle_scalaire_sur_tout_le_pool(board_x5, make_active_deployment_engine):
    """Terrain de production (`terrain-mc1`), en cours de déploiement : égalité hexe par hexe."""
    engine = make_active_deployment_engine(seed=1)
    for _ in range(4):
        if engine.game_state["phase"] != "deployment":
            break
        mask = engine.get_action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        if not legal:
            break
        engine.step(legal[0])
    assert engine.game_state["phase"] == "deployment"
    _compare_sur_tout_le_pool(engine, "terrain-mc1, 4 poses jouees")


def test_le_vectorise_egale_la_regle_scalaire_sur_un_second_terrain(board_x5, tmp_path):
    """Second TERRAIN : d'autres murs, d'autres areas obscurantes, mêmes réponses attendues."""
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine
    from tests.unit.engine._config_helpers import ACTIVE_DEPLOYMENT_SCENARIO

    scenario = json.loads(open(ACTIVE_DEPLOYMENT_SCENARIO, encoding="utf-8").read())
    assert scenario["terrain_ref"] != SECOND_TERRAIN_REF, (
        "le second terrain est celui du scenario de reference : le test ne varierait rien"
    )
    scenario["terrain_ref"] = SECOND_TERRAIN_REF
    # L'arborescence `agents/<agent>/scenarios/...` n'est pas décorative : le chargeur en déduit
    # la clé d'agent (`_load_units_from_roster_refs`) et lève si elle manque.
    chemin = tmp_path / "agents" / "ArmageddonAgent_x1" / "scenarios" / "holdout_regular"
    chemin.mkdir(parents=True)
    fichier = chemin / "scenario_second_terrain.json"
    fichier.write_text(json.dumps(scenario), encoding="utf-8")

    engine = W40KEngine(
        rewards_config="ArmageddonAgent_x1",
        training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent_x1",
        scenario_file=str(fichier),
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
    )
    engine.reset(seed=1)
    assert engine.game_state["phase"] == "deployment"
    murs = len(_get_wall_set(engine.game_state))
    assert murs > 0, "second terrain sans mur : rien ne peut bloquer, la comparaison est creuse"
    _compare_sur_tout_le_pool(engine, f"{SECOND_TERRAIN_REF} ({murs} murs)")


def test_le_trace_hex_ne_produit_jamais_de_cellule_en_double(board_x5, make_active_deployment_engine):
    """L'HYPOTHÈSE sur laquelle repose le jumeau vectorisé, vérifiée au lieu d'être supposée.

    Le générateur scalaire `hex_line_iter` déduplique ses cellules (`seen`) ; le jumeau
    vectorisé, lui, ne le peut pas — il traite les rangs `i` en parallèle. L'équivalence tient
    parce que la i-ème cellule d'un cube-lerp est à distance cube `i` de la source, donc les
    `n+1` cellules sont deux à deux distinctes et la déduplication ne retire jamais rien.
    """
    from engine.hex_utils import hex_line, offset_to_cube

    engine = make_active_deployment_engine(seed=1)
    game_state = engine.game_state
    decoder = engine.action_decoder
    deployer = int(game_state["deployment_state"]["current_deployer"])
    hexes = decoder.deployment_scoring_hexes(game_state, deployer)
    # Un échantillon LARGE et déterministe (un hexe sur 37) : ni graine aléatoire, ni ordre
    # d'exécution — la situation observée est construite.
    cibles = hexes[::37]
    assert len(cibles) > 100, f"echantillon de {len(cibles)} paires : trop maigre"

    sources = [hexes[0], hexes[len(hexes) // 2], hexes[-1]]
    verifiees = 0
    for src in sources:
        x1, y1, z1 = offset_to_cube(int(src[0]), int(src[1]))
        for tgt in cibles:
            x2, y2, z2 = offset_to_cube(int(tgt[0]), int(tgt[1]))
            n = max(abs(x1 - x2), abs(y1 - y2), abs(z1 - z2))
            ligne = hex_line(int(src[0]), int(src[1]), int(tgt[0]), int(tgt[1]))
            assert len(ligne) == len(set(ligne)), f"doublon dans la ligne {src} -> {tgt}"
            assert len(ligne) == n + 1, (
                f"ligne {src} -> {tgt} : {len(ligne)} cellules pour une distance {n} — la "
                f"deduplication a retire une cellule, le jumeau vectorise en testerait une de plus"
            )
            verifiees += 1
    assert verifiees > 300, f"{verifiees} paires verifiees : test creux"


def test_deux_terrains_aux_memes_murs_ne_partagent_pas_le_cache_potentiel(
    make_active_deployment_engine,
):
    """La clé du cache des expositions POTENTIELLES doit porter l'obscuring, pas que les murs.

    Trouvé par `/code-review` sur la livraison §0.65. La clé (mémoire ET fichier `.cache/`) ne
    retenait que les MURS — vrai du tracé 2D d'avant §0.64, faux depuis que `deployment_los`
    applique 13.10. Deux terrains aux mêmes murs et aux areas obscurantes différentes se
    partageaient donc le fichier : le second relisait, en silence et pour toujours, les
    expositions du premier.

    Aucune version de modèle ne peut rattraper ce défaut : le modèle n'a pas changé, c'est la
    clé qui ne décrivait pas ce que le modèle lit.

    📌 Aucun terrain du dépôt ne déclenche le cas aujourd'hui : les fichiers disponibles
    partagent le même cache correctement. C'est bien pour ça que le test CONSTRUIT son cas au
    lieu de l'espérer d'un fichier de configuration.

    Le test CONSTRUIT la situation : mêmes murs, une area obscurante déplacée.
    """
    engine = make_active_deployment_engine(seed=1)
    game_state = engine.game_state
    decoder = engine.action_decoder
    deployer = int(game_state["deployment_state"]["current_deployer"])
    refs = decoder._build_enemy_los_reference_hexes(
        decoder._get_enemy_deployment_pool_hexes(game_state, deployer)
    )

    def _cle_et_chemin():
        signature = ground_los_blocking_signature(game_state)
        chemin = decoder._get_deployment_potential_los_cache_file_path(
            (deployer, tuple(refs), signature)
        )
        return signature, chemin

    murs_avant = {tuple(map(int, h)) for h in game_state["wall_hexes"]}
    signature_avant, chemin_avant = _cle_et_chemin()

    obscurantes = [a for a in game_state["terrain_areas"] if a.get("obscuring")]
    assert obscurantes, "terrain sans area obscurante : le test ne construit pas sa situation"
    cible = obscurantes[0]
    cible["hexes"] = [[int(c) + 3, int(r) + 3] for c, r in cible["hexes"]]
    # Caches DÉRIVÉS du terrain : sans cette purge, le déplacement ne serait pas vu — et le
    # test observerait sa propre inertie au lieu de la clé.
    for cle in ("_obscuring_area_sets_cache", "_obscuring_hex_to_area_cache",
                "_los_blocking_grids_cache"):
        game_state.pop(cle, None)

    murs_apres = {tuple(map(int, h)) for h in game_state["wall_hexes"]}
    assert murs_apres == murs_avant, (
        "le test a bouge les murs : il ne prouverait plus que c'est l'OBSCURING qui discrimine"
    )
    signature_apres, chemin_apres = _cle_et_chemin()
    assert signature_apres != signature_avant, (
        "signature de terrain identique apres deplacement d'une area obscurante : deux "
        "terrains aux memes murs se partageraient le cache"
    )
    assert chemin_apres != chemin_avant, (
        f"meme fichier de cache disque pour deux obscurings differents : {chemin_avant}"
    )


def test_le_deploiement_n_alimente_plus_le_cache_de_paires(make_active_deployment_engine):
    """`hex_los_cache` ne doit plus être rempli par le déploiement (V11 §0.64, suite).

    Il mémorisait 146 781 paires QUE PERSONNE ne redemandait (mesuré : 146 776 consultations
    pour 146 781 calculs, soit zéro réutilisation) — et chaque déplacement d'unité devait
    ensuite reparcourir ces clés pour les invalider. Un retour au chemin par paire le
    remplirait de nouveau : c'est ce que ce test interdit.
    """
    engine = make_active_deployment_engine(seed=1)
    for _ in range(400):
        if engine.game_state["phase"] != "deployment":
            break
        mask = engine.get_action_mask()
        legal = [i for i, ok in enumerate(mask) if ok]
        if not legal:
            break
        engine.step(legal[0])

    counts = engine.action_decoder.deployment_cache_counts()
    assert counts["incremental"] > 0, f"deploiement non joue, test creux : {counts}"
    assert not engine.game_state.get("hex_los_cache"), (
        f"le deploiement a remis {len(engine.game_state['hex_los_cache'])} paires dans "
        f"hex_los_cache : le chemin par paire est revenu"
    )
