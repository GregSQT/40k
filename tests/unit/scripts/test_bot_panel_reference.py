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
    for grandeur in ("combined=0.8567", "attrition=0.810", "pire scenario=0.7800", "T2/T5=1.81/1.76"):
        assert grandeur in ligne


def test_la_ligne_signale_la_rupture_tant_que_les_chiffres_ne_sont_pas_rejoues(module):
    """Tant que l'étalon épinglé n'est pas celui des chiffres, la ligne doit le DIRE.

    Le 2026-08-20, l'ajout de la tête `charge_pair_net` a rendu inchargeable tout checkpoint
    antérieur, dont celui sur lequel ces chiffres ont été pris. La ligne continuait à s'afficher
    telle quelle : un lecteur comparait un relevé neuf à une base qu'aucun modèle chargeable ne
    peut plus produire. L'avertissement n'est donc pas du décor, et il doit DISPARAÎTRE le jour
    où la ligne est rejouée sur l'étalon courant — sans quoi il devient un mensonge inverse.
    """
    direct = charger_script("scripts/bot_zone_direct.py")
    etalon = re.search(r"robust_(\d+\.\d+)", direct.REFERENCE_MODEL)
    assert etalon, f"REFERENCE_MODEL n'a pas la forme `..._robust_<score>.zip` : {direct.REFERENCE_MODEL!r}"

    ligne = module.PANEL_REFERENCE_LINE
    mesure = re.search(r"robust_(\d+\.\d+)", ligne)
    assert mesure, "La ligne ne nomme pas le checkpoint sur lequel les chiffres ont été pris."

    if mesure.group(1) == etalon.group(1):
        assert "PRÉ-RUPTURE" not in ligne, (
            "Les chiffres sont désormais pris sur l'étalon épinglé : l'avertissement de rupture "
            "annonce une incomparabilité qui n'existe plus."
        )
    else:
        assert "PRÉ-RUPTURE" in ligne, (
            f"Les chiffres viennent de robust_{mesure.group(1)} alors que l'étalon épinglé est "
            f"robust_{etalon.group(1)} : la ligne doit signaler que rien ne s'y compare."
        )
        assert etalon.group(1) in ligne, (
            "L'avertissement doit nommer l'étalon courant, sinon le lecteur ne sait pas sur quoi "
            "la remesure doit être faite."
        )


def test_la_condition_experimentale_n_est_pas_un_siege_fixe(module):
    """`x1_long` tire le siège au sort : annoncer « bot=P2 » décrivait un autre protocole."""
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


def test_chiffres_concordent_avec_doc_12_14(module):
    """Le module et le §12.14 du document de chantier portent les mêmes chiffres.

    Sans ce test, le module peut passer des heures avec une référence périmée (c'est arrivé
    le 2026-08-13 avec l'étiquette §12.5/JAMAIS REJOUÉE) sans qu'aucun test ne rougisse.
    La source de vérité est le document ; le module doit la refléter.
    """
    texte = DOC_PANEL.read_text(encoding="utf-8")

    # Ligne canonique du §12.14 : "`Combined = 0,7433`. Pire bot `racer = 0,630`."
    m_doc = re.search(r"`Combined = (\d+,\d+)`\. Pire bot `(\w+) = (\d+,\d+)`", texte)
    assert m_doc, (
        "Ligne de référence §12.14 non trouvée dans le document. "
        "Forme attendue : `Combined = X,XXXX`. Pire bot `<nom> = X,XXX`."
    )
    combined_doc = m_doc.group(1).replace(",", ".")
    pire_bot_nom_doc = m_doc.group(2)
    pire_bot_val_doc = m_doc.group(3).replace(",", ".")

    # Module : "combined=0.7433  pire bot racer=0.630  ..."
    m_mod = re.search(r"combined=(\S+)\s+pire bot (\w+)=(\S+)", module.PANEL_REFERENCE_FIGURES)
    assert m_mod, f"Format de PANEL_REFERENCE_FIGURES inattendu : {module.PANEL_REFERENCE_FIGURES!r}"
    combined_mod = m_mod.group(1)
    pire_bot_nom_mod = m_mod.group(2)
    pire_bot_val_mod = m_mod.group(3)

    assert combined_mod == combined_doc, (
        f"combined diverge — module={combined_mod!r}, doc §12.14={combined_doc!r}. "
        "Mettre à jour scripts/bot_panel_reference.py ou le document."
    )
    assert pire_bot_nom_mod == pire_bot_nom_doc, (
        f"Nom du pire bot diverge — module={pire_bot_nom_mod!r}, doc §12.14={pire_bot_nom_doc!r}."
    )
    assert pire_bot_val_mod == pire_bot_val_doc, (
        f"Win-rate du pire bot diverge — module={pire_bot_val_mod!r}, doc §12.14={pire_bot_val_doc!r}. "
        "Mettre à jour scripts/bot_panel_reference.py ou le document."
    )
