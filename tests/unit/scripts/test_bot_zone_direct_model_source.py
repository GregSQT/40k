"""`bot_zone_direct` ne doit pas lire le modele au chemin canonique, et doit LEVER s'il manque.

Contexte, mesure du 2026-08-13 (chantier `A_faire/bots_refonte_panel.md` §12.7 invalidee, §12.8) :
l'instrument visait `ai/models/ArmageddonAgent/model_ArmageddonAgent.zip` en dur. Ce chemin est
partage et volatil — tout `train.py --new`, depuis n'importe quelle session, l'ecrase — et il
portait ce jour-la un AUTRE modele que celui dont le chantier tire tous ses chiffres. Les deux
tableaux du §12.7 ont donc ete publies sans que rien ne dise sur quoi ils avaient ete pris.

Les deux proprietes verrouillees ici sont exactement celles qui manquaient :

1. la valeur par defaut designe l'ARCHIVE NOMMEE, pas le chemin canonique. Un test de constante,
   assume : c'est une constante qui a coute une campagne, et le seul moment ou l'on constate
   qu'elle est revenue au chemin partage, c'est apres avoir publie des chiffres faux ;
2. un modele absent LEVE. Sans ce controle, `--model` mal orthographie retombait sur le defaut,
   c'est-a-dire precisement le repli silencieux que T1 interdit.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = PROJECT_ROOT / "scripts" / "bot_zone_direct.py"


def _load_module():
    """Charge le script via spec_from_file_location : le script se charge lui-meme ses dependances."""
    spec = importlib.util.spec_from_file_location("bot_zone_direct_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_le_modele_par_defaut_est_l_archive_nommee_pas_le_chemin_canonique():
    module = _load_module()
    defaut = module._DEFAULT_MODEL

    assert os.path.basename(defaut) != "model_ArmageddonAgent.zip", (
        "Le defaut est revenu au chemin canonique, qui est ecrase par tout `train.py --new` "
        "et par toute autre session : les mesures ne diraient plus sur quel modele elles portent."
    )
    assert "robust_" in os.path.basename(defaut), (
        "Le defaut doit designer une archive de modele NOMMEE (`..._robust_<score>.zip`), "
        "seule forme que rien ne reecrit."
    )


def test_modele_absent_leve_au_lieu_de_se_rabattre(monkeypatch, tmp_path):
    module = _load_module()
    manquant = tmp_path / "modele_qui_n_existe_pas.zip"
    assert not manquant.exists()

    monkeypatch.setattr(
        sys, "argv", ["bot_zone_direct.py", "--episodes", "1", "--model", str(manquant)]
    )

    with pytest.raises(RuntimeError) as leve:
        module.main()

    # Le message doit NOMMER le chemin cherche : c'est ce qui distingue une faute de frappe
    # d'un modele reellement absent, et c'est la seule information que l'appelant n'a pas.
    assert str(manquant) in str(leve.value)


def test_md5_est_bien_celui_du_fichier(tmp_path):
    import hashlib

    fichier = tmp_path / "donnees.bin"
    # Plus grand que le tampon de lecture (1 Mio) : un `read()` partiel rendrait un md5 faux
    # sur les gros modeles et juste sur tous les fichiers d'un test qui tiendrait en un bloc.
    contenu = b"w40k" * ((1 << 20) // 2)
    fichier.write_bytes(contenu)
    attendu = hashlib.md5(contenu, usedforsecurity=False).hexdigest()

    assert _load_module()._md5(str(fichier)) == attendu

    # JUMEAU : `roster_matchup_stats` mesure lui aussi sur le chemin canonique volatil et imprime
    # desormais la meme empreinte. Les deux implementations sont distinctes (pas de module commun
    # dans `scripts/`), donc c'est leur ACCORD qui se verifie, pas leur partage.
    from scripts.roster_matchup_stats import _model_md5

    assert _model_md5(str(fichier)) == attendu
