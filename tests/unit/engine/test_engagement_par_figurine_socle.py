"""Pile-in / consolidation / charge : l'ENGAGEMENT d'une figurine se mesure à SON socle.

LE DÉFAUT. Le chantier précédent (`test_pile_in_empreinte_par_figurine`) a fait empreinter chaque
figurine à son propre socle — mais l'empreinte ainsi calculée était ensuite passée à une entrée
d'engagement COPIÉE de la ligne `units_cache` de l'ESCOUADE. Or les trois chemins de mesure de
`entries_in_engagement_zone` relisent `BASE_SHAPE`/`BASE_SIZE`/`MODEL_HEIGHT` SUR L'ENTRÉE et
ignorent l'empreinte qu'on y pose (`socle_from_cache_entry`, `_class_footprint`). Un personnage
attaché — socle plus large que la troupe qu'il rejoint — était donc jugé engagé, ou non, au gabarit
du bloc : 0 divergence de verdict alors que son empreinte annoncée passait de 19 à 43 hexes.

CE QUI VERROUILLE ICI. Le scénario `scenario_attached_unit_test` porte un Captain (socle 8) dans
une escouade d'Intercessors (socle 6). Autour de l'ennemi existent 78 cases où le verdict DIFFÈRE
selon le socle utilisé — c'est cette bande que les tests occupent. Un test posé ailleurs serait
vert avec le défaut en place.

Règles citées : Documentation/40k_rules/03 Moving (03.04 zone d'engagement), /12 Fights phase
(12.03 « Your unit must be engaged »), /19 Attached units.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Dict, List, Tuple

import pytest

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
SCENARIO = os.path.join(
    PROJECT_ROOT, "config/board/44x60x5/scenario/scenario_attached_unit_test.json"
)


@pytest.fixture(scope="module")
def attached_env():
    from ai.training_utils import setup_imports
    from ai.unit_registry import UnitRegistry
    from services.api_server import get_agents_from_scenario

    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()
    if not os.path.exists(SCENARIO):
        raise FileNotFoundError(SCENARIO)
    env = W40KEngine(
        rewards_config="default",
        training_config_name="x1",
        controlled_agent=sorted(get_agents_from_scenario(SCENARIO, ur))[0],
        scenario_file=SCENARIO,
        unit_registry=ur,
        quiet=True,
        gym_training_mode=True,
    )
    env.reset(seed=1)
    return env


@pytest.fixture
def cas(attached_env) -> Dict[str, Any]:
    """Le personnage attaché, son escouade, l'ennemi, et DEUX cases de référence.

    - ``case_discriminante`` : le socle de la FIGURINE y engage l'ennemi, celui de l'ESCOUADE non.
      C'est la seule position qui prouve quoi que ce soit ; sans elle le test serait vacant.
    - ``case_hors_portee`` : aucun des deux socles n'y engage. Contre-épreuve — sans elle, une
      fonction qui répondrait « engagé » en toutes circonstances passerait le test principal.
    """
    from engine.phase_handlers.shared_utils import (
        _synth_model_entry, get_engagement_zone, require_key,
    )
    from engine.spatial_relations import unit_entries_within_engagement_zone

    gs = attached_env.game_state
    ubi = gs["unit_by_id"]
    attache = None
    for mid, model in gs["models_cache"].items():
        unit = ubi.get(str(model["squad_id"]))
        if unit is None:
            continue
        if str(model["BASE_SIZE"]) != str(unit.get("BASE_SIZE")):
            attache = (str(mid), str(model["squad_id"]))
            break
    if attache is None:
        raise AssertionError(
            "scénario sans personnage attaché à socle divergent — fixture vacante"
        )
    mid, squad_id = attache
    model = gs["models_cache"][mid]
    troupe_id = next(
        str(m) for m in gs["squad_models"][squad_id]
        if str(m) != mid and str(m) in gs["models_cache"]
    )
    troupe = gs["models_cache"][troupe_id]
    enemy_id = next(
        str(u) for u, e in gs["units_cache"].items()
        if int(e["player"]) != int(model["player"])
    )
    enemy_entry = gs["units_cache"][enemy_id]
    ez = int(get_engagement_zone(gs))

    def _verdict(porteur: Dict[str, Any], col: int, row: int) -> bool:
        return unit_entries_within_engagement_zone(
            _synth_model_entry(gs, squad_id, porteur, col, row, level=0),
            enemy_entry, ez, memoise=False,
        )

    ec, er = int(enemy_entry["col"]), int(enemy_entry["row"])
    discriminante = None
    for dc in range(-20, 21):
        for dr in range(-20, 21):
            c, r = ec + dc, er + dr
            if c < 0 or r < 0:
                continue
            if _verdict(model, c, r) and not _verdict(troupe, c, r):
                discriminante = (c, r)
                break
        if discriminante is not None:
            break
    assert discriminante is not None, (
        "aucune case où les deux socles divergent : ce fichier ne peut rien verrouiller"
    )
    hors_portee = (ec + 30, er)
    assert not _verdict(model, *hors_portee) and not _verdict(troupe, *hors_portee), (
        "la case de contre-épreuve est encore dans la zone d'engagement — elle ne contredit rien"
    )
    # Contre-épreuve du VOILE VERT : hors zone d'engagement mais assez près pour que le pile-in
    # ait des cibles (12.03 « within 5" »). Sur `hors_portee`, l'absence de cible viderait le voile
    # sans rien prouver.
    portee_cible = int(
        require_key(require_key(gs, "config"), "game_rules")["pile_in_target_range"]
    ) * int(gs["inches_to_subhex"])
    hors_ez_mais_proche = None
    for d in range(1, portee_cible):
        c = ec + d
        if not _verdict(model, c, er) and not _verdict(troupe, c, er):
            hors_ez_mais_proche = (c, er)
            break
    assert hors_ez_mais_proche is not None, (
        "aucune case hors zone d'engagement à portée de cible : la contre-épreuve du voile serait "
        "vide de cibles, donc vacante"
    )
    return {
        "gs": gs, "mid": mid, "squad_id": squad_id, "troupe_id": troupe_id,
        "enemy_id": enemy_id, "unit": ubi[squad_id],
        "case_discriminante": discriminante, "case_hors_portee": hors_portee,
        "case_hors_ez_mais_proche": hors_ez_mais_proche,
        "base_figurine": model["BASE_SIZE"], "base_escouade": ubi[squad_id]["BASE_SIZE"],
    }


@contextmanager
def _figurine_posee(gs: Dict[str, Any], mid: str, case: Tuple[int, int]):
    """Pose RÉELLEMENT ``mid`` sur ``case``, puis remet tout en place.

    Le voile vert dépend des cibles de pile-in, dérivées de la position COURANTE de l'escouade :
    un plan provisoire ne les change pas, et la mise en scène doit donc muter l'état. Le
    `game_state` est partagé par le module — le laisser muté ferait dépendre les tests suivants
    de l'ordre d'exécution.
    """
    from engine.phase_handlers.shared_utils import place_model_at_effective_level

    avant = gs["models_cache"][mid]
    origine = (int(avant["col"]), int(avant["row"]), int(avant["level"]))
    place_model_at_effective_level(gs, mid, int(case[0]), int(case[1]), 0)
    try:
        yield
    finally:
        place_model_at_effective_level(gs, mid, *origine)


def _plan(cas: Dict[str, Any], case: Tuple[int, int]) -> List[Tuple[str, int, int, int]]:
    """Plan couvrant TOUTES les figurines : le personnage sur ``case``, les autres à l'origine."""
    mc = cas["gs"]["models_cache"]
    out: List[Tuple[str, int, int, int]] = []
    for m in cas["gs"]["squad_models"][cas["squad_id"]]:
        m = str(m)
        if m not in mc:
            continue
        if m == cas["mid"]:
            out.append((m, int(case[0]), int(case[1]), 0))
        else:
            out.append((m, int(mc[m]["col"]), int(mc[m]["row"]), int(mc[m]["level"])))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Niveau UNITÉ — 12.03 « Your unit must be engaged »
