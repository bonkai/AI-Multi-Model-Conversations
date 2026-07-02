# ... (Keep all imports and config the same) ...
import requests
import json
import logging
import time
import os
import re
from datetime import datetime
import string
from collections import deque
import sys
import traceback # Import traceback for detailed error logging

# --- Configuration ---
API_URL = "http://localhost:11434/api/chat"
OUTPUT_DIR = "generated_stories_iterative"
MODEL_NAME = "gemma3:latest"
STORY_TOPIC = "Topic: Build a Beat Block House"
"Concept: Help a friendly, blocky character (maybe named 'Blocky Sprunk' or similar) build a simple house. Each type of block (wood, stone, maybe a special 'music block') makes a fun sound (like an Incredibox beat) when placed. The goal is to finish the house and maybe make a little beat pattern."
"Minecraft Elements: Building with blocks (wood, stone), simple structures (wall, roof)."
"Incredibox Elements: Character inspiration, focus on sounds/beats associated with actions."
"Reading Focus: Simple nouns (block, wood, stone, house, wall, roof), action verbs (get, put, build, stack, tap, listen), sound words (tap, pop, boom, ding - keep simple), color words (red block, blue block), location words (here, on top). Repetitive sentence structures like" 
"Get the wood block." "Put the block here." 
"Listen! It goes [sound]."
CHECKPOINT_FILE = "checkpoint_story.json" # File for saving progress

# --- Generation Parameters ---
TARGET_CHUNK_SIZE = 5
MAX_TOTAL_NODES = 150
MAX_ITERATIONS = 150

# --- Set up Logging ---
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')

# --- Helper Function to Sanitize Filenames ---
def sanitize_filename(text, max_length=20):
    # (Function remains the same)
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    sanitized = ''.join(c for c in text if c in valid_chars)
    sanitized = sanitized.replace(' ', '_').lower()
    sanitized = re.sub('_+', '_', sanitized)
    return sanitized[:max_length].strip('_')


# --- Prompt Building Functions ---
# (build_prompt_for_chunk and build_initial_prompt remain the same)
def build_prompt_for_chunk(topic, current_node_id, history_path, story_data, target_chunk_size):
    # (Function remains the same)
    logging.debug(f"Building prompt for node: {current_node_id}")
    if current_node_id not in story_data["nodes"]:
         logging.error(f"Cannot build prompt. Node ID '{current_node_id}' not found in story_data.")
         return None
    current_node_text = story_data["nodes"][current_node_id].get("text", "[No text found]")
    history_summary = " -> ".join(history_path) if history_path else "[Start]"
    prompt = f"""
You are an expert AI assistant creating structured Choose Your Own Adventure (CYOA) stories in JSON format, chunk by chunk.
**Overall Topic:** {topic}
**Current Situation:**
The player has reached Node ID '{current_node_id}'.
The text for this node is: "{current_node_text}"
The path taken to get here was: {history_summary}
**Your Task:**
Generate the next part of the story graph starting from the choices offered at Node '{current_node_id}'.
Your response MUST be a single, valid JSON object containing ONLY the newly generated nodes for this chunk. Do NOT include the current node ('{current_node_id}') in your response JSON.
**Constraints:**
1.  **Chunk Size:** Aim to generate roughly **{target_chunk_size}** new nodes in total within this chunk (including nodes reachable from choices within the chunk). It can be fewer if paths end quickly.
2.  **Node IDs:** Use unique and descriptive string IDs for all new nodes you generate (e.g., "{current_node_id}_choice1", "{current_node_id}_alt_path"). Ensure these IDs are unique within the JSON object you return.
3.  **Merging & Endings:** Where it makes narrative sense, you **can and should** create choices that lead to an ending (set `isEnding: true`, `choices: []`). You can also make choices lead back to logical previous points if appropriate (though explicitly referencing *old* node IDs is complex, focus on natural narrative conclusions or loops within the chunk if possible).
4.  **JSON Format:** The output MUST be ONLY a JSON object mapping the new node IDs to their node objects. Structure each node object like this:
    ```json
    {{
      "new_node_id_1": {{
        "text": "Narrative text for this new node.",
        "choices": [
          {{"text": "Choice description 1", "nextNodeId": "next_node_id_a"}},
          {{"text": "Choice description 2", "nextNodeId": "next_node_id_b"}}
        ],
        "isEnding": false
      }},
      "next_node_id_a": {{ ... }},
      "ending_node_id": {{
          "text": "An ending description. THE END.",
          "choices": [],
          "isEnding": true
      }}
    }}
    ```
5.  **Connectivity:** The choices listed in the *current* node ('{current_node_id}') should logically connect to the starting nodes defined within your JSON response chunk.
**IMPORTANT:** Generate *only* the JSON object representing the new chunk of nodes. Do not include explanations or markdown formatting.
Now, generate the JSON chunk following Node ID '{current_node_id}'.
"""
    return prompt.strip()

