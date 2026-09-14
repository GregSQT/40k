"""Marqueur « échauffé sous cette table » — décision B du 2026-09-14 (échauffement critic B6).

`value_warmup_updates` vit dans le profil de lignée (`x1_lineage`), donc chaque `--append`
suivant la porte encore : sans marqueur, chaque étape rejouait 20 updates critic-only (~1 440
épisodes, politique figée) sans qu'aucun garde-fou ne le voie. Le zip retient désormais sous
quelle table de récompense le dernier échauffement s'est ACHEVÉ (`value_warmup_done_under`,
écrit par `PatchedMaskablePPO.train` à la dernière update du régime), et
`ai/train.py::arm_value_warmup` refuse à l'ouverture un run dont le profil demande un
échauffement déjà fait sous cette table. L'identité de la table est
`training_contract.reward_table_fingerprint` : clés ET valeurs, hors clés de documentation —
le critic apprend la somme des récompenses, un facteur doublé est une autre cible.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from ai.patched_ppo import PatchedMaskablePPO
from ai.train import arm_value_warmup
from ai.training_contract import reward_table_fingerprint
from tests.unit.ai.test_critic_warmup import _TABLE_ID, _model, _run_one_update
from tests.unit.ai.test_gradient_norm_is_pre_clip import _TinyMaskedEnv

_AGENT = "AgentTest"


def _rewards(**overrides: Any) -> Dict[str, Any]:
    """Table minimale acceptée par `agent_reward_table` (section `base_actions` non vide)."""
    table: Dict[str, Any] = {
        "base_actions": {"ranged_attack": 1.0, "wait": -0.1},
        "objective_rewards": {"vp_margin_factor": 6.0, "_comment": "doc"},
    }
    table.update(overrides)
    return {_AGENT: table}


# --- Le modèle inscrit le marqueur à l'ACHÈVEMENT du régime ---------------------------------


def test_le_marqueur_est_ecrit_a_la_derniere_update_du_regime_pas_avant() -> None:
    """n_warmup=2 : après 1 update, aucun marqueur ; après 2, l'empreinte du run.

    VERROU. Écrire le marqueur à l'ouverture (ou à la première update) ferait passer la
    première assertion au ROUGE : un checkpoint pris au milieu de l'échauffement se dirait
    échauffé, et `--resume-from` sauterait la moitié du régime.
    """
    model = _model(n_warmup=2)
    assert model.value_warmup_done_under is None

    _run_one_update(model)
    assert model._vwu_done == 1
    assert model.value_warmup_done_under is None, "marqueur posé avant la fin du régime"

    _run_one_update(model)
    assert model._vwu_done == 2
    assert model.value_warmup_done_under == _TABLE_ID


def test_sans_warmup_aucun_marqueur_n_est_ecrit() -> None:
    model = _model(n_warmup=0)
    _run_one_update(model)
    assert model.value_warmup_done_under is None


def test_le_marqueur_voyage_dans_le_zip_mais_pas_l_identite_du_run(tmp_path) -> None:
    """`value_warmup_done_under` est sérialisé ; `value_warmup_contract_id` (identité du RUN
    courant, posée à chaque ouverture) ne l'est pas — c'est `arm_value_warmup` qui la repose."""
    model = _model(n_warmup=1)
    _run_one_update(model)
    assert model.value_warmup_done_under == _TABLE_ID
    path = tmp_path / "m.zip"
    model.save(str(path))

    loaded = PatchedMaskablePPO.load(str(path), env=_TinyMaskedEnv(), device="cpu")
    assert loaded.value_warmup_done_under == _TABLE_ID, "le marqueur n'a pas voyagé dans le zip"
    assert loaded.value_warmup_contract_id is None, "l'identité du run a voyagé dans le zip"


def test_un_echauffement_sans_identite_de_table_est_refuse() -> None:
    """T1 : `value_warmup_updates > 0` sans `value_warmup_contract_id` lève dans `train`.

    Un échauffement qui ne sait pas sous quelle table il se fait ne peut pas s'inscrire, et le
    run suivant le rejouerait — exactement ce que le marqueur existe pour empêcher.
    """
    model = _model(n_warmup=1)
    model.value_warmup_contract_id = None
    with pytest.raises(RuntimeError, match="value_warmup_contract_id"):
        _run_one_update(model)


def test_un_zip_anterieur_au_marqueur_charge_sans_marqueur(tmp_path) -> None:
    """Zip sauvé avant la décision B (pas d'attribut) : chargé avec `None`, jamais un KeyError."""
    model = _model(n_warmup=0)
    delattr(model, "value_warmup_done_under")
    path = tmp_path / "old.zip"
    model.save(str(path))

    loaded = PatchedMaskablePPO.load(str(path), env=_TinyMaskedEnv(), device="cpu")
    assert loaded.value_warmup_done_under is None


# --- L'ouverture du run : `arm_value_warmup` ------------------------------------------------


def _logs() -> List[str]:
    return []


def test_arm_pose_toujours_l_identite_de_la_table_du_run() -> None:
    """Même sans clé dans le profil : `train` en a besoin le jour où un profil la porte."""
    model = _model(n_warmup=0)
    model.value_warmup_contract_id = None
    arm_value_warmup(model, {}, _rewards(), _AGENT, log=_logs().append)
    assert model.value_warmup_contract_id == reward_table_fingerprint(_rewards(), _AGENT)


def test_arm_refuse_un_echauffement_deja_fait_sous_cette_table() -> None:
    """Profil avec la clé + zip marqué de CETTE table → ValueError, et l'identité reste posée.

    VERROU. Retirer le `raise` d'`arm_value_warmup` fait passer ce test au ROUGE — et rend au
    profil de lignée son rejeu silencieux de 20 updates à chaque étape.
    """
    rewards = _rewards()
    model = _model(n_warmup=0)
    model.value_warmup_done_under = reward_table_fingerprint(rewards, _AGENT)
    with pytest.raises(ValueError, match="value_warmup_done_under"):
        arm_value_warmup(model, {"value_warmup_updates": 20}, rewards, _AGENT, log=_logs().append)


def test_arm_laisse_passer_quand_le_profil_ne_demande_rien() -> None:
    """Le marqueur seul n'interdit rien : sans clé (ou à 0), aucun échauffement, aucun refus."""
    rewards = _rewards()
    model = _model(n_warmup=0)
    model.value_warmup_done_under = reward_table_fingerprint(rewards, _AGENT)
    journal = _logs()
    arm_value_warmup(model, {}, rewards, _AGENT, log=journal.append)
    arm_value_warmup(model, {"value_warmup_updates": 0}, rewards, _AGENT, log=journal.append)
    assert journal == []


def test_arm_laisse_passer_un_echauffement_sous_une_autre_table() -> None:
    """Marqueur d'une AUTRE table (facteur changé) : l'échauffement se joue, le log dit sous
    quelle empreinte et laquelle était la précédente."""
    ancienne = _rewards()
    nouvelle = _rewards(objective_rewards={"vp_margin_factor": 12.0})
    model = _model(n_warmup=0)
    model.value_warmup_done_under = reward_table_fingerprint(ancienne, _AGENT)
    journal = _logs()
    arm_value_warmup(model, {"value_warmup_updates": 20}, nouvelle, _AGENT, log=journal.append)
    assert len(journal) == 1
    assert reward_table_fingerprint(nouvelle, _AGENT) in journal[0]
    assert reward_table_fingerprint(ancienne, _AGENT) in journal[0]


def test_arm_laisse_passer_un_zip_jamais_echauffe() -> None:
    model = _model(n_warmup=0)
    journal = _logs()
    arm_value_warmup(model, {"value_warmup_updates": 20}, _rewards(), _AGENT, log=journal.append)
    assert len(journal) == 1 and "jamais echauffee" in journal[0]


# --- L'identité de la table : `reward_table_fingerprint` -------------------------------------


def test_l_empreinte_ignore_les_cles_de_documentation() -> None:
    """Reformuler `_comment` ne change pas la cible du critic."""
    a = _rewards()
    b = _rewards(objective_rewards={"vp_margin_factor": 6.0, "_comment": "autre texte", "_normal": "x"})
    assert reward_table_fingerprint(a, _AGENT) == reward_table_fingerprint(b, _AGENT)


def test_l_empreinte_change_avec_une_valeur_et_avec_une_cle() -> None:
    """Contrairement au contrat (`build_contract`, noms seuls) : un poids doublé est une autre
    cible pour le critic, au même titre qu'une clé remplacée."""
    base = reward_table_fingerprint(_rewards(), _AGENT)
    valeur = reward_table_fingerprint(_rewards(objective_rewards={"vp_margin_factor": 12.0}), _AGENT)
    cle = reward_table_fingerprint(_rewards(objective_rewards={"objective_reward_factor": 6.0}), _AGENT)
    assert base != valeur
    assert base != cle
    assert valeur != cle


def test_l_empreinte_est_stable_a_l_ordre_des_cles() -> None:
    a = {_AGENT: {"base_actions": {"wait": -0.1, "ranged_attack": 1.0}}}
    b = {_AGENT: {"base_actions": {"ranged_attack": 1.0, "wait": -0.1}}}
    assert reward_table_fingerprint(a, _AGENT) == reward_table_fingerprint(b, _AGENT)
    assert len(reward_table_fingerprint(a, _AGENT)) == 16
