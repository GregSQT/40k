"""Verrou de la graine `torch` posée par la fixture autouse de `tests/conftest.py`.

La fixture ne fait plus `import torch` : elle sème le module s'il est DÉJÀ dans `sys.modules`,
pour ne pas faire payer 4,9 s d'import à chaque worker xdist qui ne touche pas au RL. La
correction repose sur un détail non évident — pytest importe tous les modules de test à la
COLLECTE, donc avant le premier setup de fixture. Si ce détail changeait (import différé, plugin
de collecte paresseuse), le déterminisme des tests RL tomberait SILENCIEUSEMENT : aucun test ne
planterait, ils deviendraient seulement non reproductibles. D'où ce verrou explicite.

Contre-épreuve exécutée : en forçant `torch = None` dans la fixture, ce test devient rouge
(`initial_seed()` rend la graine aléatoire du processus).
"""

import torch


def test_the_autouse_fixture_seeds_torch_without_importing_it():
    assert torch.initial_seed() == 12345
