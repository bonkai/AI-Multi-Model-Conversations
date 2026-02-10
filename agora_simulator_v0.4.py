# START OF FILE: agora_simulator_v1.5_modes.py
# -*- coding: utf-8 -*-
# agora_simulator_v1.5_modes.py (Added Simulation Modes, Removed Summary)

import requests
import json
import logging
import time
import os
import random
import traceback # For better error logging within topic loops
from datetime import datetime

# --- Configuration Loading ---
CONFIG_FILE = "config.json"

def load_config(filepath):
    """Loads configuration from a JSON file, including simulation mode."""
    logging.info(f"Loading configuration from {filepath}")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logging.info("Configuration loaded successfully.")

        # Add defaults for optional params if missing
        config.setdefault("simulation_mode", "debate") # <<< Default mode
        config.setdefault("llm_judge_temperature", 0.5)
        config.setdefault("llm_moderator_temperature", 0.4) # Still relevant if mode is debate
        config.setdefault("weight_initial", 1.0)
        config.setdefault("weight_decrement_factor", 0.3)
        config.setdefault("weight_increment_amount", 0.05)
        config.setdefault("moderator_history_lookback", 5)
        config.setdefault("history_lookback", 50)
        config.setdefault("llm_timeout_seconds", 180)
        config.setdefault("turn_delay_seconds", 1)
        config.setdefault("log_moderator_output", False)
        config.setdefault("llm_max_predict_tokens", 250)
        config.setdefault("zero_turn_override_threshold", 3)

        # --- Config Validation ---
        required_keys = [
            "personas_file", "api_url", "model_name", "max_turns",
            "simulation_topics", # Expects a list of topics/tasks
            "base_log_directory", "llm_temperature",
            "llm_max_predict_tokens", "simulation_mode" # Mode is now required
            # Weight/Moderator keys only strictly required if mode is 'debate'
        ]
        if config.get("simulation_mode") == "debate":
             required_keys.extend([
                 "weight_initial", "weight_decrement_factor", "weight_increment_amount",
                 "moderator_history_lookback", "zero_turn_override_threshold", "history_lookback"
             ])
        # Remove duplicates just in case
        required_keys = list(set(required_keys))

        missing = [key for key in required_keys if key not in config]
        if missing:
            raise ValueError(f"Missing required keys in config file for mode '{config.get('simulation_mode')}': {', '.join(missing)}")

        # Validate simulation_topics
        if not isinstance(config.get("simulation_topics"), list) or not config.get("simulation_topics"):
             raise ValueError("'simulation_topics' must be a non-empty list.")

        # Validate mode
        valid_modes = ["debate", "collaborative_build", "competitive_refine"]
        if config.get("simulation_mode") not in valid_modes:
            raise ValueError(f"Invalid 'simulation_mode'. Must be one of: {valid_modes}")

        # Validate numeric types
        numeric_keys = ["max_turns", "history_lookback", "moderator_history_lookback", "llm_temperature", "llm_judge_temperature", "llm_moderator_temperature", "weight_initial", "weight_decrement_factor", "weight_increment_amount", "llm_max_predict_tokens", "llm_timeout_seconds", "turn_delay_seconds", "zero_turn_override_threshold"]
        for key in numeric_keys:
            # Only validate if key exists (some are optional depending on mode)
            if key in config and not isinstance(config[key], (int, float)):
                 raise ValueError(f"Config key '{key}' must be numeric. Found: {type(config[key])}")

        return config
    except FileNotFoundError: logging.error(f"FATAL: Config file not found: {filepath}"); return None
    except json.JSONDecodeError as e: logging.error(f"FATAL: Could not decode JSON: {filepath}: {e}"); return None
    except ValueError as ve: logging.error(f"FATAL: Config error: {ve}"); return None
    except Exception as e: logging.error(f"FATAL: Unexpected error loading config: {e}", exc_info=True); return None

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Function to Load & Filter Personas ---
def load_and_filter_personas(filepath):
    """Loads personas from JSON and separates them by role."""
    # No changes needed here, roles are still used for filtering
    # The meaning/prompting changes based on simulation_mode later
    logging.info(f"Loading personas from {filepath}")
    debaters = []; judges = []; moderator = None
    try:
        with open(filepath, 'r', encoding='utf-8') as f: all_personas = json.load(f)
        if not isinstance(all_personas, list): raise TypeError("Personas file not list.")
        for i, p in enumerate(all_personas):
            if not isinstance(p, dict) or not all(k in p for k in ['persona_id', 'display_name', 'role', 'core_prompt']): logging.warning(f"Skipping invalid persona at index {i}"); continue
            role = p.get("role")
            # Treat all non-judge/non-moderator as participants for build/refine modes
            if role == "debater": debaters.append(p)
            elif role == "judge": judges.append(p)
            elif role == "moderator":
                if moderator is None: moderator = p; logging.info(f"Found moderator: {p.get('display_name')}")
                else: logging.warning(f"Multiple moderators. Using first ('{moderator.get('persona_id')}'). Ignoring '{p.get('persona_id')}'.")
            # else: Allow other roles silently, they won't be used unless code is adapted
        if not debaters: logging.warning("No 'debater' (participant) personas found.")
        # Judges/Moderator might be optional depending on mode
        logging.info(f"Loaded {len(debaters)} debaters/participants, {len(judges)} judges, {1 if moderator else 0} moderator(s).")
        return debaters, judges, moderator
    except FileNotFoundError: logging.error(f"Error: Personas file not found: {filepath}"); return None, None, None
    except json.JSONDecodeError as e: logging.error(f"Error: Could not decode JSON: {filepath}: {e}"); return None, None, None
    except TypeError as e: logging.error(f"Error: Personas file content is not a list: {e}"); return None, None, None
    except Exception as e: logging.error(f"Error loading personas: {e}", exc_info=True); return None, None, None


