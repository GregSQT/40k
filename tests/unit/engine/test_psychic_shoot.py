"""[PSYCHIC] 24.29 — les modificateurs du jet de touche sont ignores.

PDF 24.29 : « Each time an attack is made with a [PSYCHIC] weapon, you can ignore any or all
modifiers to that attack's BS or WS characteristic and any or all modifiers to the hit roll. »

Dans ce moteur, le seul modificateur DEFAVORABLE du jet de touche au tir est le malus de
couvert 13.08 (`_cover_worsened_bs` degrade le BS de 1). « any or all » laisse le choix au
joueur : on ignore le malus et on garde le bonus [HEAVY] (choix optimal, deterministe).

Discrimination : meme fixture sous couvert, avec et sans [PSYCHIC].
"""
from engine.phase_handlers import shooting_handlers
from engine.phase_handlers.shared_utils import _cover_worsened_bs


def _sous_couvert(monkeypatch, cover=True):
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": cover})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})


def _weapon(rules):
    return {"WEAPON_RULES": list(rules), "display_name": "W", "RNG": 24, "NB": 1,
            "ATK": 3, "STR": 4, "AP": 0, "DMG": 1}


def test_psychic_ignore_le_malus_de_couvert(monkeypatch):
    """Arme PSYCHIC sous couvert : BS inchange, mais la cible garde le BENEFICE du couvert."""
    _sous_couvert(monkeypatch)
    bs, cover = _cover_worsened_bs({}, {"squad_id": "1"}, "2", 3, _weapon(["PSYCHIC"]))
    assert (bs, cover) == (3, True)


def test_sans_psychic_le_couvert_degrade_le_bs(monkeypatch):
    """Contre-epreuve : la meme arme sans PSYCHIC subit le malus (BS 3 -> 4)."""
    _sous_couvert(monkeypatch)
    bs, cover = _cover_worsened_bs({}, {"squad_id": "1"}, "2", 3, _weapon([]))
    assert (bs, cover) == (4, True)


def test_psychic_hors_couvert_ne_change_rien(monkeypatch):
    """Sans couvert, PSYCHIC n a rien a ignorer."""
    _sous_couvert(monkeypatch, cover=False)
    bs, cover = _cover_worsened_bs({}, {"squad_id": "1"}, "2", 3, _weapon(["PSYCHIC"]))
    assert (bs, cover) == (3, False)


def test_ignores_cover_supprime_le_benefice_psychic_le_conserve(monkeypatch):
    """24.18 vs 24.29 : IGNORES COVER retire le benefice du couvert (cover=False) ;
    PSYCHIC neutralise seulement le modificateur (cover reste True)."""
    _sous_couvert(monkeypatch)
    assert _cover_worsened_bs({}, {"squad_id": "1"}, "2", 3, _weapon(["IGNORES_COVER"])) == (3, False)
    assert _cover_worsened_bs({}, {"squad_id": "1"}, "2", 3, _weapon(["PSYCHIC"])) == (3, True)
