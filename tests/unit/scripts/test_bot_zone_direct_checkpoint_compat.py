"""Vérifie que le checkpoint épinglé de bot_zone_direct.py est chargeable par PointerMaskablePolicy.

Contexte (2026-08-20) : le commit d5ddffb5 a ajouté `charge_pair_net` à PointerMaskablePolicy.
Le checkpoint épinglé (`REFERENCE_MODEL`) est antérieur à ce commit — ses clés diffèrent de
celles de la politique courante. Rien n'a rougi : `MaskablePPO.load` tolère silencieusement des
clés manquantes avec `strict=False`, et `bot_zone_direct.py` a continué de tourner.

Ce test compare les CLÉS du `policy.pth` de l'archive épinglée aux paramètres d'une
`PointerMaskablePolicy` fraîchement construite. Toute divergence est une incompatibilité réelle :
soit le checkpoint ne contient pas un module qu'utilise la politique (clés manquantes), soit
il contient un module qui n'existe plus (clés en excès).

Le test est skippé si le fichier n'est pas présent (il n'est pas commité dans le dépôt) : son
absence est un problème pour `bot_zone_direct.py` lui-même, pas pour ce test.
"""

from __future__ import annotations

import io
import json
import pickle
import zipfile
from pathlib import Path

import gymnasium as gym
import numpy as np
from typing import cast
import pytest
import torch
from sb3_contrib import MaskablePPO
from stable_baselines3.common.save_util import json_to_data

from ai.pointer_policy import PointerMaskablePolicy
from ai.spatial_extractor import SpatialCombinedExtractor
from engine.macro_intents import TOTAL_ACTION_SIZE
from tests._chargeur_script import charger_script
from tests.unit.ai._fabriques import squad_obs_space

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = PROJECT_ROOT / "scripts" / "bot_zone_direct.py"


class _ToyEnv(gym.Env):
    """Env jouet avec l'espace d'observation réel, pour construire la politique sans moteur."""

    observation_space: gym.spaces.Dict = squad_obs_space()
    action_space = gym.spaces.Discrete(TOTAL_ACTION_SIZE)

    def reset(self, *, seed=None, options=None):
        return {k: np.zeros(cast(tuple[int, ...], v.shape), dtype=np.float32) for k, v in self.observation_space.spaces.items()}, {}

    def step(self, action):
        obs = {k: np.zeros(cast(tuple[int, ...], v.shape), dtype=np.float32) for k, v in self.observation_space.spaces.items()}
        return obs, 0.0, False, False, {}

    def action_masks(self):
        return np.ones(TOTAL_ACTION_SIZE, dtype=bool)


@pytest.fixture(scope="module")
def script():
    return charger_script("scripts/bot_zone_direct.py")


@pytest.fixture(scope="module")
def reference_zip(script):
    """Chemin résolu du zip épinglé ; skip si absent."""
    path = Path(script._DEFAULT_MODEL)
    if not path.exists():
        pytest.skip(f"Checkpoint de référence absent : {path} — bot_zone_direct ne peut pas tourner non plus")
    return path


@pytest.fixture(scope="module")
def _checkpoint_data(reference_zip):
    """Ouvre le zip une seule fois ; skip si une entrée obligatoire manque."""
    with zipfile.ZipFile(reference_zip) as z:
        names = z.namelist()
        for entry in ("policy.pth", "data"):
            if entry not in names:
                pytest.skip(
                    f"Archive {reference_zip.name!r} sans entrée {entry!r} "
                    f"(contenu : {', '.join(sorted(names))})"
                )
        with z.open("policy.pth") as f:
            keys = set(torch.load(io.BytesIO(f.read()), map_location="cpu", weights_only=True).keys())
        with z.open("data") as f:
            raw = f.read()
        try:
            data = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=False)
        except pickle.UnpicklingError:
            data = json_to_data(raw.decode())
        if not isinstance(data, dict):
            raise ValueError(f"Entrée 'data' de format inattendu : {type(data)}")
        policy_kwargs = data.get("policy_kwargs", {})
    return keys, policy_kwargs


@pytest.fixture(scope="module")
def checkpoint_keys(_checkpoint_data):
    return _checkpoint_data[0]


@pytest.fixture(scope="module")
def checkpoint_policy_kwargs(_checkpoint_data):
    return _checkpoint_data[1]


@pytest.fixture(scope="module")
def fresh_policy_keys(checkpoint_policy_kwargs):
    """Clés d'une PointerMaskablePolicy construite avec les policy_kwargs du checkpoint.

    Utiliser les kwargs réels (net_arch inclus) garantit que seul un changement de code
    (module ajouté/supprimé) crée une divergence, pas une différence d'architecture.
    """
    torch.manual_seed(0)
    model = MaskablePPO(
        PointerMaskablePolicy,
        _ToyEnv(),
        device="cpu",
        verbose=0,
        policy_kwargs=checkpoint_policy_kwargs,
    )
    return set(model.policy.state_dict().keys())


def test_checkpoint_ne_manque_aucune_cle_de_la_politique_courante(checkpoint_keys, fresh_policy_keys, reference_zip):
    """Le checkpoint doit contenir TOUTES les clés que la politique courante attend.

    Une clé absente du checkpoint mais présente dans la politique signifie qu'un nouveau module
    a été ajouté à PointerMaskablePolicy sans que le checkpoint ait été regénéré.
    `MaskablePPO.load` charge alors le checkpoint sans rougir (les poids manquants restent
    aléatoires), et bot_zone_direct.py tourne en mesurant un modèle différent de celui épinglé.
    """
    manquantes = fresh_policy_keys - checkpoint_keys
    assert not manquantes, (
        f"Le checkpoint {reference_zip.name!r} ne contient pas les clés suivantes, "
        f"présentes dans PointerMaskablePolicy :\n"
        + "\n".join(f"  - {k}" for k in sorted(manquantes))
        + "\nMise à jour nécessaire : régénérer le checkpoint avec la politique courante "
        "et mettre à jour REFERENCE_MODEL + REFERENCE_MD5 dans bot_zone_direct.py."
    )


def test_checkpoint_ne_contient_pas_de_cle_obsolete(checkpoint_keys, fresh_policy_keys, reference_zip):
    """Le checkpoint ne doit pas contenir de clés absentes de la politique courante.

    Une clé en excès indique qu'un module a été retiré de PointerMaskablePolicy depuis que le
    checkpoint a été sauvegardé. Ce n'est pas un crash, mais ces poids sont chargés pour rien
    et leur présence signale que le checkpoint est périmé.
    """
    en_exces = checkpoint_keys - fresh_policy_keys
    assert not en_exces, (
        f"Le checkpoint {reference_zip.name!r} contient des clés absentes de PointerMaskablePolicy :\n"
        + "\n".join(f"  - {k}" for k in sorted(en_exces))
        + "\nCes poids sont chargés mais inutilisés : le checkpoint est périmé."
    )
