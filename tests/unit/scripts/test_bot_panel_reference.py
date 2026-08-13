"""Verrouille la source UNIQUE de la référence chiffrée du panel (§12.14).

Le défaut réparé le 2026-08-13 : `bot_zone_check.py` et `bot_zone_direct.py` imprimaient les
MÊMES chiffres sous des étiquettes CONTRAIRES (« pre-§12.6 » / « post-§12.6 »). Deux littéraux
ne peuvent pas se contredire bruyamment, donc rien ne l'a signalé. Ces tests interdisent la
recopie plutôt que de vérifier deux copies l'une contre l'autre : un troisième script du panel
qui réécrirait les chiffres fait rougir `test_aucune_recopie_dans_scripts`.
"""
import re
from pathlib import Path

import pytest

from tests._chargeur_script import charger_script

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = PROJECT_ROOT / "scripts"
DOC_PANEL = PROJECT_ROOT / "Documentation/Implémentation/A_faire/bots_refonte_panel.md"

#: Les scripts du panel qui affichent la référence. Ils l'IMPRIMENT, ils ne l'écrivent pas.
APPELANTS = ("bot_zone_check.py", "bot_zone_direct.py")


@pytest.fixture(scope="module")
def module():
    return charger_script("scripts/bot_panel_reference.py")


def test_aucune_recopie_dans_scripts():
    """Un seul fichier de `scripts/` porte les chiffres : le module de référence."""
    porteurs = sorted(
        chemin.name
        for chemin in SCRIPTS.rglob("*.py")
        if "combined=0.7433" in chemin.read_text(encoding="utf-8")
    )
    assert porteurs == ["bot_panel_reference.py"], (
        "La référence chiffrée est recopiée hors de bot_panel_reference.py : "
        f"{porteurs}. C'est exactement le défaut du 2026-08-13 (deux étiquettes contraires)."
    )


@pytest.mark.parametrize("nom", APPELANTS)
def test_les_appelants_passent_par_le_helper(nom):
    source = (SCRIPTS / nom).read_text(encoding="utf-8")
    assert "print_panel_reference()" in source
    assert "combined=0.7433" not in source


def test_l_etiquette_est_celle_de_la_mesure_la_plus_recente(module):
    """La référence est POSTÉRIEURE à tous les correctifs du chantier, et le dit.

    L'étiquette « pre-§12.6 / JAMAIS REJOUÉE » était juste le matin du 2026-08-13 et fausse le
    soir : trois mesures l'ont rejouée dans la journée. Ce test interdit qu'elle revienne, et
    exige que la ligne nomme les correctifs qu'elle suit — sans quoi un lecteur ne peut pas
    savoir à quoi il compare.
    """
    ligne = module.PANEL_REFERENCE_LINE
    assert "JAMAIS REJOUÉE" not in ligne
    assert "pre-§12.6" not in ligne
    for correctif in ("post-§12.6", "post-§12.9", "post-§12.11"):
        assert correctif in ligne


def test_la_ligne_porte_les_quatre_grandeurs(module):
    ligne = module.PANEL_REFERENCE_LINE
    for grandeur in ("combined=0.7433", "racer=0.630", "pire scenario=0.6867", "T2/T5=1.60/1.89"):
        assert grandeur in ligne


def test_la_condition_experimentale_n_est_pas_un_siege_fixe(module):
    """`x1_panel` tire le siège au sort : annoncer « bot=P2 » décrivait un autre protocole."""
    ligne = module.PANEL_REFERENCE_LINE
    assert "siège aléatoire" in ligne
    assert "bot=P2" not in ligne


def test_print_emet_la_ligne(module, capsys):
    module.print_panel_reference()
    assert capsys.readouterr().out.strip() == module.PANEL_REFERENCE_LINE.strip()


def test_le_doc_ne_labelle_plus_la_reference_post_12_6():
    """La ligne du §12.7 est la SOURCE de l'étiquette fautive : elle doit rester juste."""
    lignes = [
        ligne
        for ligne in DOC_PANEL.read_text(encoding="utf-8").splitlines()
        if re.search(r"Référence panel \(§12\.5", ligne)
    ]
    assert lignes, "La ligne « Référence panel (§12.5… » a disparu du doc de chantier."
    for ligne in lignes:
        assert "pre-§12.6" in ligne
