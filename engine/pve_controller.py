#!/usr/bin/env python3
"""
pve_controller.py - PvE mode AI opponent
"""

import numpy as np
import os
from typing import Dict, Any, Optional, Tuple, List, cast
from engine.phase_handlers.shared_utils import is_unit_alive
from shared.data_validation import require_key
from engine.action_decoder import ActionValidationError
from config_loader import get_config_loader

class PvEController:
    """Controls AI opponent in PvE mode."""
    
    def __init__(self, config: Dict[str, Any], unit_registry=None):
        self.config = config
        self.ai_model = None
        self.macro_model = None
        self.micro_models = {}
        self.micro_model_paths = {}
        # model_path -> chemin du pkl VecNormalize per-model (V11 §0.35), ou None si le modele
        # joue en obs brutes. Resolu au CHARGEMENT (`_resolve_vec_stats_path`) : a l'inference,
        # un chemin inconnu est une erreur, jamais un repli silencieux.
        self.micro_model_vec_stats: Dict[str, Optional[str]] = {}
        # model_path -> objet VecNormalize charge (obs Dict du pipeline squad). Cache pur : il
        # evite de depickler les stats a chaque decision, il ne decide rien.
        self._micro_model_vec_normalize: Dict[str, Any] = {}
        self.macro_model_key = None
        self.unit_registry = unit_registry
        self.quiet = config.get("quiet", True)

    # ============================================================================
    # MODEL LOADING
    # ============================================================================
    
    def load_ai_model_for_pve(self, game_state: Dict[str, Any], engine):
        """Load trained AI model for PvE Player 2 - with diagnostic logging."""
        debug_mode = require_key(game_state, "debug_mode")
        if not isinstance(debug_mode, bool):
            raise ValueError(f"debug_mode must be boolean (got {type(debug_mode).__name__})")
        
        if debug_mode:
            print(f"DEBUG: _load_ai_model_for_pve called")
        
        try:
            from sb3_contrib import MaskablePPO
            from sb3_contrib.common.wrappers import ActionMasker
            if debug_mode:
                print(f"DEBUG: MaskablePPO import successful")
            
            config = get_config_loader()
            models_root = config.get_models_root()
            # PvE runtime is explicitly micro-only (CoreAgent); MacroController is disabled.
            self.macro_model_key = None
            self.macro_model = None
            self.ai_model = None
            engine._ai_model = None
            if not self.quiet:
                print("PvE: Macro controller disabled (micro-only CoreAgent mode)")
            
            # Wrap engine with ActionMasker : le masque est celui du pipeline squad
            # (`W40KEngine.get_action_mask` -> `get_squad_action_mask_and_eligible_units`).
            def mask_fn(env):
                return env.get_action_mask()
            masked_env = ActionMasker(engine, mask_fn)
            
            # Load micro models for all Player 2 unit types
            if not self.unit_registry:
                raise ValueError("unit_registry is required to load micro models for PvE")
            if "units_cache" not in game_state:
                raise KeyError("game_state missing required 'units_cache' field")
            unit_by_id = {str(u["id"]): u for u in game_state["units"]}
            micro_model_keys = set()
            for unit_id, entry in game_state["units_cache"].items():
                if entry["player"] == 2:
                    unit = unit_by_id.get(str(unit_id))
                    if not unit:
                        raise KeyError(f"Unit {unit_id} missing from game_state['units']")
                    unit_type = require_key(unit, "unitType")
                    micro_model_keys.add(self.unit_registry.get_model_key(unit_type))
            
            self.micro_models = {}
            self.micro_model_paths = {}
            self.micro_model_vec_stats = {}
            shared_micro_model_key = require_key(self.config, "controlled_agent")
            if not isinstance(shared_micro_model_key, str) or not shared_micro_model_key.strip():
                raise ValueError(
                    f"controlled_agent must be a non-empty string in PvE config "
                    f"(got {shared_micro_model_key!r})"
                )
            shared_micro_model_storage_key = config._resolve_agent_config_key(
                shared_micro_model_key.strip()
            )
            for model_key in micro_model_keys:
                model_path = os.path.join(
                    models_root,
                    shared_micro_model_storage_key,
                    f"model_{shared_micro_model_storage_key}.zip"
                )
                if debug_mode:
                    print(
                        f"DEBUG: Micro model key '{model_key}' mapped to shared "
                        f"storage key '{shared_micro_model_storage_key}'"
                    )
                    print(f"DEBUG: Micro model path: {model_path}")
                    print(f"DEBUG: Micro model exists: {os.path.exists(model_path)}")
                if not os.path.exists(model_path):
                    raise FileNotFoundError(f"Micro model required for PvE mode not found: {model_path}")
                self.micro_models[model_key] = MaskablePPO.load(model_path, env=masked_env)
                self.micro_model_paths[model_key] = model_path
                self.micro_model_vec_stats[model_path] = self._resolve_vec_stats_path(model_path)

            # Marker to indicate PvE micro models are loaded (used by W40KEngine reset guard).
            self.ai_model = self.micro_models
            
            if not self.quiet:
                print(f"PvE: Loaded micro models: {sorted(self.micro_models.keys())}")
                
        except Exception as e:
            print(f"DEBUG: _load_ai_model_for_pve exception: {e}")
            print(f"DEBUG: Exception type: {type(e).__name__}")
            # Set ai_model to None on any failure
            self.ai_model = None
            raise  # Re-raise to see the full error
    
    # ============================================================================
    # AI DECISION MAKING
    # ============================================================================

    def is_ready_for_decision(self) -> bool:
        """Return whether PvE controller has the required models for inference."""
        return bool(self.micro_models)
    
    def make_ai_decision(self, game_state: Dict[str, Any], engine) -> Dict[str, Any]:
        """
        AI decision logic - replaces human clicks with model predictions.

        Pipeline SQUAD (V11) : observation en tenseurs d'entites + grille, masque a 41 actions,
        decodage par `convert_squad_action`. C'est la MEME machine que l'entrainement
        (`W40KEngine.step`) et que l'evaluation (`ai/bot_evaluation`) — un bot conduit par un
        autre contrat que celui sur lequel la politique a ete entrainee joue autre chose que ce
        qu'elle a appris.

        L'observation est construite AVANT le masque : `_build_observation_and_mask` peut avancer la
        phase quand le pool est vide, et le masque doit decrire l'etat sur lequel le modele a decide.
        C'est pourquoi le masque SORT de la construction d'observation au lieu d'etre recalcule
        apres elle : les deux proviennent du meme passage, donc du meme etat, par construction. Un
        second calcul redonnait le bon resultat tant que rien ne s'executait entre les deux — une
        propriete qui se demontre par lecture a chaque modification, au lieu d'etre garantie.
        """
        if not self.micro_models:
            raise RuntimeError("Micro models not loaded for PvE")

        micro_obs, mask_used = engine._build_observation_and_mask()
        if mask_used is not None:
            action_mask, eligible_units = mask_used
        else:
            # Chemins ou l'observation ne construit aucun masque (decision en attente, phase de
            # deploiement : l'observateur y est designe autrement). Il faut donc le construire.
            action_mask, eligible_units = engine.action_decoder.get_squad_action_mask_and_eligible_units(
                game_state
            )
        if not eligible_units and not action_mask.any():
            raise RuntimeError("No eligible units and no valid action for PvE decision")
        # Squad actif = 1er eligible, EXACTEMENT la convention de `_build_observation`, du masque
        # et de `convert_squad_action` : en choisir un autre desynchroniserait obs, masque et
        # decodage. La phase command n'a pas de pool (zone intents + wait uniquement) ; le squad
        # ne sert alors qu'a resoudre le modele, d'ou le repli sur la 1re unite vivante du joueur.
        if eligible_units:
            selected_unit_id = str(require_key(eligible_units[0], "id"))
        else:
            current_player = int(require_key(game_state, "current_player"))
            units_cache = require_key(game_state, "units_cache")
            selected_unit_id = next(
                (
                    str(uid)
                    for uid, entry in units_cache.items()
                    if int(require_key(entry, "player")) == current_player
                    and is_unit_alive(str(uid), game_state)
                ),
                "",
            )
            if not selected_unit_id:
                raise RuntimeError(
                    f"No living unit for player {current_player} to resolve PvE micro model"
                )
        micro_model, micro_model_path = self._get_micro_model_and_path_for_unit_id(
            selected_unit_id, game_state, engine
        )
        micro_obs = self._normalize_obs_for_inference(micro_obs, micro_model_path)
        micro_prediction = micro_model.predict(micro_obs, action_masks=action_mask, deterministic=True)
        if isinstance(micro_prediction, tuple) and len(micro_prediction) >= 1:
            predicted_action = micro_prediction[0]
        elif hasattr(micro_prediction, 'item'):
            predicted_action = cast(Any, micro_prediction).item()
        else:
            predicted_action = micro_prediction

        # Apply action mask like in training - force valid action if predicted action is invalid
        if game_state.get("debug_mode", False):
            from engine.game_utils import add_debug_file_log
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            current_phase = game_state.get("phase", "?")
            mask_indices = [i for i, v in enumerate(action_mask) if v]
            add_debug_file_log(
                game_state,
                f"[AI_DECISION DEBUG] E{episode} T{turn} P2 make_ai_decision: "
                f"phase={current_phase} predicted_action={predicted_action} "
                f"mask_true_indices={mask_indices}"
            )
        try:
            action_int = engine.action_decoder.normalize_action_input(
                raw_action=predicted_action,
                phase=require_key(game_state, "phase"),
                source="pve_controller",
                action_space_size=len(action_mask),
            )
            engine.action_decoder.validate_action_against_mask(
                action_int=action_int,
                action_mask=action_mask,
                phase=require_key(game_state, "phase"),
                source="pve_controller",
                unit_id=selected_unit_id,
            )
        except ActionValidationError as e:
            raise RuntimeError(f"PvE action validation failed: {e}") from e

        # Aucun garde supplementaire sur la valeur de l'action : les zone intents (26-40) font
        # partie de l'espace d'action de la politique squad et ne sont ouverts qu'en phase
        # command, par le masque lui-meme. Le masque est l'autorite — il vient d'etre verifie par
        # `validate_action_against_mask`, qui leve au lieu de replier sur une action « sure ».
        semantic_action = engine.action_decoder.convert_squad_action(
            action_int, game_state, eligible_units=eligible_units
        )
        if game_state.get("debug_mode", False):
            from engine.game_utils import add_debug_file_log
            episode = game_state.get("episode_number", "?")
            turn = game_state.get("turn", "?")
            add_debug_file_log(
                game_state,
                f"[AI_DECISION DEBUG] E{episode} T{turn} P2 make_ai_decision: "
                f"action_int={action_int} semantic_action={semantic_action}"
            )
        # Aucune reecriture de l'identite de l'unite ici : la semantique squad porte deja
        # `squad_id` (ou `unitId` pour deploy_unit), pose par `convert_squad_action` depuis le
        # MEME pool que le masque. Forcer `unitId` ecrasait la cible d'actions qui n'en ont pas
        # (zone_intent, command_wait).
        return semantic_action

    def _evaluate_rule_choice_option_value(
        self, unit_id: str, game_state: Dict[str, Any], engine
    ) -> float:
        """
        Evaluate one rule-choice option using the policy value head.

        The selected option is expected to already be applied in game_state before this call.
        """
        micro_model, micro_model_path = self._get_micro_model_and_path_for_unit_id(
            unit_id, game_state, engine
        )
        # Observation CANONIQUE du pipeline squad (celle de l'escouade active), la seule sur
        # laquelle la tete de valeur a ete entrainee. On ne construit PAS l'obs de `unit_id` a la
        # place : la grille egocentrique relit la carte de cellules posee par le masque (§0.32
        # T-K), qui n'existe que pour l'escouade active — la reconstruire ici ferait diverger
        # l'obs du masque, ce que la convention interdit explicitement.
        # La branche « pool vide -> advance_phase » de `_build_observation` est hors d'atteinte
        # ici : un choix de regle n'est propose que pendant une activation, donc pool non vide.
        unit_observation = engine._build_observation()
        unit_observation = self._normalize_obs_for_inference(unit_observation, micro_model_path)
        obs_tensor, _ = micro_model.policy.obs_to_tensor(unit_observation)
        import torch
        with torch.no_grad():
            value_tensor = micro_model.policy.predict_values(obs_tensor)
        value_array = value_tensor.detach().cpu().numpy().reshape(-1)
        if value_array.size != 1:
            raise ValueError(
                f"Expected scalar policy value for rule choice evaluation, got shape {value_array.shape}"
            )
        option_value = float(value_array[0])
        if np.isnan(option_value):
            raise ValueError("Policy value for rule choice evaluation is NaN")
        return option_value

    def select_rule_choice_with_policy(
        self, prompt: Dict[str, Any], game_state: Dict[str, Any], engine
    ) -> str:
        """
        Select one rule-choice option with trained policy evaluation.

        Strategy:
        - Simulate each candidate option by setting `_selected_granted_rule_id`.
        - Build the unit observation for that simulated state.
        - Score with the micro-policy value head.
        - Pick the option with the highest value (deterministic tie-break by display_rule_id).
        """
        if not self.micro_models:
            raise RuntimeError("Micro models not loaded for policy-based rule choice")

        options = require_key(prompt, "options")
        if not isinstance(options, list) or not options:
            raise ValueError(f"Rule choice prompt requires non-empty options list, got: {options!r}")
        unit_id = str(require_key(prompt, "unit_id"))
        rule_id = require_key(prompt, "rule_id")
        if not isinstance(rule_id, str) or not rule_id.strip():
            raise ValueError(f"Rule choice prompt requires non-empty rule_id, got: {rule_id!r}")

        unit = engine._get_unit_by_id(unit_id)
        if unit is None:
            raise KeyError(f"Cannot evaluate rule choice: unit {unit_id} not found")
        unit_rules = require_key(unit, "UNIT_RULES")
        if not isinstance(unit_rules, list):
            raise TypeError(f"UNIT_RULES must be a list for unit {unit_id}")

        source_rule_entry = None
        for unit_rule in unit_rules:
            if require_key(unit_rule, "ruleId") == rule_id:
                source_rule_entry = unit_rule
                break
        if source_rule_entry is None:
            raise KeyError(f"Rule '{rule_id}' not found in UNIT_RULES for unit {unit_id}")

        previous_selected_rule_id = source_rule_entry.get("_selected_granted_rule_id")
        option_scores: List[Tuple[str, float]] = []
        try:
            for option in options:
                display_rule_id = require_key(option, "display_rule_id")
                if not isinstance(display_rule_id, str) or not display_rule_id.strip():
                    raise ValueError(f"Invalid display_rule_id in rule choice option: {option!r}")
                normalized_display_rule_id = display_rule_id.strip()
                source_rule_entry["_selected_granted_rule_id"] = normalized_display_rule_id
                option_value = self._evaluate_rule_choice_option_value(unit_id, game_state, engine)
                option_scores.append((normalized_display_rule_id, option_value))
        finally:
            source_rule_entry["_selected_granted_rule_id"] = previous_selected_rule_id

        if not option_scores:
            raise ValueError(f"No option scores computed for prompt: {prompt!r}")

        best_value = max(score for _, score in option_scores)
        best_display_rule_ids = [
            display_rule_id for display_rule_id, score in option_scores if score == best_value
        ]
        if not best_display_rule_ids:
            raise ValueError(f"No best option found despite computed scores: {option_scores!r}")
        return sorted(best_display_rule_ids)[0]

    def _get_micro_model_and_path_for_unit_id(
        self, unit_id: str, game_state: Dict[str, Any], engine=None
    ):
        """Get micro model and its path for a specific unit id (for VecNormalize inference).
        If model_key is not loaded, attempts lazy load when engine is provided."""
        unit_by_id = {str(u["id"]): u for u in game_state["units"]}
        unit = unit_by_id.get(str(unit_id))
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        if not self.unit_registry:
            raise ValueError("unit_registry is required to resolve micro model key")
        unit_type = require_key(unit, "unitType")
        model_key = self.unit_registry.get_model_key(unit_type)
        if model_key not in self.micro_models:
            if engine is not None:
                self._load_micro_model_lazy(model_key, engine)
            else:
                raise KeyError(f"Micro model not loaded for model_key={model_key}")
        model_path = self.micro_model_paths.get(model_key, "")
        return self.micro_models[model_key], model_path

    def _load_micro_model_lazy(self, model_key: str, engine) -> None:
        """Load a single micro model on demand (for roster change after initial load)."""
        from sb3_contrib import MaskablePPO
        from sb3_contrib.common.wrappers import ActionMasker

        def mask_fn(env):
            return env.get_action_mask()

        masked_env = ActionMasker(engine, mask_fn)
        config = get_config_loader()
        models_root = config.get_models_root()
        shared_micro_model_key = require_key(self.config, "controlled_agent")
        if not isinstance(shared_micro_model_key, str) or not shared_micro_model_key.strip():
            raise ValueError(
                f"controlled_agent must be a non-empty string in PvE config "
                f"(got {shared_micro_model_key!r})"
            )
        model_storage_key = config._resolve_agent_config_key(shared_micro_model_key.strip())
        model_path = os.path.join(
            models_root,
            model_storage_key,
            f"model_{model_storage_key}.zip",
        )
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Micro model required for PvE mode not found: {model_path}"
            )
        self.micro_models[model_key] = MaskablePPO.load(model_path, env=masked_env)
        self.micro_model_paths[model_key] = model_path
        self.micro_model_vec_stats[model_path] = self._resolve_vec_stats_path(model_path)
        if not self.quiet:
            print(
                f"PvE: Lazy-loaded micro model for '{model_key}' "
                f"using shared model '{model_storage_key}'"
            )

    def _resolve_vec_stats_path(self, model_path: str) -> Optional[str]:
        """Décide AU CHARGEMENT si les obs de ce modèle seront normalisées (V11 §0.35).

        - pkl per-model présent → son chemin : l'inférence normalisera avec CES stats.
        - pkl LEGACY partagé (`vec_normalize.pkl`) présent sans per-model → erreur : il peut
          appartenir à n'importe quel modèle du dossier, le charger rejouerait exactement le
          bug §0.35. À migrer explicitement (renommer) si et seulement si on en est sûr.
        - aucun pkl → None : le modèle joue en obs brutes (entraîné sans VecNormalize). C'est
          un cas métier, pas un repli — mais on le dit, pour qu'une perte d'artefact ne passe
          pas pour un choix.
        """
        from ai.vec_normalize_utils import get_vec_normalize_path

        vec_path = get_vec_normalize_path(model_path)
        if os.path.exists(vec_path):
            return vec_path
        legacy_path = os.path.join(os.path.dirname(model_path), "vec_normalize.pkl")
        if os.path.exists(legacy_path):
            raise FileNotFoundError(
                f"PvE: stats VecNormalize per-model absentes ({vec_path}) mais un pkl LEGACY "
                f"partagé existe ({legacy_path}). Il peut appartenir à un AUTRE modèle du "
                f"dossier (V11 §0.35) : le renommer en "
                f"'{os.path.basename(vec_path)}' explicitement si ces stats sont bien celles "
                f"de ce modèle, sinon ré-entraîner."
            )
        if not self.quiet:
            print(f"PvE: aucune stat VecNormalize pour {model_path} — obs servies brutes")
        return None

    def _normalize_obs_for_inference(
        self, obs: Dict[str, np.ndarray], model_path: str
    ) -> Dict[str, np.ndarray]:
        """Normalise l'observation squad avec les stats DU modèle, résolues à son chargement.

        L'observation du pipeline squad est un Dict de tenseurs (V11 §0.30) et VecNormalize est
        entraînée avec `norm_obs_keys=["global_cont"]` (`ai/train._vec_norm_obs_keys`) : les
        tenseurs d'entités sont normalisés dans l'extracteur, la grille reste brute. On délègue
        donc à `VecNormalize.normalize_obs`, comme l'évaluation
        (`ai/bot_evaluation._build_eval_obs_normalizer_for_worker`), au lieu de réimplémenter la
        formule — deux implémentations dériveraient. L'objet est chargé une fois par modèle, pas
        à chaque décision.

        Aucun repli : un modèle jamais passé par `_resolve_vec_stats_path` est une erreur de
        flux (l'ancien code retournait l'obs brute sous un `except Exception`, faisant jouer
        en silence un modèle normalisé sur des obs brutes)."""
        if model_path not in self.micro_model_vec_stats:
            raise RuntimeError(
                f"PvE: modèle {model_path!r} non résolu au chargement — "
                f"_resolve_vec_stats_path n'a pas été appelé pour ce chemin."
            )
        stats_path = self.micro_model_vec_stats[model_path]
        if stats_path is None:
            return obs
        if not isinstance(obs, dict):
            raise TypeError(
                f"PvE: observation squad attendue sous forme de dict, reçu "
                f"{type(obs).__name__} — le pipeline mono-figurine n'existe plus."
            )
        vec_normalize = self._micro_model_vec_normalize.get(model_path)
        if vec_normalize is None:
            import pickle

            with open(stats_path, "rb") as stats_file:
                vec_normalize = pickle.load(stats_file)
            vec_normalize.training = False
            vec_normalize.norm_reward = False
            self._micro_model_vec_normalize[model_path] = vec_normalize
        return vec_normalize.normalize_obs(obs)