# ─────────────────────────────────────────────────────────────────────────────

def test_l_unite_est_engagee_par_le_socle_de_son_personnage_attache(cas):
    """VERROU : mesurée au socle du bloc, cette escouade est déclarée NON engagée.

    Le personnage est posé sur la bande où son socle atteint l'ennemi et où celui de la troupe ne
    l'atteint pas ; les autres figurines restent au loin. `unit_engaged` ne peut donc être vrai que
    si l'entrée d'engagement porte le socle de la FIGURINE.
    """
    from engine.phase_handlers import fight_handlers as fh

    prev = fh._fight_pile_in_preview_plan(
        cas["gs"], cas["squad_id"], _plan(cas, cas["case_discriminante"]), [cas["enemy_id"]]
    )

    assert prev["unit_engaged"] is True, (
        f"personnage attaché (socle {cas['base_figurine']}) posé en {cas['case_discriminante']} : "
        f"son socle atteint l'ennemi, celui de l'escouade ({cas['base_escouade']}) non. "
        "unit_engaged=False ⇒ l'unité est mesurée au gabarit du bloc"
    )


def test_l_unite_hors_portee_reste_non_engagee(cas):
    """Contre-épreuve : sans elle, un `unit_engaged` constamment vrai passerait le test ci-dessus."""
    from engine.phase_handlers import fight_handlers as fh

    prev = fh._fight_pile_in_preview_plan(
        cas["gs"], cas["squad_id"], _plan(cas, cas["case_hors_portee"]), [cas["enemy_id"]]
    )

    assert prev["unit_engaged"] is False, (
        "aucune figurine n'est à portée d'engagement et l'unité est pourtant déclarée engagée"
    )


