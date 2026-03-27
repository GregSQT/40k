import random

import numpy as np
import pytest

try:
    import torch
except ImportError:  # pragma: no cover
    torch = None


@pytest.fixture(autouse=True)
def deterministic_seed() -> None:
    seed = 12345
    random.seed(seed)
    np.random.seed(seed)
    if torch is not None:
        torch.manual_seed(seed)
