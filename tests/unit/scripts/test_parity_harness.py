"""Harnais de parité bit-à-bit — Phase 0.2 du chantier perf_entrainement.

OBJECTIF
--------
Garantir qu'aucune optimisation « pure perf » ne modifie la sémantique du moteur. Avant
toute Phase 1, on CAPTURE hash(masque, obs) pour N steps à graine fixe. Après l'optimisation,
on re-capture sur les mêmes conditions : toute divergence de hash indique une régression métier.

TROIS INVARIANTS VÉRIFIÉS
--------------------------
1. REPRODUCTIBILITÉ : deux runs à graine identique produisent exactement les mêmes hashes
   masque+obs à chaque step (prouve le déterminisme du moteur sur ce chemin).
2. DÉTECTION DE MUTATION : un patch qui flippe un bit du masque retourné par `get_action_mask`
   fait diverger les hashes → le harnais le détecte (rouge). Sans le patch → hashes identiques
   (vert).
3. GATE MASK_VERIFICATION ARMÉE : avec `W40K_MASK_VERIFY=1`, `verify_memoised_move_cell_map`
   est appelée au moins une fois sur N steps (le gate n'est pas un no-op) ; un run propre ne
   lève aucune erreur.

CHEMIN MOTEUR
-------------
W40KEngine avec la même config que train.py (ArmageddonAgent, x1_debug, scénarios bot, résolution
d'env héritée du .env/config.json). BotControlledEnv absent : les deux joueurs reçoivent des
actions aléatoires depuis la même graine, ce qui suffit à garantir la reproductibilité. La
couverture est le chemin MASQUE+OBS du moteur, pas la politique apprise.

COÛT DE RÉFÉRENCE (machine dev)
---------------------------------
~10-20 s pour N_STEPS = 80, sans W40K_MASK_VERIFY.
~45-90 s avec W40K_MASK_VERIFY=1 (×2,6 mesuré dans engine/mask_verification.py).
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Callable, Optional
import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

# ── Constantes ────────────────────────────────────────────────────────────────────────────────

AGENT_KEY = "ArmageddonAgent"
TRAINING_CONFIG = "x1_debug"
SEED = 42
N_STEPS = 80  # ~1 épisode ; balancé temps/couverture


# ── Fabrication de l'environnement ───────────────────────────────────────────────────────────

def _make_engine(seed: int):
    """W40KEngine sur le chemin exact de train.py (x1_debug, scénarios bot, résolution config).

    Sans BotControlledEnv : les deux joueurs sont pilotés par le rng appelant. Suffisant pour
    vérifier la reproductibilité masque+obs.
    """
    from config_loader import get_config_loader
    from ai.training_utils import get_scenario_list_for_phase
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    config = get_config_loader()
    scenario_list = get_scenario_list_for_phase(
        config, AGENT_KEY, TRAINING_CONFIG, scenario_type="bot"
    )
    if not scenario_list:
        pytest.skip(
            f"Aucun scénario bot trouvé pour {AGENT_KEY}/{TRAINING_CONFIG}. "
            "Vérifier config/agents/ArmageddonAgent/scenarios/training/."
        )

    eng = W40KEngine(
        rewards_config=AGENT_KEY,
        training_config_name=TRAINING_CONFIG,
        controlled_agent=AGENT_KEY,
        scenario_file=scenario_list[0],
        unit_registry=UnitRegistry(),
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    eng.reset(seed=seed)
    return eng


# ── Capture des empreintes ────────────────────────────────────────────────────────────────────

def _hash_step(mask: np.ndarray, obs: dict) -> str:
    """md5 de (mask, obs) — stable entre runs, suffisant pour détecter toute divergence bit-à-bit."""
    h = hashlib.md5()
    h.update(mask.tobytes())
    for key in sorted(obs.keys()):
        h.update(np.asarray(obs[key]).tobytes())
    return h.hexdigest()


def _capture_fingerprints(
    seed: int,
    n_steps: int,
    mask_transform: Optional[Callable[[np.ndarray], np.ndarray]] = None,
) -> list[str]:
    """Retourne la liste des hash(masque, obs_post_step) pour n_steps.

    `mask_transform` permet d'injecter une mutation dans le masque avant hachage ET sélection
    d'action — les états suivants divergent, et toute modification est capturée.

    Réinitialisation déterministe entre épisodes : seed + 1000 * episode_index.
    """
    rng = np.random.default_rng(seed)
    eng = _make_engine(seed)
    fingerprints: list[str] = []
    episode_count = 0

    for _ in range(n_steps):
        mask = eng.get_action_mask()

        if mask_transform is not None:
            mask_hashed = mask_transform(mask.copy())
            valid = np.flatnonzero(mask_hashed)
            if valid.size == 0:
                # la mutation a vidé le masque : on joue une action originale valide
                # mais on hache le masque muté — la divergence reste capturée
                valid = np.flatnonzero(mask)
        else:
            mask_hashed = mask
            valid = np.flatnonzero(mask)

        if valid.size == 0:
            break
        action = int(rng.choice(valid))

        next_obs, _, terminated, truncated, _ = eng.step(action)
        fingerprints.append(_hash_step(mask_hashed, next_obs))

        if terminated or truncated:
            episode_count += 1
            eng.reset(seed=seed + episode_count * 1000)

    return fingerprints


# ── Invariant 1 : reproductibilité ───────────────────────────────────────────────────────────

def test_parity_stable_across_two_runs() -> None:
    """Deux runs à graine fixe produisent exactement les mêmes empreintes masque+obs.

    Critère : toute la liste de hashes est identique, step par step. Un seul hash différent
    indique que le moteur n'est pas déterministe sur ce chemin — et qu'une optimisation qui
    semble passer vert a pu altérer la sémantique sans qu'on le voit.

    Vérifie aussi : liste non vide (>= 10 steps produits) et hashes non-constants
    (états distincts au fil du jeu) — deux gardes contre un vert vacant.
    """
    run_a = _capture_fingerprints(SEED, N_STEPS)
    run_b = _capture_fingerprints(SEED, N_STEPS)

    assert len(run_a) >= 10, (
        f"Seulement {len(run_a)} steps capturés sur {N_STEPS} demandés — "
        "le moteur s'est probablement bloqué."
    )
    assert len(set(run_a)) > 1, "Tous les hashes sont identiques — l'obs est invariante (vert vacant)."
    assert len(run_a) == len(run_b), (
        f"Longueurs différentes : {len(run_a)} vs {len(run_b)} — "
        "le moteur n'a pas produit le même nombre de steps à graine fixe."
    )
    first_diff = next((i for i, (a, b) in enumerate(zip(run_a, run_b)) if a != b), None)
    assert first_diff is None, (
        f"Divergence masque+obs au step {first_diff} (sur {len(run_a)}) — "
        "le moteur n'est pas déterministe à graine fixe sur ce chemin."
    )


# ── Invariant 2 : détection de mutation ──────────────────────────────────────────────────────

def _flip_first_true_bit(mask: np.ndarray) -> np.ndarray:
    """Flippe le premier bit vrai du masque — mutation minimale, toujours présente."""
    idx = np.flatnonzero(mask)
    if idx.size:
        mask[idx[0]] = False
    return mask


def test_parity_mutation_detected() -> None:
    """Un patch qui flippe un bit du masque fait diverger les hashes — le harnais le détecte.

    ROUGE attendu si la mutation est active : les hashes mutés doivent différer des propres.
    Cette propriété est le critère de clôture §0.2 : harnais rouge avec mutation, vert sans.
    """
    clean = _capture_fingerprints(SEED, N_STEPS)
    mutated = _capture_fingerprints(SEED, N_STEPS, mask_transform=_flip_first_true_bit)

    # Le harnais doit DÉTECTER la mutation : au moins un hash doit différer.
    n_divergent = sum(1 for a, b in zip(clean, mutated) if a != b)
    assert n_divergent > 0, (
        "Le harnais n'a détecté AUCUNE divergence alors qu'un bit du masque a été flippé "
        "à chaque step — le test ne peut pas servir de verrou de parité."
    )


# ── Invariant 3 : gate mask_verification armée ───────────────────────────────────────────────

def test_mask_verification_gate_is_not_a_noop(monkeypatch) -> None:
    """Avec W40K_MASK_VERIFY=1, verify_memoised_move_cell_map est appelée au moins une fois.

    Le gate doit être ARMÉ (count > 0) et ne pas lever sur un run propre (pas de faux positif).
    Si count == 0 après N steps, c'est que le gate a été outrepassé, que le module a été importé
    avant que l'env var soit posée, ou que le chemin moteur ne l'atteint pas.
    """
    from engine import mask_verification as mv

    monkeypatch.setenv("W40K_MASK_VERIFY", "1")

    call_count = 0
    original_verify = mv.verify_memoised_move_cell_map

    def _counting_verify(game_state, squad_id, memoised):
        nonlocal call_count
        call_count += 1
        original_verify(game_state, squad_id, memoised)

    monkeypatch.setattr(mv, "verify_memoised_move_cell_map", _counting_verify)
    # Le module shared_utils importe verify_memoised_move_cell_map au niveau module ; on
    # redirige aussi la référence que shared_utils tient déjà pour que le patch soit effectif.
    import engine.phase_handlers.shared_utils as su
    monkeypatch.setattr(su, "verify_memoised_move_cell_map", _counting_verify)

    # Run propre : aucune erreur ne doit être levée.
    run = _capture_fingerprints(SEED, N_STEPS)

    assert len(run) >= 10, f"Seulement {len(run)} steps — le moteur s'est bloqué."
    assert call_count > 0, (
        f"verify_memoised_move_cell_map n'a jamais été appelée sur {len(run)} steps avec "
        "W40K_MASK_VERIFY=1 — le gate n'est pas armé sur ce chemin."
    )


# ── Invariant 4 : remise à zéro du buffer scratch d'observation (item 1.7) ───────────────────

def test_obs_scratch_buffer_is_zeroed_before_reuse() -> None:
    """Le buffer scratch de _empty_squad_observation est remis à zéro avant chaque réutilisation.

    ROUGE si le `.fill(0)` de `_empty_squad_observation` est supprimé : les valeurs empoisonnées
    survivraient au second appel et corrompraient l'observation d'une escouade absente.
    VERT avec le fill(0) : le second appel renvoie toujours des zéros.

    Testé directement sur le builder (pas de game_state requis) pour que l'échec soit immédiat
    et la cause lisible sans trace de stack moteur.
    """
    from engine.observation_builder import ObservationBuilder

    builder = ObservationBuilder(
        {"observation_params": {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}}
    )

    # Premier appel : initialise _obs_scratch
    obs_first = builder._empty_squad_observation()

    # Poison : on écrit 99.0 dans TOUS les tableaux du scratch
    for arr in obs_first.values():
        arr.fill(99.0)

    # Deuxième appel : doit remettre à zéro, même si le buffer contient 99.0
    obs_second = builder._empty_squad_observation()

    # obs_second EST obs_first (même dict) — le test vérifie que fill(0) a bien agi
    for key, arr in obs_second.items():
        assert np.all(arr == 0.0), (
            f"Buffer scratch non remis à zéro pour la clé '{key}' : "
            f"valeur max = {arr.max()} (attendu 0.0). "
            "Vérifier que _empty_squad_observation appelle arr.fill(0) sur chaque tableau."
        )


def test_unit_entity_scratch_zeroed_between_entities() -> None:
    """Les buffers scratch de _encode_unit_entity ne fuient pas d'une entité à la suivante.

    ROUGE si les `.fill(0)` de `_encode_unit_entity` sont supprimés : la valeur 99.0 empoisonnée
    dans `_unit_ent_cont` avant le premier encode apparaîtrait dans les fields non écrits du
    résultat (ex. `effective_range`, écrit SEULEMENT pour les entités ennemies non actives),
    rendant l'observation d'une entité alliée active non nulle sur ces fields.
    VERT avec les fill(0) : les fields non écrits restent à 0 quel que soit le poison initial.

    Vérifié via le moteur réel (N_STEPS steps) : on empoisonne le buffer AVANT chaque encode
    via un monkeypatch, et on contrôle la parité bit-à-bit avec un run propre.
    """
    clean = _capture_fingerprints(SEED, N_STEPS)

    # Run "empoisonné" : avant chaque appel à _encode_unit_entity, on remplit le buffer scratch
    # avec 99.0 pour simuler un résidu. Si fill(0) est en place, le résultat doit être identique
    # au run propre ; sinon, les fields non écrits porteront 99.0 et les hashes divergeront.
    import engine.observation_builder as obs_mod
    original_encode = obs_mod.ObservationBuilder._encode_unit_entity

    def _poisoning_encode(self, *args, **kwargs):
        # Poison avant l'appel : simule un buffer non remis à zéro
        self._unit_ent_cont.fill(99.0)
        self._unit_ent_bin.fill(99.0)
        return original_encode(self, *args, **kwargs)

    obs_mod.ObservationBuilder._encode_unit_entity = _poisoning_encode
    try:
        poisoned = _capture_fingerprints(SEED, N_STEPS)
    finally:
        obs_mod.ObservationBuilder._encode_unit_entity = original_encode

    assert len(clean) >= 10, f"Seulement {len(clean)} steps — le moteur s'est bloqué."
    assert len(clean) == len(poisoned), (
        f"Longueurs différentes : {len(clean)} vs {len(poisoned)}"
    )
    first_diff = next((i for i, (a, b) in enumerate(zip(clean, poisoned)) if a != b), None)
    assert first_diff is None, (
        f"Divergence au step {first_diff} : le poison 99.0 a survécu dans l'observation — "
        "le buffer scratch n'est pas remis à zéro avant encode."
    )