# --- Function to Interact with Ollama LLM (MODIFIED for different modes/contexts) ---
def get_llm_response(persona, context, current_topic_or_task, config, role_context="debater"):
    """
    Gets response from Ollama, handling different roles and simulation modes.

    Args:
        persona (dict): The persona dictionary.
        context: Varies by mode/role:
                 - debate/debater: list of turn dicts
                 - debate/moderator: dict {"history": list, "weights": dict, "last_speaker_id": str|None, "turn_counts": dict}
                 - debate/judge: transcript string
                 - debate/final_statement: transcript string
                 - collaborative_build/debater: string (artifact built so far)
                 - competitive_refine/debater: string (last version of artifact)
        current_topic_or_task (str): The topic for debate or task description.
        config (dict): The loaded configuration dictionary.
        role_context (str): "debater", "judge", "moderator", "final_statement".

    Returns:
        str: The LLM's generated response text, or None on error.
    """
    simulation_mode = config.get("simulation_mode", "debate")
    persona_name = persona.get('display_name', 'Unknown Persona')
    logging.info(f"Requesting response for {persona_name} (Role: {role_context}, Mode: {simulation_mode})") # Log mode
    messages = []
    messages.append({"role": "system", "content": persona.get('core_prompt', 'You are helpful.')}) # Core prompt is crucial for mode!

    user_prompt_content = ""
    try:
        # --- Debate Mode Prompts ---
        if simulation_mode == "debate":
            if role_context == "debater":
                if not isinstance(context, list): raise TypeError("Debate/Debater context must be a list")
                if not context: user_prompt_content = f"Begin debate on: {current_topic_or_task}. As {persona_name}, make opening statement. **Concise.**"
                else:
                    messages.append({"role": "system", "content": f"Ongoing topic: {current_topic_or_task}"})
                    history_context_list = []
                    lookback = config.get("history_lookback", 50)
                    start_index = max(0, len(context) - lookback)
                    for turn in context[start_index:]: speaker = turn.get('speaker', 'Unk'); text = turn.get('text', ''); history_context_list.append(f"{speaker}: {text}")
                    history_context_str = "\n".join(history_context_list)
                    user_prompt_content = (f"History (up to {lookback} turns):\n{history_context_str}\n\nAs {persona_name}, respond. **Briefly.**")
            elif role_context == "judge" or role_context == "final_statement":
                 if not isinstance(context, str): raise TypeError(f"{role_context} context must be a string")
                 if role_context == "judge":
                      user_prompt_content = (f"Transcript (Topic: '{current_topic_or_task}'). Participants: {config.get('participant_names_for_judge_prompt', 'debaters')}. "
                                             f"Review, evaluate per criteria, declare winner, justify. **Keep judgment brief.**\n\n--- TRANSCRIPT ---\n{context}\n--- END ---\n\nYour judgment:")
                 else: # final_statement
                      user_prompt_content = (f"Topic: '{current_topic_or_task}'.\nTranscript below.\n"
                                             f"Considering the debate and your persona ({persona_name}), what is your **final concluding thought or stance on the topic itself**?\n"
                                             f"**Do not summarize.** State your final position concisely (1-3 sentences).\n\n"
                                             f"--- TRANSCRIPT ---\n{context}\n--- END ---\n\nYour final statement on the topic:")
            elif role_context == "moderator":
                if not isinstance(context, dict) or not all(k in context for k in ["history", "weights", "last_speaker_id", "turn_counts"]): raise TypeError("Mod context needs history, weights, last_speaker_id, turn_counts")
                history_snippet = context.get("history", []); weights_info = context.get("weights", {}); last_speaker_id = context.get("last_speaker_id"); turn_counts = context.get("turn_counts", {})
                history_text = "\n".join([f"{t.get('speaker', 'Unk')}: {t.get('text','')}" for t in history_snippet])
                participant_info_lines = []
                if isinstance(weights_info, dict):
                     for pid, weight_data in weights_info.items():
                          if isinstance(weight_data, (list, tuple)) and len(weight_data) == 2: name, weight = weight_data; turns = turn_counts.get(pid, 0); participant_info_lines.append(f"- {name} (ID: {pid}): Weight={weight:.2f}, Turns={turns}")
                          else: logging.warning(f"Skipping invalid weight data for pid {pid}")
                participant_info_text = "\n".join(participant_info_lines)
                user_prompt_content = (f"Topic: {current_topic_or_task}\nHistory:\n---\n{history_text}\n---\nParticipant Status:\n---\n{participant_info_text}\n---\n"
                                       f"Last speaker: {last_speaker_id if last_speaker_id else 'N/A'}.\n"
                                       f"Analyze context/status. Choose relevant next speaker (prioritize higher weight/lower turns, esp 0). **DO NOT choose '{last_speaker_id}'.** Output only 'NEXT_SPEAKER: persona_id'.")
            else: raise ValueError(f"Invalid role_context '{role_context}' for debate mode.")

        # --- Collaborative Build Mode Prompt ---
        elif simulation_mode == "collaborative_build":
             if role_context != "debater": raise ValueError("Only 'debater' role valid for collaborative_build mode.")
             if not isinstance(context, str): raise TypeError("collaborative_build context must be a string (artifact so far)")
             # Context is the artifact built so far
             artifact_so_far = context if context else "[Start of artifact]"
             user_prompt_content = (f"Task: {current_topic_or_task}\n\n"
                                    f"Current artifact state:\n---\n{artifact_so_far}\n---\n\n"
                                    f"As {persona_name}, your task is to **continue building** the artifact based on your specific instructions in the system prompt. "
                                    f"Focus on adding the next logical piece. Ensure your contribution fits coherently. **Keep your contribution concise.**")

        # --- Competitive Refine Mode Prompt ---
        elif simulation_mode == "competitive_refine":
             if role_context != "debater": raise ValueError("Only 'debater' role valid for competitive_refine mode.")
             if not isinstance(context, str): raise TypeError("competitive_refine context must be a string (last artifact version)")
             # Context is the *previous* version of the artifact
             previous_artifact = context if context else "[No previous version - create the first one!]"
             user_prompt_content = (f"Task: {current_topic_or_task}\n\n"
                                    f"The previous version of the artifact was:\n---\n{previous_artifact}\n---\n\n"
                                    f"As {persona_name}, your goal is to **generate an improved version** of this artifact based on your specific instructions in the system prompt. "
                                    f"Try to make it significantly better than the previous version according to your criteria. "
                                    f"**Output only the new, full version of the artifact.** Keep it concise.")
        else:
            raise ValueError(f"Invalid simulation_mode '{simulation_mode}'.")

        messages.append({"role": "user", "content": user_prompt_content})

    except (TypeError, ValueError) as e: logging.error(f"Prompt construction error for {role_context}/{simulation_mode} ({persona_name}): {e}"); return None
    except Exception as e: logging.error(f"Unexpected prompt error for {persona_name}: {e}", exc_info=True); return None

    # --- Determine Temperature ---
    temp_to_use = None
    try:
        # Simplified temp logic - persona first, then role default (if applicable), then global
        if "llm_params" in persona and "temperature" in persona["llm_params"]: temp_to_use = float(persona["llm_params"]["temperature"])
        elif role_context == "judge" and simulation_mode == "debate": temp_to_use = float(config["llm_judge_temperature"])
        elif role_context == "moderator" and simulation_mode == "debate": temp_to_use = float(config["llm_moderator_temperature"])
        else: temp_to_use = float(config["llm_temperature"]) # Global default for debaters/builders/refiners unless persona overrides
    except Exception as e: logging.warning(f"Temp setting error ({e}), using global default."); temp_to_use = float(config.get("llm_temperature", 0.7))
    logging.debug(f"Using temp {temp_to_use:.2f} for {persona_name}")

    # --- Construct Payload ---
    payload = { "model": config["model_name"], "messages": messages, "temperature": temp_to_use, "stream": False,
                "options": { "num_predict": config.get("llm_max_predict_tokens", 250) } }
    # Adjust token limits based on role/mode if needed
    if role_context == "moderator": payload["options"]["num_predict"] = 50
    if role_context == "final_statement": payload["options"]["num_predict"] = 150
    if simulation_mode == "competitive_refine": payload["options"]["num_predict"] = 300 # Allow longer refined artifacts maybe?
    logging.debug(f"Sending payload for {persona_name} (Role={role_context}, Mode={simulation_mode}, Temp={temp_to_use:.2f}): {json.dumps(payload, indent=2)}")

    # --- API Call and Response Handling ---
    try:
        response = requests.post( config["api_url"], json=payload, timeout=config.get("llm_timeout_seconds", 180) )
        response.raise_for_status(); result = response.json(); logging.debug(f"Raw response for {persona_name}: {result}")
        # Truncation check - avoid warning for moderator/final statement which have lower limits
        is_short_output_role = role_context in ["moderator", "final_statement"] or simulation_mode == "competitive_refine" # Assume refine might hit limit intentionally
        if not result.get('done', True) and not is_short_output_role : logging.warning(f"Response for {persona_name} might be truncated.")
        response_text = result.get('message', {}).get('content', '').strip()
        return response_text if response_text else f"({persona_name} silent.)" # Placeholder for empty response
    except requests.exceptions.Timeout: logging.error(f"Timeout for {persona_name}."); return None # Error = None
    except requests.exceptions.RequestException as e: logging.error(f"API Error for {persona_name}: {e}"); return None # Error = None
    except Exception as e: logging.error(f"LLM interaction error for {persona_name}: {e}", exc_info=True); return None # Error = None


