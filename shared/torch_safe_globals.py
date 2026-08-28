"""Liste blanche des globals autorisés au chargement des modèles PPO.

Depuis torch 2.6, `torch.load` s'exécute par défaut en `weights_only=True` : un dépickle
RESTREINT, qui refuse tout global absent d'une liste blanche. Les checkpoints
Stable-Baselines3 de ce dépôt contiennent des scalaires numpy (hyperparamètres, bornes
d'espaces d'observation) et échouent donc en l'état, avec :

    Unsupported global: GLOBAL numpy._core.multiarray.scalar was not an allowed global

Ce module autorise ces deux globals, et RIEN d'autre.

Ce qu'il ne faut PAS faire à la place : repasser `weights_only=False`. Ce serait rouvrir
l'exécution de code arbitraire au chargement d'un `.zip` de modèle — exactement le vecteur
qu'exploitent les CVE torch listées dans `scripts/security_audit_ignore.txt`. La liste
blanche est, côté modèles, le pendant de `_safe_loads` côté sauvegardes de partie
(securite.md, étapes 2 et 6).

Jeu minimal vérifié le 2026-08-11 sur torch 2.13.0 + sb3 2.9.0 : `numpy._core.multiarray.
scalar` et `numpy.dtype` suffisent à recharger tous les modèles du dépôt. Le module reste
sans effet de bord sur torch 2.5.x, où `add_safe_globals` existe déjà et où
`weights_only` vaut encore `False` par défaut.

Appelé au niveau MODULE (pas par site de chargement) dans chaque fichier qui charge un
modèle : `ai/train.py`, `ai/bot_evaluation.py`, `ai/env_wrappers.py`,
`ai/replay_converter.py`, `engine/pve_controller.py`, plus `tests/conftest.py` pour les
tests qui appellent `MaskablePPO.load` directement. Un nouveau site de chargement dans
l'un de ces fichiers est donc couvert sans rien ajouter.
"""

_REGISTERED = False


def register_torch_safe_globals() -> None:
    """Autorise les scalaires numpy au dépickle restreint de `torch.load`. Idempotent."""
    global _REGISTERED
    if _REGISTERED:
        return

    import numpy as np
    import torch.serialization
    from numpy._core.multiarray import scalar as numpy_scalar

    # `numpy._core` est le chemin de numpy 2.x (`numpy.core` en 1.x). Le dépôt épingle numpy
    # 2.4.2 : si ce chemin disparaît, l'ImportError doit remonter telle quelle plutôt
    # que d'être rattrapée — un repli silencieux rendrait les modèles inchargeables avec
    # un message sans rapport.
    allowed = [numpy_scalar, np.dtype]

    # Toutes les classes de dtype de numpy, et elles seules. Énumérer à la main ne tient
    # pas : le jeu nécessaire dépend des dtypes présents dans CHAQUE checkpoint —
    # `Float64DType` manquait aux modèles CoreAgent alors que `Float32DType` suffisait aux
    # Armageddon (mesuré le 2026-08-11). Un ensemble FERMÉ vaut mieux qu'une liste qu'on
    # rallonge à chaque modèle qui casse.
    # Sûreté : ce sont des descripteurs de type numpy, pas des appelables arbitraires ;
    # les autoriser ne rouvre pas l'exécution de code que `weights_only=True` ferme.
    allowed.extend(
        getattr(np.dtypes, name) for name in dir(np.dtypes) if name.endswith("DType")
    )

    torch.serialization.add_safe_globals(allowed)
    _REGISTERED = True