def build_initial_prompt(topic, target_chunk_size):
    # (Function remains the same)
    logging.debug("Building initial prompt...")
    prompt = f"""
You are an expert AI assistant creating structured Choose Your Own Adventure (CYOA) stories in JSON format, starting from the beginning.
**Overall Topic:** {topic}
**Your Task:**
Generate the **starting chunk** of the story graph. This should include the very first node the player sees, and the nodes immediately reachable from its choices.
Your response MUST be a single, valid JSON object containing the nodes for this initial chunk.
**Constraints:**
1.  **Chunk Size:** Aim to generate roughly **{target_chunk_size}** nodes in total (including the start node and its successors).
2.  **Start Node:** Designate one node as the starting point. The Python script will identify this later.
3.  **Node IDs:** Use unique and descriptive string IDs (e.g., "start", "start_choice1", "start_choice1_outcome"). Ensure these IDs are unique within the JSON object you return.
4.  **JSON Format:** The output MUST be ONLY a JSON object mapping the new node IDs to their node objects. Structure each node object like this:
    ```json
    {{
      "node_id_1": {{
        "text": "Narrative text for this node.",
        "choices": [
          {{"text": "Choice description 1", "nextNodeId": "next_node_id_a"}},
          {{"text": "Choice description 2", "nextNodeId": "next_node_id_b"}}
        ],
        "isEnding": false
      }},
      "next_node_id_a": {{ ... }},
    }}
    ```
5.  **Endings:** It's possible, though less likely in the first chunk, for a choice to lead directly to an ending (`isEnding: true`, `choices: []`).
**IMPORTANT:** Generate *only* the JSON object representing the initial chunk of nodes. Do not include explanations or markdown formatting.
Now, generate the initial JSON chunk for the story topic: {topic}.
"""
    return prompt.strip()


# --- Function to Interact with Ollama LLM for a Chunk ---
# (get_llm_chunk remains the same)
def get_llm_chunk(prompt_text):
    """Sends a prompt to Ollama and expects a JSON object representing a chunk of nodes."""
    logging.info(f"Requesting LLM chunk generation...")
    logging.debug(f"Sending prompt (first 100 chars): {prompt_text[:100]}...")
    messages = [{"role": "user", "content": prompt_text}]
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.7,
        "format": "json",
        "stream": False
    }
    logging.debug(f"Payload: {json.dumps(payload, indent=2)}")

    try:
        start_time = time.time()
        response = requests.post(API_URL, json=payload, timeout=360)
        end_time = time.time()
        logging.info(f"Request completed. Status: {response.status_code}. Time: {end_time - start_time:.2f}s.")
        response.raise_for_status()

        result = response.json()
        response_content = result.get('message', {}).get('content', '').strip()

        if not response_content:
            logging.error("Received empty content from Ollama.")
            return None

        # Clean content
        cleaned_content = re.sub(r"^\s*<think>.*?</think>\s*", "", response_content, flags=re.DOTALL | re.IGNORECASE)
        if len(cleaned_content) < len(response_content):
            logging.debug("Removed <think> block.")
            response_content = cleaned_content

        if response_content.startswith("```json"):
            response_content = response_content[7:]
            if response_content.endswith("```"):
                response_content = response_content[:-3]
            response_content = response_content.strip()
            logging.debug("Stripped ```json fence.")
        elif response_content.startswith("```"):
             response_content = response_content[3:]
             if response_content.endswith("```"):
                response_content = response_content[:-3]
             response_content = response_content.strip()
             logging.debug("Stripped ``` fence.")

        # Parse JSON
        chunk_data = json.loads(response_content)
        logging.info(f"Successfully parsed JSON chunk with {len(chunk_data)} nodes.")
        return chunk_data

    except json.JSONDecodeError as json_err:
        logging.error(f"Failed to decode JSON chunk. Error: {json_err}")
        logging.error(f"Content received: {response_content[:500]}...")
        return None
    except requests.exceptions.Timeout:
        logging.error("Ollama request timed out.")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Ollama API request failed: {e}", exc_info=False) # exc_info=False to reduce noise unless needed
        return None
    except Exception as e:
        logging.error(f"Unexpected error in get_llm_chunk: {e}", exc_info=True)
        return None