# --- Function to Format Transcript ---
def format_transcript(structured_log, current_topic, include_final_statements=True):
    """Formats the debate log into a readable string for judge context."""
    # This function is primarily for DEBATE mode judging/final statements.
    # It might need adaptation if used for build/refine modes, but likely won't be.
    lines = [f"Debate Topic/Task: {current_topic}\n" + "-"*20 + "\n=== Log Start ===\n"]
    final_statements = []
    for entry in structured_log:
        if isinstance(entry, dict):
            event_type = entry.get("event")
            # Include turns and potentially final statements for debate transcripts
            if event_type == "turn":
                 lines.append(f"Turn {entry.get('turn_number','?')} - {entry.get('speaker','Unk')}: {entry.get('text','')}")
            elif event_type == "final_statement":
                 final_statements.append(f"Final Statement - {entry.get('speaker','Unk')}: {entry.get('statement_text','')}")
            # Could add other event types like 'artifact_segment' if needed for other modes

    lines.append("\n=== Log End ===\n")

    if include_final_statements and final_statements:
        lines.append("-" * 20 + "\n=== Final Statements ===\n"); lines.extend(final_statements); lines.append("\n=== End Final Statements ===")

    return "\n\n".join(lines)


# --- Function to Update Weights (Only used in Debate mode) ---
def update_weights(weights, speaker_id, debater_ids, config):
    """Updates participation weights after a turn."""
    if config.get("simulation_mode") != "debate": return weights # No weights needed otherwise
    new_weights = weights.copy(); decrement_factor=config.get("weight_decrement_factor",0.3); increment_amount=config.get("weight_increment_amount",0.05); initial_weight=config.get("weight_initial",1.0)
    for pid in debater_ids:
        current_weight = new_weights.get(pid, initial_weight)
        if pid == speaker_id: new_weights[pid] = current_weight * decrement_factor
        else: new_weights[pid] = current_weight + increment_amount
    return new_weights


