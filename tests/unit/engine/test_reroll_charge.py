"""`reroll_charge` (config/unit_rules.json) — détection de la règle, et purge du placeholder.

« When this unit makes a charge, it can reroll the charge roll. » Règle d'UNITÉ déclarée au
registre et implémentée par le moteur, mais que PLUS AUCUNE datasheet du jeu n'accorde :
« Unstoppable Valour » était un placeholder INVENTÉ, absent des 17 datasheets Armageddon, purgé
de 20 fichiers de roster par le chantier 05.

Le code n'est pas mort pour autant — de vraies datasheets 40K accordent cette relance, et le
jour où l'une entre au roster elle la déclarera.

Décision du « can » (documentée) : on relance sur le SEUL critère exact et disponible — le jet
n'atteint aucune destination légale au contact de la cible. Un dé ne se relance qu'une fois
(PDF 01 Core, Re-rolls).

PORTÉE EXACTE, et ce qu'elle ne couvre PAS :
  - les tests de DÉTECTION ci-dessous fabriquent un `game_state` à la main : ils vérifient
    `unit_can_reroll_charge`, pas ses appelants ;
  - les tests de PURGE lisent les vraies datasheets par `UnitRegistry` ;
  - le CÂBLAGE 19.04 (règle d'un character replié, vue au niveau escouade) est verrouillé par
    `test_attached_units_abilities_19_04.py`, mais sur `deep_strike` depuis le 2026-08-10 : ce
    fichier-là ne passe plus par `unit_can_reroll_charge`. Ce qui est verrouillé est le MÊME
    lecteur sous-jacent (`unit_has_rule_effect`), pas cette fonction-ci ;
  - ⚠️ les DEUX appelants de production — `w40k_core.py` (charge IA) et `charge_handlers.py`
    (charge PvP) — ne sont couverts par aucun test : inverser leur condition laisse la suite
    verte. Trou connu, sans conséquence tant qu'aucune datasheet ne porte la règle ; à fermer
    en même temps que la datasheet qui la ramènera.
"""
import pytest

from engine.phase_handlers.shared_utils import unit_can_reroll_charge


def _gs(unit_rules):
    return {"unit_by_id": {"1": {"id": "1", "UNIT_RULES": list(unit_rules)}}}


def test_regle_detectee_sur_l_unite():
    """L'unité qui déclare reroll_charge est reconnue."""
    assert unit_can_reroll_charge(_gs([{"ruleId": "reroll_charge"}]), "1") is True


def test_absence_de_regle():
    """Contre-épreuve : sans la règle, aucun reroll."""
    assert unit_can_reroll_charge(_gs([]), "1") is False


def test_autre_regle_ne_declenche_pas():
    """Discrimination : une autre règle d'unité ne donne pas le reroll de charge."""
    assert unit_can_reroll_charge(_gs([{"ruleId": "reroll_1_towound"}]), "1") is False


def test_unite_introuvable_leve():
    """Aucun repli masquant : une unité inconnue est un bug, pas un 'False' silencieux."""
    with pytest.raises(KeyError):
        unit_can_reroll_charge({"unit_by_id": {}}, "404")


#: Datasheets purgées par le chantier 05 : les neuf pages Armageddon Orks, les deux SM dont la
#: datasheet a été relue (Captain with Relic Shield, Chaplain with Jump Pack), et les six SM
#: hors Armageddon purgées sur arbitrage — invérifiables contre un PDF, mais porteuses du même
#: placeholder inventé.
#:
#: `CaptainPowerWeaponBolter` a été la dernière, purgée quelques heures après les autres : les
#: tests de la règle 19.04 s'ancraient sur son `reroll_charge` et n'avaient pas d'autre témoin.
#: Ils reposent depuis sur un couple de vraies datasheets (Chaplain with Jump Pack / Assault
#: Intercessors with Jump Packs), donc plus rien ne retient le placeholder nulle part.
_PURGEES = (
    "Warboss", "Bigboss", "BannerNob", "PainBoy", "WeirdBoy",
    "Boyz", "BoyzNobKombi", "BoyzNobKustomShoota", "Gretchin",
    "WarTrakk", "BigMekDakkarig",
    "CaptainRelicShield", "ChaplainJumpPack",
    "CaptainTerminatorRelicFistBolter", "CaptainTerminatorRelicFistCombi",
    "CaptainTerminatorRelicWeaponBolter", "CaptainTerminatorRelicWeaponCombi",
    "LibrarianTerminator", "CaptainPowerWeaponBolter",
    # `endlessDuty` : sous-dossier de roster que `config/unit_registry.json` ne declare PAS.
    # Nommee ici en plus du balayage exhaustif, parce qu'elle est le seul cas ou les deux
    # sources de verite divergent — et c'est exactement celui qu'un balayage mal branche rate.
    "LeaderCaptainTerminator",
)