# --- Checkpointing Functions ---
def save_checkpoint(filepath, story_data, frontier, processed_node_ids, iteration):
    """Saves the current generation state to a checkpoint file."""
    abs_filepath = os.path.abspath(filepath) # Get absolute path for clarity
    logging.debug(f"Attempting to save checkpoint to: {abs_filepath}")
    try:
        state = {
            "story_data": story_data,
            "frontier": list(frontier), # Convert deque to list
            "processed_node_ids": list(processed_node_ids), # Convert set to list
            "iteration_count": iteration,
            "timestamp": datetime.now().isoformat()
        }
        # Use a temporary file and rename to make the save more atomic
        temp_filepath = abs_filepath + ".tmp"
        with open(temp_filepath, 'w') as f:
            json.dump(state, f, indent=2)
        os.replace(temp_filepath, abs_filepath) # Atomic rename (on most OS)
        logging.info(f"Checkpoint saved successfully to {abs_filepath} at iteration {iteration}.")
    except Exception as e:
        # Log the full traceback for save errors
        logging.error(f"CRITICAL: Failed to save checkpoint to {abs_filepath}!", exc_info=True)
        # Optionally: print traceback to console as well
        # traceback.print_exc()

def load_checkpoint(filepath):
    """Loads the generation state from a checkpoint file."""
    abs_filepath = os.path.abspath(filepath)
    logging.info(f"Attempting to load checkpoint from: {abs_filepath}")
    if not os.path.exists(abs_filepath):
        logging.info("Checkpoint file not found. Starting fresh.")
        return None
    try:
        with open(abs_filepath, 'r') as f:
            state = json.load(f)
        # Convert lists back to deque and set
        state["frontier"] = deque(state.get("frontier", []))
        state["processed_node_ids"] = set(state.get("processed_node_ids", []))
        # Basic validation
        if "story_data" not in state or "nodes" not in state["story_data"]:
             raise ValueError("Checkpoint data is missing essential 'story_data' structure.")
        logging.info(f"Checkpoint loaded successfully from {state.get('timestamp', 'unknown time')}.")
        logging.info(f"Resuming from iteration {state.get('iteration_count', 0)}.")
        logging.info(f"Loaded {len(state['story_data']['nodes'])} nodes.")
        logging.info(f"Loaded frontier size: {len(state['frontier'])}")
        return state
    except Exception as e:
        logging.error(f"Failed to load or validate checkpoint from {abs_filepath}: {e}", exc_info=True)
        logging.warning("Ignoring potentially corrupt checkpoint file.")
        # Optionally delete the corrupt file: os.remove(abs_filepath)
        return None