# --- Function to Parse Moderator Choice (Only used in Debate mode) ---
def parse_moderator_choice(response_text, valid_ids):
    """Extracts the chosen persona_id from the moderator's response."""
    # ... (Same as v1.4) ...
    if not response_text: return None
    lines = response_text.strip().split('\n'); prefix = "NEXT_SPEAKER:"
    for line in lines:
        cleaned_line = line.strip()
        if cleaned_line.upper().startswith(prefix.upper()): # Case-insensitive check
            chosen_id = cleaned_line[len(prefix):].strip()
            if chosen_id in valid_ids: logging.info(f"Moderator chose: {chosen_id}"); return chosen_id
            else: logging.warning(f"Moderator chose invalid ID: '{chosen_id}'. Valid: {valid_ids}"); return None
    logging.warning(f"Could not parse '{prefix}' from mod response: {response_text[:100]}...")
    return None


# --- Function to Run a Single Simulation ---
def run_single_simulation(config, current_topic_or_task, topic_index):
    """Runs one full simulation for a given topic/task and mode."""
    simulation_mode = config.get("simulation_mode", "debate")
    logging.info(f"Starting simulation {topic_index+1} (Mode: {simulation_mode}) | Task: '{current_topic_or_task[:80]}...'")
    print(f"\n--- Running Simulation {topic_index+1} (Mode: {simulation_mode}) ---")
    print(f"Task/Topic: {current_topic_or_task}")

    # --- Load Personas ---
    # Participants are loaded into 'debaters' list regardless of mode for simplicity now
    participants, judges, moderator = load_and_filter_personas(config["personas_file"])
    if not participants: logging.error(f"No participants found for task '{current_topic_or_task}'. Skipping."); print(f"[ERROR] No participants found. Skipping task {topic_index+1}."); return False
    # Moderator only required for debate mode with >1 participants
    if simulation_mode == "debate" and moderator is None and len(participants) > 1:
        logging.error(f"Moderator required for debate mode but not found for task '{current_topic_or_task}'. Skipping."); print(f"[ERROR] Moderator required for debate. Skipping task {topic_index+1}."); return False
    # Judges only used in debate mode
    if simulation_mode != "debate":
         judges = [] # Clear judges if not in debate mode

    # --- Create Output Directory ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S"); safe_topic_part = "".join(c if c.isalnum() else "_" for c in current_topic_or_task[:30]).strip('_'); topic_slug = f"Task{topic_index+1:02d}_{safe_topic_part}"
    run_directory = os.path.join(config["base_log_directory"], f"simulation_{simulation_mode}_{topic_slug}_{timestamp}") # Include mode in dir name
    try: os.makedirs(run_directory, exist_ok=True); logging.info(f"Created output directory: {run_directory}")
    except OSError as e: logging.error(f"FATAL: Could not create dir {run_directory}: {e}"); print(f"[ERROR] Could not create output dir. Skipping task {topic_index+1}."); return False

    # --- Define Log File Paths ---
    detailed_log_path = os.path.join(run_directory, "detailed_log.jsonl")
    tts_json_path = os.path.join(run_directory, "conversation_script.json") # Might rename later if output isn't dialogue
    # Only create judge/final statement logs if in debate mode
    judgments_log_path = os.path.join(run_directory, "judgments.jsonl") if simulation_mode == "debate" else None
    final_statements_log_path = os.path.join(run_directory, "final_statements.jsonl") if simulation_mode == "debate" else None

    # --- Initialize State ---
    log_structured = [] # Generic log for turns/events
    output_data_for_json = [] # Data for the main JSON output (TTS script or artifact evolution)
    current_turn_number = 0
    last_speaker_id = None
    # Mode-specific state
    participation_weights = {}
    turn_counts = {}
    participant_ids = []
    participant_map = {}
    current_artifact = "" # For build/refine modes

    # Initialize participants map and IDs
    for i, p in enumerate(participants): pid = p.get('persona_id'); # ... (ID generation/validation) ...
        if pid is None: pid = f'unk_participant_{i}'; logging.warning(f"Participant missing ID, using {pid}"); p['persona_id']=pid
        if pid not in participant_map: participant_ids.append(pid); participant_map[pid]=p
        else: logging.warning(f"Duplicate ID '{pid}'")
    if not participant_ids: logging.error("No valid participant IDs found."); return False

    # Initialize debate-specific state if needed
    if simulation_mode == "debate":
        initial_weight = config.get("weight_initial", 1.0)
        participation_weights = {pid: initial_weight for pid in participant_ids}
        turn_counts = {pid: 0 for pid in participant_ids}

    logging.info(f"Starting {simulation_mode} phase for task '{current_topic_or_task[:80]}...'")
    # Add participant names list to config temporarily if needed for prompts
    config['participant_names_for_judge_prompt'] = ', '.join([p.get('display_name', 'Unk') for p in participants])

    # --- Main Simulation Loop ---
    simulation_successful = True
    try:
        with open(detailed_log_path, 'a', encoding='utf-8') as jsonl_file:
            # Log initial setup info
            config_to_log = {k:v for k,v in config.items() if k not in ['simulation_topics', 'participant_names_for_judge_prompt']}
            setup_info = { "event": "simulation_start", "mode": simulation_mode, "task_index": topic_index + 1, "task": current_topic_or_task, "timestamp": datetime.now().isoformat(), "config_subset": config_to_log, "loaded_participants": [p.get('persona_id', 'unknown') for p in participants], "loaded_judges": [p.get('persona_id', 'unknown') for p in judges] if judges else [], "loaded_moderator": moderator.get('persona_id', 'unknown') if moderator and simulation_mode == "debate" else None }
            jsonl_file.write(json.dumps(setup_info) + '\n')

            while current_turn_number < config["max_turns"]:
                current_turn_number += 1
                logging.info(f"--- Task {topic_index+1} / Turn {current_turn_number} ---")
                print(f"--- Turn {current_turn_number} ---")

                # --- Determine Next Speaker ---
                chosen_participant_id = None
                moderator_choice_method = 'N/A' # Tracks how choice was made
                moderator_response = None # Store moderator output if applicable

                if simulation_mode == "debate":
                    # Use Moderator logic from v1.4
                    if moderator is None: # Handle single debater
                        if len(participants) == 1: chosen_participant_id = participant_ids[0]; moderator_choice_method = 'single_debater'
                        else: logging.error("Moderator missing for debate. Aborting."); simulation_successful = False; break
                    else: # Moderator exists
                        mod_history_lookback = config.get("moderator_history_lookback", 5)
                        mod_history_turns = [t for t in log_structured if t.get('event') == 'turn'][-mod_history_lookback:]
                        mod_weights_context = {pid: (participant_map[pid].get('display_name', 'Unk'), weight) for pid, weight in participation_weights.items()}
                        moderator_input_context = { "history": mod_history_turns, "weights": mod_weights_context, "last_speaker_id": last_speaker_id, "turn_counts": turn_counts }
                        moderator_response = get_llm_response( moderator, moderator_input_context, current_topic_or_task, config, role_context="moderator" )
                        parsed_choice_id = parse_moderator_choice(moderator_response, participant_ids)
                        # --- Zero-Turn Override & Fallback ---
                        zero_turn_override = False; min_turns = min(turn_counts.values()) if turn_counts else 0; max_turns = max(turn_counts.values()) if turn_counts else 0; override_threshold = config.get("zero_turn_override_threshold", 3)
                        if min_turns == 0 and max_turns >= override_threshold and len(participants) > 1:
                             zero_turn_candidates = [pid for pid, count in turn_counts.items() if count == 0 and pid != last_speaker_id]
                             if zero_turn_candidates and not (parsed_choice_id and parsed_choice_id in zero_turn_candidates):
                                 logging.warning(f"Zero-turn override triggered."); chosen_participant_id = random.choice(zero_turn_candidates); moderator_choice_method = 'fallback_zero_turn'; zero_turn_override = True
                        if not zero_turn_override:
                            moderator_choice_method = 'moderator'
                            if parsed_choice_id and parsed_choice_id == last_speaker_id: logging.warning(f"Mod chose last speaker. Overriding."); moderator_choice_method='fallback_override'; parsed_choice_id=None
                            elif parsed_choice_id: chosen_participant_id = parsed_choice_id
                            else: # Fallback needed
                                if parsed_choice_id is None and moderator_response is not None: moderator_choice_method = 'fallback_invalid_choice'
                                else: moderator_choice_method = 'fallback_llm_failure'
                                logging.warning(f"Mod choice failed ({moderator_choice_method}). Falling back.")
                                zero_turn_fallback_candidates = [pid for pid, count in turn_counts.items() if count == 0 and pid != last_speaker_id]
                                if zero_turn_fallback_candidates: chosen_participant_id = random.choice(zero_turn_fallback_candidates); logging.info(f"Fallback prioritizing zero turns: '{chosen_participant_id}'"); moderator_choice_method += '_zero_priority'
                                else:
                                     eligible_fallback_ids = [pid for pid in participant_ids if pid != last_speaker_id];
                                     if not eligible_fallback_ids and participant_ids: eligible_fallback_ids = participant_ids
                                     max_weight = -float('inf'); candidates = []
                                     for pid in eligible_fallback_ids: weight = participation_weights.get(pid, initial_weight); # ... (find max weight candidates) ...
                                         if weight > max_weight: max_weight = weight; candidates = [pid]
                                         elif weight == max_weight: candidates.append(pid)
                                     if candidates: chosen_participant_id = random.choice(candidates); logging.info(f"Fallback choice (Highest Weight): '{chosen_participant_id}'")
                                     else: logging.error("CRITICAL FALLBACK FAILURE. Aborting."); simulation_successful = False; break
                else:
                    # Simple Round-Robin for build/refine modes
                    participant_index = (current_turn_number - 1) % len(participants)
                    chosen_participant_id = participant_ids[participant_index]
                    moderator_choice_method = 'round_robin'
                    logging.info(f"Round-robin choice: {chosen_participant_id}")


                # --- Participant Turn ---
                current_persona = participant_map.get(chosen_participant_id)
                if current_persona is None: logging.error(f"FATAL: Chosen ID '{chosen_participant_id}' invalid. Aborting."); simulation_successful = False; break
                current_persona_name = current_persona.get('display_name', 'Unknown')
                logging.info(f"--- Task {topic_index+1} / Turn {current_turn_number}: {current_persona_name}'s turn (Method: {moderator_choice_method}) ---")

                # 5. Determine Context & Get Response
                participant_context = None
                role_for_llm = "debater" # Default role passed to LLM function
                if simulation_mode == "debate":
                    participant_context = [t for t in log_structured if t.get('event') == 'turn'] # Pass turn history list
                elif simulation_mode == "collaborative_build":
                    participant_context = current_artifact # Pass the artifact string built so far
                elif simulation_mode == "competitive_refine":
                    participant_context = current_artifact # Pass the *last* generated artifact version

                response_text = get_llm_response( current_persona, participant_context, current_topic_or_task, config, role_context=role_for_llm )

                if response_text is None: # Handle LLM error for participant
                    logging.error(f"Failed response from {current_persona_name}. Aborting task."); print(f"\n[{current_persona_name} error. Aborted.]")
                    simulation_successful = False; break

                # --- Record the turn/artifact ---
                turn_timestamp = datetime.now().isoformat(); persona_id_safe = current_persona.get('persona_id', 'unknown')
                event_data_structured = { 'event':'turn','turn_number':current_turn_number,'timestamp':turn_timestamp,'persona_id':persona_id_safe,'speaker':current_persona_name,'text':response_text,'chosen_by':moderator_choice_method,'moderator_raw_output':moderator_response if simulation_mode == "debate" and config.get("log_moderator_output") else None }
                log_structured.append(event_data_structured) # Add turn to main log

                # For build/refine, update the artifact. For debate, just log.
                if simulation_mode == "collaborative_build":
                    current_artifact += f"\n\n[Contribution from {current_persona_name} (Turn {current_turn_number})]:\n{response_text}"
                elif simulation_mode == "competitive_refine":
                    current_artifact = response_text # Replace with the latest refined version

                # Add to TTS data (dialogue field contains turn text OR artifact segment)
                output_json_entry = { "type":"turn" if simulation_mode=="debate" else simulation_mode, "turn":current_turn_number,"speaker_id":persona_id_safe,"speaker_name":current_persona_name,"dialogue":response_text }
                output_data_for_json.append(output_json_entry)

                # Write detailed log entry
                jsonl_file.write(json.dumps({k:v for k,v in event_data_structured.items() if v is not None})+'\n'); jsonl_file.flush()
                print(f"{current_persona_name}: {response_text}\n"); logging.info(f"Turn {current_turn_number} by {current_persona_name} logged.")

                # --- Updates specific to Debate Mode ---
                if simulation_mode == "debate":
                    # 6. Update Weights & Turn Counts
                    participation_weights = update_weights(participation_weights, chosen_participant_id, participant_ids, config)
                    turn_counts[chosen_participant_id] = turn_counts.get(chosen_participant_id, 0) + 1
                    last_speaker_id = chosen_participant_id # Update last speaker
                    logging.debug(f"Updated weights: { {pid: f'{w:.2f}' for pid, w in participation_weights.items()} }")
                    logging.debug(f"Updated turn counts: {turn_counts}")
                else:
                     # In build/refine, last_speaker doesn't matter for round-robin
                     last_speaker_id = chosen_participant_id # Still useful to track potentially

                time.sleep(config.get("turn_delay_seconds", 1)) # End of loop delay

            # --- Log Simulation End ---
            end_event = "simulation_aborted" if not simulation_successful else "simulation_end"
            completed_turns = current_turn_number if simulation_successful else current_turn_number -1
            end_info = { "event": end_event, "mode": simulation_mode, "timestamp": datetime.now().isoformat(), "total_turns_completed": max(0, completed_turns) }
            jsonl_file.write(json.dumps(end_info) + '\n')

    except Exception as e:
        logging.error(f"Unexpected error during simulation loop for task '{current_topic_or_task}': {e}", exc_info=True)
        print(f"\n[An unexpected error occurred during simulation for task '{current_topic_or_task}'. Check logs.]")
        simulation_successful = False
        # Log fatal error
        try:
             with open(detailed_log_path, 'a', encoding='utf-8') as jsonl_file:
                 error_info = { "event": "fatal_error", "type": f"{simulation_mode}_loop", "timestamp": datetime.now().isoformat(), "message": str(e) }
                 jsonl_file.write(json.dumps(error_info) + '\n')
        except Exception as log_e: logging.error(f"Could not write fatal error to detailed log: {log_e}")


    # --- Final Statements Phase (Only for Debate Mode) ---
    final_statements_data = []
    if simulation_mode == "debate" and simulation_successful and participants:
        logging.info(f"--- Starting Final Statements Phase for topic '{current_topic_or_task[:80]}...' ---")
        print("\n" + "-" * 30 + f"\n--- Collecting Final Statements (Topic {topic_index+1}) ---\n" + "-" * 30 + "\n")
        final_statement_context = format_transcript(log_structured, current_topic_or_task, include_final_statements=False)
        try:
            with open(final_statements_log_path, 'a', encoding='utf-8') as fs_jsonl_file:
                start_fs_info = { "event": "final_statements_start", "timestamp": datetime.now().isoformat() }
                fs_jsonl_file.write(json.dumps(start_fs_info) + '\n')
                for participant_persona in participants: # Iterate through 'debaters' list
                    participant_name = participant_persona.get('display_name', 'Unk Participant'); participant_id = participant_persona.get('persona_id', 'unk_participant')
                    logging.info(f"Requesting Final Stmt from: {participant_name}")
                    print(f"Requesting final statement from {participant_name}...")
                    statement_text = get_llm_response( participant_persona, final_statement_context, current_topic_or_task, config, role_context="final_statement" )
                    if statement_text is None: statement_text = "(Failed final statement)"; # ... log error ...
                    fs_data_detailed = { 'event': 'final_statement', 'timestamp': datetime.now().isoformat(), 'persona_id': participant_id, 'speaker': participant_name, 'statement_text': statement_text }
                    final_statements_data.append(fs_data_detailed); log_structured.append(fs_data_detailed) # Add to main log too
                    tts_fs_data = { "type": "final_statement", "speaker_id": participant_id, "speaker_name": participant_name, "dialogue": statement_text }
                    output_data_for_json.append(tts_fs_data) # Add final statement to output JSON
                    fs_jsonl_file.write(json.dumps(fs_data_detailed) + '\n'); fs_jsonl_file.flush()
                    print(f"\n--- Final Stmt: {participant_name} ---\n{statement_text}\n{'-'*35}\n")
                    logging.info(f"Final statement logged from {participant_name}.")
                    time.sleep(config.get("turn_delay_seconds", 1))
                end_fs_info = { "event": "final_statements_end", "timestamp": datetime.now().isoformat(), "total_statements": len(final_statements_data) }
                fs_jsonl_file.write(json.dumps(end_fs_info) + '\n')
        except Exception as e: logging.error(f"Final statements phase error: {e}", exc_info=True); print("[Final statements error]")
    elif simulation_mode != "debate": logging.info("Skipping final statements phase - not applicable for this mode.")
    elif not participants: logging.info("Skipping final statements phase - no participants.")
    else: logging.info("Skipping final statements phase - simulation aborted.")


    # --- Judging Phase (Only for Debate Mode) ---
    if simulation_mode == "debate" and judges and simulation_successful:
        logging.info(f"--- Starting Judging Phase for topic '{current_topic_or_task[:80]}...' ---")
        print("\n" + "-" * 30 + f"\n--- Judging Phase (Topic {topic_index+1}) ---\n" + "-" * 30 + "\n")
        judge_transcript_context = format_transcript(log_structured, current_topic_or_task, include_final_statements=True) # Judges see final statements
        judgments = []
        try:
            with open(judgments_log_path, 'a', encoding='utf-8') as judge_jsonl_file:
                # ... (Log start) ...
                for judge_persona in judges:
                    judge_persona_name = judge_persona.get('display_name', 'Unk Judge'); judge_id = judge_persona.get('persona_id', 'unk_judge')
                    logging.info(f"Requesting judgment from: {judge_persona_name}")
                    print(f"Asking {judge_persona_name} for judgment...")
                    judgment_text = get_llm_response( judge_persona, judge_transcript_context, current_topic_or_task, config, role_context="judge" )
                    if judgment_text is None: judgment_text = "(Failed judgment)"; # ... log error ...
                    judgment_data_detailed = { 'event': 'judgment', 'timestamp': datetime.now().isoformat(), 'judge_id': judge_id, 'judge_name': judge_persona_name, 'judgment_text': judgment_text }
                    judgments.append(judgment_data_detailed)
                    tts_judgment_data = { "type": "judgment", "speaker_id": judge_id, "speaker_name": judge_persona_name, "dialogue": judgment_text }
                    output_data_for_json.append(tts_judgment_data) # Add judgment to output JSON
                    judge_jsonl_file.write(json.dumps(judgment_data_detailed) + '\n'); judge_jsonl_file.flush()
                    print(f"\n--- Judgment: {judge_persona_name} ---\n{judgment_text}\n{'-'*35}\n")
                    logging.info(f"Judgment logged from {judge_persona_name}.")
                    time.sleep(config.get("turn_delay_seconds", 1))
                # ... (Log end) ...
        except Exception as e: logging.error(f"Judging phase error: {e}", exc_info=True); print("[Judging error]")
    elif simulation_mode != "debate": logging.info("Skipping judging phase - not applicable for this mode.")
    elif not judges: logging.info("Skipping judging phase - no judges.")
    else: logging.info("Skipping judging phase - simulation aborted.")


    # --- Write Final Output JSON (TTS script or Artifact evolution) ---
    logging.info(f"Attempting to write output JSON script to {tts_json_path}")
    try:
        # Add final artifact state for build/refine modes? Maybe not needed if logged per turn.
        # For now, output_data_for_json contains turns/statements/judgments
        final_output_structure = {
            "simulation_mode": simulation_mode,
            "task": current_topic_or_task,
            "log": output_data_for_json
            # Could add final artifact state here for build/refine if desired:
            # "final_artifact": current_artifact if simulation_mode != "debate" else None
        }
        with open(tts_json_path, 'w', encoding='utf-8') as f: json.dump(final_output_structure, f, indent=2, ensure_ascii=False)
        logging.info(f"Output JSON script saved to {tts_json_path}"); print(f"\nOutput JSON script for Task {topic_index+1} saved to: {tts_json_path}")
    except Exception as e: logging.error(f"Failed write output JSON: {e}", exc_info=True); print("[Error writing output JSON]")

    logging.info(f"Finished single simulation for task: '{current_topic_or_task[:80]}...'")
    return simulation_successful # Return True/False based on completion w/o critical errors