@pytest.mark.parametrize("unit_type", _PURGEES)
def test_une_datasheet_purgee_ne_relance_plus_la_charge(unit_type):
    """VERROU chantier 05 : le placeholder inventé ne revient pas par les rosters.

    Lecture par `UnitRegistry` — le CHEMIN DE PRODUCTION, celui qui alimente `game_state` —
    et pas un grep sur le fichier : c'est ce que le moteur verra réellement.
    """
    from ai.unit_registry import UnitRegistry

    entries = UnitRegistry().get_unit_data(unit_type).get("UNIT_RULES") or []
    portees = {e["ruleId"] for e in entries}
    assert "reroll_charge" not in portees, (
        f"{unit_type} porte encore reroll_charge : la datasheet Armageddon ne l'accorde pas "
        f"(UNIT_RULES : {sorted(portees)})"
    )


def test_aucune_datasheet_du_registre_ne_porte_le_placeholder():
    """Balayage EXHAUSTIF : plus AUCUNE des datasheets découvertes ne porte `reroll_charge`.

    Le test paramétré ci-dessus ne regarde que les datasheets connues au moment de la purge ;
    celui-ci attrape les autres — une unité ajoutée plus tard qui recopierait une datasheet
    existante, ou une purge qui se déferait sur un fichier que `_PURGEES` ne nomme pas.

    La source énumérée est `UnitRegistry().units`, c'est-à-dire ce que le parseur a RÉELLEMENT
    découvert en balayant `frontend/src/roster`. Énumérer `config/unit_registry.json` à la place
    rendait ce test menteur : ce fichier ne déclare pas les datasheets `endlessDuty`, dont
    `LeaderCaptainTerminator` — purgée par ce même chantier — donc y réintroduire le placeholder
    laissait le fichier vert.

    Il vaut aussi RÈGLE : `reroll_charge` reste au registre (`config/unit_rules.json`) et le
    moteur sait l'appliquer, mais aucune datasheet du jeu ne l'accorde. Le jour où une vraie
    datasheet en gagne une — il en existe en 40K — ce test se met à jour, il ne se supprime pas.
    """
    from ai.unit_registry import UnitRegistry

    decouvertes = UnitRegistry().units
    porteurs = sorted(
        unit_type for unit_type, data in decouvertes.items()
        if any(
            entry["ruleId"] == "reroll_charge"
            for entry in (data.get("UNIT_RULES") or [])
        )
    )
    assert porteurs == [], f"reroll_charge est revenu sur : {porteurs}"

    # VERT VACANT, en deux temps. Un compte global ne suffit pas : le trou réel n'était pas un
    # parseur muet mais un parseur qui ne DESCENDAIT PAS dans `endlessDuty/`. Chaque datasheet
    # purgée doit donc être individuellement présente dans ce que le balayage a vu.
    manquantes = sorted(set(_PURGEES) - set(decouvertes))
    assert not manquantes, (
        f"le balayage ne voit pas {manquantes} : il ne peut pas y détecter une réintroduction"
    )
    assert len(decouvertes) > len(_PURGEES) + 50, (
        f"seulement {len(decouvertes)} datasheets découvertes : le balayage ne couvre plus rien"
    )


def test_le_verrou_ci_dessus_regarde_de_vraies_regles():
    """VERT VACANT : le verrou lit-il encore des `UNIT_RULES`, ou une liste vide partout ?

    8 des 19 datasheets purgées n'ont plus AUCUNE règle — c'est le résultat attendu de la purge,
    mais c'est aussi ce à quoi ressemblerait un parseur cassé. Sans ces témoins, une régression
    de `_extract_static_properties` rendrait tout le fichier trivialement vert.

    Les témoins sont choisis pour couvrir les trois formes de déclaration qui subsistent : un
    marqueur de rôle, une capacité à effet direct, et une capacité au nom porteur d'apostrophe
    (le cas qui avait déjà cassé le parseur une fois).
    """
    from ai.unit_registry import UnitRegistry

    registry = UnitRegistry()
    attendus = {
        "Warboss": "leader",
        "AggressorBoltStorm": "closest_target_penetration",
        "Gretchin": "cp_gain_on_objective",
    }
    for unit_type, rule_id in attendus.items():
        portees = {
            entry["ruleId"] for entry in (registry.get_unit_data(unit_type).get("UNIT_RULES") or [])
        }
        assert rule_id in portees, (
            f"{unit_type} ne porte plus {rule_id!r} (UNIT_RULES lues : {sorted(portees)}) — "
            "le parseur de datasheets ne rend plus de règles, les verrous de ce fichier sont vides"
        )
