"""Verrouille les gardes de bot_zone_direct.py ajoutées le 2026-08-13.

_require_board_path  : lève RuntimeError si W40K_BOARD_PATH absent de l'environnement.
_require_reference_model : lève RuntimeError si le md5 du fichier ne correspond pas à
                           REFERENCE_MD5. Ne touche jamais ai/models/ — le chemin est
                           monkeypatché vers un fichier temporaire.
--label : présent dans run_meta quand fourni, absent quand omis.
_avg_focus_target_distance : retourne None sur _focus_target périmé (appartient au bot-player).
"""
import hashlib
import os
from pathlib import Path

import pytest

from tests._chargeur_script import charger_script

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "bot_zone_direct.py"

_DUMMY_FINGERPRINT = {
    "model_path": "/fake/model.zip",
    "model_bytes": 1000,
    "model_mtime": "2026-08-13T00:00:00",
}


@pytest.fixture(scope="module")
def script():
    return charger_script("scripts/bot_zone_direct.py")


# ---------------------------------------------------------------------------
# Garde de plateau
# ---------------------------------------------------------------------------

def test_require_board_path_leve_sans_variable(script, monkeypatch):
    monkeypatch.delenv("W40K_BOARD_PATH", raising=False)
    with pytest.raises(RuntimeError, match="W40K_BOARD_PATH"):
        script._require_board_path()


def test_require_board_path_retourne_le_chemin_quand_definie(script, monkeypatch):
    monkeypatch.setenv("W40K_BOARD_PATH", "board/44x60x1")
    assert script._require_board_path() == "board/44x60x1"


# ---------------------------------------------------------------------------
# Garde de modèle
# ---------------------------------------------------------------------------

def _model_dir(tmp_path: Path) -> Path:
    """Structure ai/models/ArmageddonAgent/ sous tmp_path."""
    d = tmp_path / "ai" / "models" / "ArmageddonAgent_x1"
    d.mkdir(parents=True)
    return d


def test_require_reference_model_leve_sur_md5_incorrect(script, monkeypatch, tmp_path):
    d = _model_dir(tmp_path)
    nom = "faux.zip"
    (d / nom).write_bytes(b"contenu qui ne correspond pas au md5 de reference")
    monkeypatch.setattr(script, "_DEFAULT_MODEL", str(d / nom))
    with pytest.raises(RuntimeError, match="md5"):
        script._require_reference_model()


def test_require_reference_model_passe_sur_md5_correct(script, monkeypatch, tmp_path):
    contenu = b"contenu connu pour le test"
    md5_reel = hashlib.md5(contenu, usedforsecurity=False).hexdigest()
    d = _model_dir(tmp_path)
    nom = "ref.zip"
    (d / nom).write_bytes(contenu)
    monkeypatch.setattr(script, "_DEFAULT_MODEL", str(d / nom))
    monkeypatch.setattr(script, "REFERENCE_MD5", md5_reel)
    path = script._require_reference_model()
    assert os.path.basename(path) == nom


def test_require_reference_model_leve_sur_modele_custom_absent(script, tmp_path):
    chemin = str(tmp_path / "inexistant.zip")
    with pytest.raises(RuntimeError) as exc:
        script._require_reference_model(chemin)
    msg = str(exc.value)
    assert "inexistant.zip" in msg
    assert "§12" not in msg


def test_require_reference_model_chemin_non_canonique_verifie_md5(script, monkeypatch, tmp_path):
    """Un chemin avec .. pointant sur le checkpoint de référence doit quand même vérifier le MD5."""
    contenu = b"contenu connu"
    md5_reel = hashlib.md5(contenu, usedforsecurity=False).hexdigest()
    d = _model_dir(tmp_path)
    nom = "ref.zip"
    cible = d / nom
    cible.write_bytes(contenu)
    monkeypatch.setattr(script, "_DEFAULT_MODEL", str(cible))
    monkeypatch.setattr(script, "REFERENCE_MD5", "000000000000000000000000deadbeef")
    # chemin équivalent via .. — string != _DEFAULT_MODEL, mais realpath identique
    non_canonique = str(d / ".." / "ArmageddonAgent_x1" / nom)
    with pytest.raises(RuntimeError, match="md5"):
        script._require_reference_model(non_canonique)


# ---------------------------------------------------------------------------
# --label dans run_meta
# ---------------------------------------------------------------------------


def test_label_present_dans_run_meta_quand_fourni(script):
    meta = script._run_meta(
        _DUMMY_FINGERPRINT, "holdout_1.json", 20, 6, 42, "alternate", 7, {"bot": 0.25},
        {"bot": {"w_crowd": 4.0}}, 3.0, "x1_long",
        label="foo",
    )
    assert meta["label"] == "foo"


def test_label_absent_de_run_meta_quand_omis(script):
    meta = script._run_meta(
        _DUMMY_FINGERPRINT, "holdout_1.json", 20, 6, 42, "alternate", 7, {"bot": 0.25},
        {"bot": {"w_crowd": 4.0}}, 3.0, "x1_long",
    )
    assert "label" not in meta


# ---------------------------------------------------------------------------
# _avg_focus_target_distance — valeur périmée d'un épisode précédent
# ---------------------------------------------------------------------------

class _BotWithFocusTarget:
    """Stub minimal : possède _focus_target comme DecapitationBot."""
    def __init__(self, focus_target):
        self._focus_target = focus_target


def _gs_with_unit(unit_id: str, player: int) -> dict:
    """game_state minimal avec une seule unité pour tester le lookup de joueur."""
    return {
        "units": [{"id": unit_id, "player": player}],
        "units_cache": {
            unit_id: {"id": unit_id, "player": player, "col": 5, "row": 5},
        },
    }


def test_avg_focus_target_distance_retourne_none_si_focus_appartient_au_bot(script):
    """Régression 2026-08-14 : _focus_target périmé d'un épisode précédent ne doit pas lever.

    Scénario : bot était P2 (ciblait unité '1' de P1), épisode suivant bot est P1.
    _focus_target vaut encore '1' (jamais réinitialisé avant la 1ère décision).
    """
    bot = _BotWithFocusTarget("1")
    gs = _gs_with_unit("1", player=1)
    result = script._avg_focus_target_distance(gs, bot, bot_player=1)
    assert result is None


def test_avg_focus_target_distance_retourne_none_si_focus_introuvable(script):
    """_focus_target absent de gs['units'] → None (unité disparue entre épisodes)."""
    bot = _BotWithFocusTarget("99")
    gs = {"units": [], "units_cache": {}}
    result = script._avg_focus_target_distance(gs, bot, bot_player=1)
    assert result is None