# --- Main Execution ---
def main():
    logging.info("--- Starting Iterative CYOA Generation Script ---")
    start_time_total = time.time()

    # --- Attempt to Load Checkpoint ---
    # Checkpoint file is saved in the script's current working directory
    checkpoint_path = os.path.join(os.getcwd(), CHECKPOINT_FILE)
    loaded_state = load_checkpoint(checkpoint_path)

    if loaded_state:
        story_data = loaded_state["story_data"]
        frontier = loaded_state["frontier"]
        processed_node_ids = loaded_state["processed_node_ids"]
        iteration_count = loaded_state["iteration_count"]
        all_generated_node_ids = set(story_data["nodes"].keys())
        logging.info("Resumed state from checkpoint.")
    else:
        # --- Initialize Fresh State ---
        logging.info("Initializing fresh state.")
        story_data = { "startNodeId": None, "nodes": {} }
        frontier = deque()
        all_generated_node_ids = set()
        processed_node_ids = set()
        iteration_count = 0

        # Create output directory for FINAL saves
        output_dir_path = os.path.abspath(OUTPUT_DIR)
        if not os.path.exists(output_dir_path):
            try:
                os.makedirs(output_dir_path)
                logging.info(f"Created output directory: {output_dir_path}")
            except OSError as e:
                logging.error(f"Failed to create output directory {output_dir_path}: {e}", exc_info=True)
                return # Cannot proceed without output dir

        # --- Generate Initial Chunk ---
        logging.info("Generating initial story chunk...")
        initial_prompt = build_initial_prompt(STORY_TOPIC, TARGET_CHUNK_SIZE)
        initial_chunk = get_llm_chunk(initial_prompt)

        if not initial_chunk or not isinstance(initial_chunk, dict) or not initial_chunk:
            logging.critical("Failed to generate or parse the initial chunk. Cannot proceed.")
            sys.exit(1)

        logging.info(f"Received initial chunk with {len(initial_chunk)} nodes.")

        # --- Process Initial Chunk ---
        # (Keep the logic for determining start node and populating initial state)
        # ... (logic from previous version) ...
        potential_start_ids = list(initial_chunk.keys())
        target_ids_in_chunk = set()
        for node_id, node_data in initial_chunk.items():
            if isinstance(node_data, dict) and not node_data.get("isEnding", False):
                for choice in node_data.get("choices", []):
                    if isinstance(choice, dict) and "nextNodeId" in choice:
                        target_ids_in_chunk.add(choice["nextNodeId"])
        determined_start_id = None
        for node_id in potential_start_ids:
            if node_id not in target_ids_in_chunk:
                determined_start_id = node_id
                break
        if not determined_start_id:
            determined_start_id = potential_start_ids[0]
            logging.warning(f"Could not reliably determine start node. Assuming '{determined_start_id}'.")
        story_data["startNodeId"] = determined_start_id
        logging.info(f"Determined start node ID: {determined_start_id}")
        initial_history_map = {}
        for node_id, node_object in initial_chunk.items():
            if node_id in all_generated_node_ids: continue
            if not isinstance(node_object, dict): continue
            story_data["nodes"][node_id] = node_object
            all_generated_node_ids.add(node_id)
            initial_history_map[node_id] = []
        q = deque([(determined_start_id, [determined_start_id])])
        visited_history = {determined_start_id}
        while q:
             curr_id, path = q.popleft()
             initial_history_map[curr_id] = path
             if curr_id not in story_data["nodes"]: continue
             node_object = story_data["nodes"][curr_id]
             if not node_object.get("isEnding", False):
                 processed_node = True
                 for choice in node_object.get("choices", []):
                     if isinstance(choice, dict) and "nextNodeId" in choice:
                         target_node_id = choice["nextNodeId"]
                         new_path = path + [target_node_id]
                         if target_node_id in initial_chunk:
                             if target_node_id not in visited_history:
                                 visited_history.add(target_node_id)
                                 q.append((target_node_id, new_path))
                             target_node_obj = initial_chunk.get(target_node_id, {})
                             if not target_node_obj.get("isEnding", False):
                                  has_external_target = False
                                  for target_choice in target_node_obj.get("choices", []):
                                       if target_choice.get("nextNodeId") not in initial_chunk:
                                            has_external_target = True
                                            break
                                  if has_external_target:
                                       if target_node_id not in [f[0] for f in frontier]:
                                            frontier.append((target_node_id, new_path))
                                       processed_node = False
                             else:
                                  processed_node_ids.add(target_node_id)
                         else:
                             if target_node_id not in [f[0] for f in frontier]:
                                 logging.debug(f"Adding node '{target_node_id}' to frontier from initial chunk.")
                                 frontier.append((target_node_id, new_path))
                             processed_node = False
                 if processed_node:
                      processed_node_ids.add(curr_id)
             else: # Initial node is an ending
                  processed_node_ids.add(curr_id)

        logging.info(f"Initial frontier size: {len(frontier)}")
        logging.debug(f"Initial Frontier: {list(frontier)}")

        # --- Save initial state immediately ---
        logging.info("Saving initial checkpoint...")
        save_checkpoint(checkpoint_path, story_data, frontier, processed_node_ids, iteration_count)


    # --- Iterative Expansion Loop ---
    while frontier and iteration_count < MAX_ITERATIONS and len(story_data["nodes"]) < MAX_TOTAL_NODES:
        iteration_count += 1
        logging.info(f"--- Iteration {iteration_count} ---")

        try:
             current_node_id, history_path = frontier.popleft()
        except IndexError:
             logging.info("Frontier is unexpectedly empty inside loop.")
             break

        logging.info(f"Expanding node: '{current_node_id}' (Frontier size: {len(frontier)})")

        # Skip if already processed
        if current_node_id in processed_node_ids:
            logging.debug(f"Node '{current_node_id}' already processed. Skipping.")
            continue

        # Ensure node exists
        if current_node_id not in story_data["nodes"]:
             logging.error(f"Node '{current_node_id}' from frontier not found in story_data! Skipping.")
             # This node might need special handling or indicates a bug
             continue

        # Skip if it's an ending node
        if story_data["nodes"][current_node_id].get("isEnding", False):
            logging.warning(f"Node '{current_node_id}' from frontier is an ending node. Marking processed.")
            processed_node_ids.add(current_node_id)
            continue

        # Build prompt
        prompt = build_prompt_for_chunk(STORY_TOPIC, current_node_id, history_path, story_data, TARGET_CHUNK_SIZE)
        if not prompt:
            logging.error(f"Failed to build prompt for node '{current_node_id}'. Re-adding to frontier.")
            frontier.append((current_node_id, history_path))
            continue

        # Get the next chunk from LLM
        new_chunk = get_llm_chunk(prompt)

        if not new_chunk or not isinstance(new_chunk, dict):
            logging.warning(f"Failed to get valid chunk for node '{current_node_id}'. Re-adding to frontier.")
            frontier.append((current_node_id, history_path))
            time.sleep(5) # Wait before retrying this node
            continue

        # --- Process and Merge New Chunk ---
        logging.info(f"Received chunk with {len(new_chunk)} nodes for '{current_node_id}'. Merging...")
        merge_successful = False # Flag to check if merge completed
        try:
            # (Using the refined merge logic from previous step)
            valid_new_nodes = {}
            for new_node_id, new_node_object in new_chunk.items():
                if not isinstance(new_node_object, dict) or "text" not in new_node_object:
                    logging.warning(f"Invalid node object format for '{new_node_id}' in chunk. Skipping.")
                    continue
                if new_node_id in all_generated_node_ids:
                    logging.warning(f"Duplicate node ID '{new_node_id}' received. Reusing existing node.")
                    continue
                valid_new_nodes[new_node_id] = new_node_object
                if new_node_object.get("isEnding", False):
                     processed_node_ids.add(new_node_id)

            current_node_obj = story_data["nodes"][current_node_id]
            original_choices = current_node_obj.get("choices", [])
            new_chunk_keys = list(valid_new_nodes.keys())

            if len(original_choices) > 0 and len(new_chunk_keys) > 0:
                 num_choices_to_link = min(len(original_choices), len(new_chunk_keys))
                 for i in range(num_choices_to_link):
                      original_choices[i]["nextNodeId"] = new_chunk_keys[i]
                      logging.debug(f"Linked choice {i} of '{current_node_id}' to '{new_chunk_keys[i]}'")
                 if len(original_choices) != len(new_chunk_keys):
                      logging.warning(f"Mismatch linking choices for '{current_node_id}'. Choices: {len(original_choices)}, Chunk starts: {len(new_chunk_keys)}")
            else:
                 logging.warning(f"Could not link choices for '{current_node_id}'. No choices or no new nodes received.")

            for new_node_id, new_node_object in valid_new_nodes.items():
                story_data["nodes"][new_node_id] = new_node_object
                all_generated_node_ids.add(new_node_id)
                logging.debug(f"Added node '{new_node_id}' to story_data.")

                if not new_node_object.get("isEnding", False):
                    new_history = history_path + [new_node_id]
                    for choice in new_node_object.get("choices", []):
                        if isinstance(choice, dict) and "nextNodeId" in choice:
                            target_node_id = choice["nextNodeId"]
                            if target_node_id not in all_generated_node_ids and target_node_id not in processed_node_ids and target_node_id not in [f[0] for f in frontier]:
                                logging.debug(f"Adding node '{target_node_id}' to frontier.")
                                frontier.append((target_node_id, new_history + [target_node_id]))
                            elif target_node_id in all_generated_node_ids:
                                logging.debug(f"Node '{target_node_id}' already generated (merge/loop). Not adding to frontier.")

            processed_node_ids.add(current_node_id)
            logging.debug(f"Marked node '{current_node_id}' as processed.")
            merge_successful = True # Mark merge as successful

        except Exception as merge_err:
             logging.error(f"Error processing/merging chunk for node '{current_node_id}': {merge_err}", exc_info=True)
             processed_node_ids.add(current_node_id) # Mark as processed to avoid infinite loop on this node

        # --- Save Checkpoint ONLY if merge was successful ---
        if merge_successful:
            save_checkpoint(checkpoint_path, story_data, frontier, processed_node_ids, iteration_count)
        else:
            logging.warning(f"Skipping checkpoint save for iteration {iteration_count} due to merge error.")


        # Safety break conditions
        if iteration_count >= MAX_ITERATIONS:
            logging.warning(f"Reached maximum iterations ({MAX_ITERATIONS}). Stopping.")
            break
        if len(story_data["nodes"]) >= MAX_TOTAL_NODES:
            logging.warning(f"Reached maximum node count ({MAX_TOTAL_NODES}). Stopping.")
            break

    # --- Completion ---
    end_time_total = time.time()
    logging.info("--- Generation Loop Finished ---")
    # (Rest of the completion and final save logic remains the same)
    # ... (final save logic) ...
    if story_data.get("startNodeId") and story_data.get("nodes"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sanitized_topic = sanitize_filename(STORY_TOPIC)
        filename = f"{sanitized_topic}_iterative_{timestamp}.json"
        # Save final output in the designated OUTPUT_DIR
        output_dir_path = os.path.abspath(OUTPUT_DIR)
        filepath = os.path.join(output_dir_path, filename)
        logging.info(f"Attempting to save final story to {filepath}")
        try:
            with open(filepath, 'w') as f:
                json.dump(story_data, f, indent=2)
            logging.info(f"Story successfully saved to {filepath}")
            print(f"\nSuccess! Story saved to {filepath}")
            # Optionally remove checkpoint file on successful final save
            if os.path.exists(checkpoint_path):
                 try:
                      os.remove(checkpoint_path)
                      logging.info(f"Removed checkpoint file: {checkpoint_path}")
                 except OSError as e:
                      logging.warning(f"Could not remove checkpoint file {checkpoint_path}: {e}")
        except IOError as e:
            logging.error(f"Error saving story to file {filepath}: {e}", exc_info=True)
            print(f"\nError: Could not save story to {filepath}.")
        except Exception as e:
            logging.error(f"An unexpected error occurred while saving the file: {e}", exc_info=True)
            print(f"\nError: An unexpected error occurred while saving the file.")
    else:
        logging.error("Final story data is incomplete. Nothing saved.")
        print("\nError: Final story data was incomplete. No file saved.")


    logging.info("--- Iterative CYOA Generation Script Finished ---")


# --- Trigger Main Function ---
if __name__ == "__main__":
    # (Initial connectivity check remains the same)
    # ... (connectivity check) ...
    try:
        logging.debug(f"Performing initial connectivity check to {API_URL.replace('/api/chat','')}...")
        requests.get(API_URL.replace('/api/chat','/'), timeout=5)
        logging.debug("Initial connectivity check successful.")
    except requests.exceptions.ConnectionError:
        logging.error(f"Initial check failed: Could not connect to Ollama base URL at {API_URL.replace('/api/chat','')}. Is Ollama running?")
        print(f"CRITICAL: Cannot connect to Ollama at {API_URL.replace('/api/chat','')}. Please ensure Ollama is running.")
        sys.exit(1)
    except Exception as e:
         logging.warning(f"Initial connectivity check encountered an issue: {e}")

    main()