"""Le segment `[MODELS:]` d'une ligne de journal ne doit pas dépendre du TYPE de son `unitId`.

`units_cache` est clé par CHAÎNE. `_models_segment_for_unit` y cherchait l'entrée avec la valeur
brute du payload — or les payloads d'`action_log` portent `unitId` tantôt en `str`, tantôt en
`int`. Pour les seconds, le lookup échouait et la fonction rendait `""` : **en silence**, parce
que le segment vide est un cas nominal (unité sans socle connu).

Conséquence, mesurée le 2026-08-12 : la ligne `[HAZARD]` n'a JAMAIS porté son `[MODELS:]` depuis
sa création — `roll_hazard_for_unit` pose `int(unit_id)`. Une blessure mortelle retire une
figurine, et le seul événement qui aurait pu repositionner l'escouade chez le lecteur du journal
sortait nu. L'analyzer gardait donc des socles morts pour vivants, ce qui fabrique de
l'engagement fantôme dans tous les contrôles géométriques en aval.

C'est le jumeau exact du trou déjà payé deux fois par cette même ligne : d'abord muette faute de
`col`/`row`, puis présente mais sans ses socles.
"""

import pytest

SQUAD = "7"
POSITIONS = {"7#0": (10, 10), "7#1": (11, 10)}


def _engine_with_squad():
    """Instance nue : seule la lecture de `units_cache` est en jeu, pas l'init du moteur."""
    from engine.w40k_core import W40KEngine

    engine = object.__new__(W40KEngine)
    engine.game_state = {
        "units_cache": {
            SQUAD: {
                "col": POSITIONS["7#0"][0], "row": POSITIONS["7#0"][1], "player": 1,
                "HP_CUR": 2, "BASE_SHAPE": "round", "BASE_SIZE": 1, "orientation": 0,
                "occupied_hexes": set(POSITIONS.values()),
                "occupied_hexes_by_model": dict(POSITIONS),
                "floor_height_by_model": {m: 0.0 for m in POSITIONS},
            }
        },
        "terrain_areas": [],
    }
    return engine


def test_the_hazard_payload_really_carries_an_int():
    """Prémisse : sans ce fait, le test ne décrit aucun défaut réel.

    Si un jour les payloads normalisent leur `unitId`, ce test cesse de protéger quoi que ce
    soit — et il doit le dire au lieu de rester vert pour rien.
    """
    from pathlib import Path

    src = Path("engine/phase_handlers/shared_utils.py").read_text(encoding="utf-8")
    assert '"unitId": int(unit_id),' in src, (
        "plus aucun payload ne pose un unitId entier : ce verrou n'a plus d'objet, le relire"
    )


@pytest.mark.parametrize("unit_id", [SQUAD, int(SQUAD)], ids=["str", "int"])
def test_the_segment_is_found_whatever_the_id_type(unit_id):
    """Les DEUX formes doivent rendre le même segment — c'est tout le contrat."""
    segment = _engine_with_squad()._models_segment_for_unit(unit_id)

    assert segment, (
        f"segment vide pour un unitId de type {type(unit_id).__name__} : la ligne de journal "
        "sortirait sans ses socles, et le lecteur garderait les figurines mortes pour vivantes"
    )
    for mid, (col, row) in POSITIONS.items():
        assert f"{mid}@({col},{row}" in segment, segment


def test_both_id_types_give_the_exact_same_segment():
    """Deux formes du même identifiant ne peuvent pas décrire deux états différents."""
    engine = _engine_with_squad()

    assert engine._models_segment_for_unit(SQUAD) == engine._models_segment_for_unit(int(SQUAD))


def test_an_unknown_unit_still_yields_an_empty_segment():
    """Le repli silencieux reste LÉGITIME quand l'unité est réellement absente du cache.

    Anti-vert-vacant : la correction ne doit pas transformer « pas de socle connu » en erreur,
    sinon toute ligne d'une unité hors cache ferait tomber la journalisation entière.
    """
    assert _engine_with_squad()._models_segment_for_unit("999") == ""