def test_les_entrees_synthetiques_d_unite_portent_un_socle_chacune(cas):
    """L'entrée-cache ne porte QU'UN socle : une escouade à bases mixtes en exige plusieurs."""
    from engine.phase_handlers import fight_handlers as fh

    entrees = fh._fight_synth_cache_entries_at_footprint(
        cas["unit"], cas["gs"], *cas["case_discriminante"],
        model_placements={
            mid: (c, r, lv) for mid, c, r, lv in _plan(cas, cas["case_discriminante"])
        },
    )

    socles = sorted(str(e["BASE_SIZE"]) for e in entrees)
    assert socles == sorted({str(cas["base_figurine"]), str(cas["base_escouade"])}), (
        f"socles décrits : {socles} ; attendu un par socle distinct de l'escouade. Une seule "
        "entrée ⇒ toutes les figurines sont mesurées au même gabarit"
    )


def test_une_escouade_homogene_ne_produit_qu_une_entree(cas):
    """Coût : le partitionnement par socle ne doit rien ajouter au cas courant."""
    from engine.phase_handlers import fight_handlers as fh

    gs = cas["gs"]
    unit = gs["unit_by_id"][cas["enemy_id"]]
    entrees = fh._fight_synth_cache_entries_at_footprint(
        unit, gs, int(unit["col"]), int(unit["row"])
    )

    assert len(entrees) == 1, (
        f"escouade homogène décrite par {len(entrees)} entrées — le partitionnement se déclenche "
        "là où il n'y a rien à partitionner"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Niveau FIGURINE — voile vert du pile-in (« en mesure de frapper »)
# ─────────────────────────────────────────────────────────────────────────────

def test_le_voile_vert_suit_le_socle_de_la_figurine(cas):
    """Le voile vert marque les figurines à portée d'engagement : mesure PAR FIGURINE."""
    from engine.phase_handlers import fight_handlers as fh

    with _figurine_posee(cas["gs"], cas["mid"], cas["case_discriminante"]):
        etat = fh._fight_pile_in_model_plan_state(
            cas["gs"], cas["unit"], selected_model=cas["mid"], view_level=0,
        )

    assert cas["mid"] in etat["engaged_models"], (
        f"figurines en vert : {etat['engaged_models']} ; le personnage attaché ({cas['mid']}) "
        "manque alors que SON socle atteint l'ennemi — le voile est mesuré au socle du bloc"
    )


def test_le_voile_vert_ne_marque_pas_une_figurine_hors_portee(cas):
    """Contre-épreuve du voile : un « tout le monde en vert » passerait le test précédent.

    La figurine reste à portée de CIBLE (5\") — sinon le voile serait vide faute de cible, et
    l'assertion passerait sans rien mesurer.
    """
    from engine.phase_handlers import fight_handlers as fh

    with _figurine_posee(cas["gs"], cas["mid"], cas["case_hors_ez_mais_proche"]):
        etat = fh._fight_pile_in_model_plan_state(
            cas["gs"], cas["unit"], selected_model=cas["mid"], view_level=0,
        )
        assert fh._fight_v11_pile_in_targets(cas["gs"], cas["unit"]), (
            "prémisse : le pile-in doit avoir au moins une cible, sinon le voile est vide "
            "quelle que soit la mesure d'engagement"
        )

    assert cas["mid"] not in etat["engaged_models"], (
        "une figurine hors de toute zone d'engagement est marquée « en mesure de frapper »"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Jumeau CHARGE — la classification du champ, par groupe de socle
# ─────────────────────────────────────────────────────────────────────────────

def test_le_champ_de_charge_classe_chaque_groupe_a_son_socle(cas):
    """`_compute_plan_context` classe ses cellules PAR GROUPE DE SOCLE (`region_by_base`).

    L'empreinte candidate y venait bien de la figurine représentative du groupe, mais l'entrée
    d'engagement qui tranche `engaged` était bâtie UNE fois sur la ligne d'escouade : le groupe du
    personnage attaché était donc classé au gabarit de la troupe. C'est le même défaut que côté
    fight, sur un site qui n'utilise pas le même constructeur — d'où un verrou distinct.
    """
    from engine.phase_handlers import charge_handlers as ch
    from engine.phase_handlers.shared_utils import _synth_model_entry, get_engagement_zone
    from engine.spatial_relations import unit_entries_within_engagement_zone

    gs = cas["gs"]
    ec, er = int(gs["units_cache"][cas["enemy_id"]]["col"]), int(gs["units_cache"][cas["enemy_id"]]["row"])
    ez = int(get_engagement_zone(gs))
    enemy_entry = gs["units_cache"][cas["enemy_id"]]
    # Les deux figurines à ~7" de l'ennemi, jet de 6" : le champ franchit la limite d'engagement,
    # donc il contient des cellules des DEUX côtés du verdict. Trop près, tout est « engagé » et
    # la classification ne discrimine plus rien (constaté en calibrant ce test).
    with _figurine_posee(gs, cas["troupe_id"], (ec + 36, er)), \
            _figurine_posee(gs, cas["mid"], (ec + 34, er - 4)):
        ctx = ch._compute_plan_context(
            gs, cas["unit"], cas["squad_id"], {}, [cas["enemy_id"]], 30, False, False, view_level=0,
        )
        region = [
            reg for cle, reg in ctx["region_by_base"].items()
            if str(cle[1]) == str(cas["base_figurine"])
        ]
        assert len(region) == 1, (
            f"groupes de socle classés : {list(ctx['region_by_base'])} ; attendu un groupe pour le "
            f"socle {cas['base_figurine']} du personnage attaché"
        )
        modele = gs["models_cache"][cas["mid"]]
        troupe = gs["models_cache"][cas["troupe_id"]]

        def _verdict(porteur, cell):
            return unit_entries_within_engagement_zone(
                _synth_model_entry(gs, cas["squad_id"], porteur, cell[0], cell[1], level=0),
                enemy_entry, ez, memoise=False,
            )

        divergentes = [
            cell for cell in region[0]
            if _verdict(modele, cell) and not _verdict(troupe, cell)
        ]
        # L'ennemi est un socle rond mono-figurine et la métrique est euclidienne : la
        # classification passe donc par la primitive d'engagement pour TOUTES ces cellules, et son
        # verdict doit coïncider exactement avec elle, dans les deux sens.
        desaccords = [
            cell for cell in region[0]
            if bool(region[0][cell]["engaged"]) != _verdict(modele, cell)
        ]

    assert divergentes, (
        "aucune cellule du champ ne discrimine les deux socles — le test ne verrouille rien"
    )
    assert not desaccords, (
        f"{len(desaccords)} cellules sur {len(region[0])} sont classées autrement que ne le dit la "
        f"mesure d'engagement au socle du personnage ({cas['base_figurine']}). Le champ mesure au "
        f"socle de l'escouade ({cas['base_escouade']}) — et une empreinte de figurine posée sur une "
        "entrée d'escouade la fait en plus passer pour multi-figurine, donc basculer sur la branche "
        f"empreinte, plus permissive. Ex. {sorted(desaccords)[:3]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# La HAUTEUR est l'autre moitié de 03.04 (2\" horizontal ET 5\" vertical)
# ─────────────────────────────────────────────────────────────────────────────

def test_la_figurine_porte_sa_propre_hauteur(cas):
    """`models_cache` doit porter MODEL_HEIGHT, comme il porte déjà le socle.

    Sans elle, l'entrée d'engagement par-figurine n'a d'autre source que la ligne d'escouade : le
    socle serait par figurine et l'intervalle vertical au bloc — une moitié de règle chacun.
    """
    mc = cas["gs"]["models_cache"]
    manquants = [m for m in mc if "MODEL_HEIGHT" not in mc[m]]

    assert not manquants, (
        f"figurines sans MODEL_HEIGHT : {manquants} — l'engagement 3D retombe sur l'escouade"
    )


def test_la_hauteur_se_lit_sur_la_figurine_puis_sur_l_escouade(cas):
    """`_model_height_of` — source unique de l'héritage escouade→figurine (engagement 3D, LoS, 13.06).

    Quatre comportements, parce que les quatre sont utilisés : la figurine prime, l'escouade prend
    le relais quand la figurine ne porte rien (escouade homogène, états de test), l'absence des
    DEUX lève — une hauteur inventée serait une mesure fausse et silencieuse —, et une entrée qui
    n'est PAS une figurine est refusée : y passer une ligne d'escouade ramènerait la hauteur du
    BLOC, le défaut que ce chantier a corrigé sur onze sites de clairance.
    """
    from shared.data_validation import ConfigurationError

    from engine.phase_handlers.shared_utils import _model_height_of

    figurine = {"squad_id": "1", "MODEL_HEIGHT": 4.0}
    escouade = {"MODEL_HEIGHT": 2.5}

    assert _model_height_of(figurine, escouade) == pytest.approx(4.0)
    assert _model_height_of({"squad_id": "1"}, escouade) == pytest.approx(2.5)
    with pytest.raises(ConfigurationError):
        _model_height_of({"squad_id": "1"}, {})
    with pytest.raises(ValueError, match="squad_id"):
        _model_height_of(escouade, escouade)


def test_l_entree_d_engagement_prend_la_hauteur_de_la_figurine(cas):
    """La hauteur suit la FIGURINE, pas l'escouade (§03.04, borne haute de l'intervalle vertical).

    Le scénario ne porte pas deux hauteurs différentes : on en fabrique une, sinon le test
    passerait sans discriminer — c'est exactement le piège du chantier précédent.
    """
    from engine.phase_handlers.shared_utils import _synth_model_entry

    gs = cas["gs"]
    hauteur_escouade = float(gs["units_cache"][cas["squad_id"]]["MODEL_HEIGHT"])
    plus_haut = dict(gs["models_cache"][cas["mid"]])
    plus_haut["MODEL_HEIGHT"] = hauteur_escouade + 3.0

    synth = _synth_model_entry(gs, cas["squad_id"], plus_haut, 20, 20, level=0)

    assert synth["MODEL_HEIGHT"] == pytest.approx(hauteur_escouade + 3.0), (
        f"hauteur retenue {synth['MODEL_HEIGHT']} = celle de l'escouade ({hauteur_escouade}) : "
        "un personnage attaché plus haut est mesuré sur l'intervalle vertical de la troupe"
    )