# --- Main Script Execution ---
def main():
    """Loads config and runs simulations for each topic/task in the list."""
    config = load_config(CONFIG_FILE)
    if not config: print("Exiting: Configuration loading failed."); return

    tasks = config.get("simulation_topics", []) # Renamed variable for clarity
    if not tasks: print("Exiting: No simulation tasks/topics found."); logging.error("Exiting: No tasks."); return

    total_tasks = len(tasks)
    successful_sims = 0; failed_sims = 0

    print(f"\nFound {total_tasks} task(s)/topic(s) to simulate.")
    logging.info(f"Starting multi-task simulation run for {total_tasks} items.")

    # --- Outer Loop for Tasks/Topics ---
    for task_index, current_task in enumerate(tasks):
        print(f"\n\n{'='*20} STARTING SIMULATION FOR TASK {task_index + 1}/{total_tasks} {'='*20}")
        logging.info(f"--- Starting Sim Task {task_index + 1}/{total_tasks}: '{current_task}' ---")
        try:
            # --- Run a Single Simulation ---
            success = run_single_simulation(config, current_task, task_index) # Pass task description
            if success: successful_sims += 1
            else: failed_sims += 1; print(f"[INFO] Simulation for task {task_index + 1} did not complete successfully.")
        except Exception as e:
            failed_sims += 1; logging.critical(f"CRITICAL UNHANDLED ERROR task {task_index + 1} ('{current_task}'): {e}", exc_info=True)
            print(f"\n[CRITICAL ERROR] Task {task_index + 1} failed unexpectedly. See logs. Continuing...")
            logging.error(traceback.format_exc())

        print(f"\n{'='*20} FINISHED SIMULATION FOR TASK {task_index + 1}/{total_tasks} {'='*20}\n")
        logging.info(f"--- Finished Sim Task {task_index + 1}/{total_tasks} ---")

        if task_index < total_tasks - 1:
             delay = config.get("turn_delay_seconds", 1) * 5
             logging.info(f"Pausing for {delay} seconds..."); print(f"...pausing {delay}s..."); time.sleep(delay)

    # --- Final Summary ---
    print("\n\n" + "="*50 + "\n=== MULTI-TASK SIMULATION RUN COMPLETE ===\n" + f"Total Tasks Processed: {total_tasks}\nSuccessful Simulations: {successful_sims}\nFailed Simulations:     {failed_sims}\n" + "="*50)
    logging.info(f"Multi-task run finished. Success: {successful_sims}, Failed: {failed_sims}")


# --- Trigger Main Function ---
if __name__ == "__main__":
    if not os.path.exists(CONFIG_FILE): print(f"Error: Config file '{CONFIG_FILE}' not found."); logging.critical(f"Config file '{CONFIG_FILE}' not found.")
    else:
        try: main()
        except Exception as e: print(f"\n[FATAL ERROR] Unhandled exception: {e}"); logging.critical(f"Unhandled exception: {e}", exc_info=True); logging.critical(traceback.format_exc())

# END OF FILE: agora_simulator_v1.5_modes.py