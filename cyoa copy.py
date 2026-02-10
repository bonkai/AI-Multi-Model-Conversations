import requests
import json
import logging
import time
import os
import re
from datetime import datetime
import string

# --- Configuration ---
API_URL = "http://localhost:11434/api/chat"
# Make sure this model name is correct and pulled in Ollama
MODEL_NAME = "qwq:latest" # As per your log - double check this name!
OUTPUT_DIR = "generated_stories"

# --- Story Parameters (Hardcoded for now) ---
STORY_TOPIC = "A lone astronaut investigates a mysterious signal from an unexplored moon."
NUM_CHOICES_PER_NODE = 2
TARGET_DEPTH = 4

# --- Set up Logging ---
# Let's increase log level to DEBUG to see more details
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')

# --- Helper Function to Sanitize Filenames ---
def sanitize_filename(text, max_length=50):
    # (Function remains the same)
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    sanitized = ''.join(c for c in text if c in valid_chars)
    sanitized = sanitized.replace(' ', '_').lower()
    sanitized = re.sub('_+', '_', sanitized)
    return sanitized[:max_length].strip('_')

# --- Function to Build the LLM Prompt ---
def build_cyoa_prompt(topic, num_choices, depth):
    # (Function remains the same)
    logging.debug("Building CYOA prompt...")
    prompt = f"""
You are an expert AI assistant specialized in creating structured Choose Your Own Adventure (CYOA) stories in JSON format.

Your task is to generate a complete CYOA story based on the provided topic and constraints. The output MUST be a single, valid JSON object and nothing else. Adhere STRICTLY to the specified format.

**Constraints:**
1.  **Topic:** {topic}
2.  **Choices per Node:** Exactly {num_choices} choices for every non-ending node.
3.  **Story Depth:** Every path from the start node to an ending node must involve exactly {depth} choices made by the player. This means there should be {depth+1} nodes in any given path (including the start and end nodes).
4.  **JSON Format:** The output must be ONLY a JSON object matching the structure below. Do NOT include any text before or after the JSON object (like "Here is the JSON:" or ```json ... ``` markdown). If you perform any internal 'thinking' steps, do not include them in the final output.

**Required JSON Structure:**
```json
{{
  "startNodeId": "unique_node_id_string",
  "nodes": {{
    "unique_node_id_string": {{
      "text": "Story narrative for this node.",
      "choices": [
        {{
          "text": "Description of choice 1.",
          "nextNodeId": "target_node_id_for_choice_1"
        }},
        {{
          "text": "Description of choice 2.",
          "nextNodeId": "target_node_id_for_choice_2"
        }}
        // Add more choices here ONLY if num_choices > 2
      ],
      "isEnding": false // Set to true ONLY for ending nodes
    }},
    // ... more nodes follow here ...
    "another_node_id": {{
        "text": "This is an ending node narrative. THE END.",
        "choices": [], // Ending nodes MUST have an empty choices list
        "isEnding": true
    }}
  }}
}}


Key JSON Rules:

startNodeId: Must be the ID of the first node. Use simple strings for IDs (e.g., "0", "1a", "1b", "2a_1"). Ensure all node IDs are unique within the nodes dictionary.

nodes: A dictionary where keys are the unique node IDs.

text: The story text for the node. Keep it concise but engaging.

choices: A list containing exactly {num_choices} objects for non-ending nodes. For ending nodes, it MUST be an empty list ([]).

nextNodeId: Must point to a valid node ID defined within the nodes dictionary.

isEnding: Must be false for nodes with choices, and true for nodes without choices (endings).

IMPORTANT: Generate the entire story tree structure fulfilling all constraints within a single JSON object. Ensure all branches reach the required depth ({depth} choices) and terminate correctly in an ending node. Create unique node IDs for all nodes generated. Produce only the JSON object as your final output.

Now, generate the CYOA JSON for the specified topic and constraints.
"""
    final_prompt = prompt.strip()
    logging.debug(f"Generated prompt (first 200 chars): {final_prompt[:200]}...")
    return final_prompt

# --- Function to Interact with Ollama LLM ---

def get_llm_cyoa_json(prompt_text):
    logging.info(f"Attempting to generate CYOA JSON using model '{MODEL_NAME}' at {API_URL}")

    messages = [{"role": "user", "content": prompt_text}]
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.6,
        "format": "json",
        "stream": False
        # Maybe add options later if needed:
        # "options": {
        #     "num_ctx": 4096 # Example: Limit context if needed
        # }
    }

    logging.debug(f"Constructed payload for Ollama: {json.dumps(payload, indent=2)}")

    try:
        logging.info(f"Sending request to Ollama (Timeout: 300s)...")
        start_time = time.time()
        response = requests.post(API_URL, json=payload, timeout=300)
        end_time = time.time()
        logging.info(f"Request completed. Status Code: {response.status_code}. Time taken: {end_time - start_time:.2f} seconds.")

        # Log headers for debugging connection issues (like keep-alive)
        logging.debug(f"Response Headers: {response.headers}")

        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        logging.debug(f"Raw Response Body (first 500 chars): {response.text[:500]}...") # Log raw text before JSON parsing

        result = response.json()
        logging.debug(f"Successfully parsed response JSON.") # Moved this after response.json() call

        response_content = result.get('message', {}).get('content', '').strip()

        if not response_content:
            logging.error("API call successful, but received empty 'content' in the response message.")
            return None

        # --- Strip <think>...</think> tags ---
        logging.debug("Checking for <think> tags...")
        cleaned_content = re.sub(r"^\s*<think>.*?</think>\s*", "", response_content, flags=re.DOTALL | re.IGNORECASE)
        if len(cleaned_content) < len(response_content):
            logging.info("Removed <think>...</think> block from the beginning of the response.")
            response_content = cleaned_content

        # --- Attempt to parse the JSON string ---
        logging.info("Attempting to parse final JSON content...")
        try:
            # Strip potential markdown fences (```json ... ```)
            logging.debug(f"Content before stripping markdown fences (first 100): {response_content[:100]}...")
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

            logging.debug(f"Content attempting to parse as JSON (first 100): {response_content[:100]}...")
            story_data = json.loads(response_content)
            logging.info("Successfully parsed final JSON from LLM response.")
            return story_data

        except json.JSONDecodeError as json_err:
            logging.error(f"Failed to decode JSON from LLM response. Reason: {json_err}")
            # Log more context around the error
            error_line = json_err.lineno
            error_col = json_err.colno
            # Get the line where the error occurred
            lines = response_content.splitlines()
            context_line = lines[error_line - 1] if error_line <= len(lines) else "N/A"
            logging.error(f"JSON Error at Line: {error_line}, Column: {error_col}")
            logging.error(f"Line Content: '{context_line}'")
            logging.error(f"--- Full Received Content (after stripping attempts) Start ---")
            logging.error(response_content) # Log the whole thing if parse fails
            logging.error(f"--- Full Received Content End ---")
            return None

    # More specific exception handling
    except requests.exceptions.ConnectionError as e:
        # This catches refused connections, DNS errors, etc.
        logging.error(f"Ollama Connection Error: {e}", exc_info=True) # exc_info=True logs traceback
        print(f"\nError: Could not connect to Ollama at {API_URL}. Is it running?")
        return None
    except requests.exceptions.Timeout as e:
        logging.error(f"Ollama Request Timeout: The request took longer than 300 seconds. {e}", exc_info=True)
        print(f"\nError: Request to Ollama timed out.")
        return None
    except requests.exceptions.HTTPError as e:
        # Handles 4xx/5xx errors after connection is made
        logging.error(f"Ollama HTTP Error: {e.response.status_code} {e.response.reason}. Response: {e.response.text}", exc_info=True)
        print(f"\nError: Ollama returned an HTTP error ({e.response.status_code}). Check logs.")
        return None
    except requests.exceptions.RequestException as e:
        # Catch-all for other requests library issues (like the RemoteDisconnected)
        logging.error(f"Ollama Request Exception: {e}", exc_info=True)
        print(f"\nError: An issue occurred during the request to Ollama. Check logs.")
        return None
    except Exception as e:
        # Catch any other unexpected errors
        logging.error(f"An unexpected error occurred in get_llm_cyoa_json: {e}", exc_info=True)
        print(f"\nError: An unexpected script error occurred. Check logs.")
        return None

# --- Main Execution ---

def main():
    logging.info("--- Starting CYOA Generation Script ---")

    # Create output directory if it doesn't exist
    output_dir_path = os.path.abspath(OUTPUT_DIR) # Use absolute path for clarity
    logging.debug(f"Ensuring output directory exists: {output_dir_path}")
    if not os.path.exists(output_dir_path):
        try:
            os.makedirs(output_dir_path)
            logging.info(f"Created output directory: {output_dir_path}")
        except OSError as e:
            logging.error(f"Failed to create output directory {output_dir_path}: {e}", exc_info=True)
            print(f"Error: Could not create output directory {output_dir_path}. Aborting.")
            return

    # 1. Build the prompt
    logging.debug("Calling build_cyoa_prompt...")
    prompt = build_cyoa_prompt(STORY_TOPIC, NUM_CHOICES_PER_NODE, TARGET_DEPTH)
    if not prompt:
        logging.error("Failed to build the prompt.")
        return

    # 2. Get the response from Ollama
    logging.debug("Calling get_llm_cyoa_json...")
    generated_story = get_llm_cyoa_json(prompt)

    # 3. Process the result
    if generated_story:
        logging.info(f"Successfully generated and parsed story data.")
        if isinstance(generated_story, dict) and "startNodeId" in generated_story and "nodes" in generated_story:
            logging.info(f"JSON structure appears valid. Contains 'startNodeId' and 'nodes'. Found {len(generated_story.get('nodes', {}))} nodes.")

            # --- Generate unique filename ---
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            sanitized_topic = sanitize_filename(STORY_TOPIC)
            filename = f"{sanitized_topic}_{timestamp}.json"
            filepath = os.path.join(output_dir_path, filename)
            logging.debug(f"Generated unique filepath: {filepath}")

            # Save the JSON to the unique file
            try:
                logging.info(f"Attempting to save story to {filepath}")
                with open(filepath, 'w') as f:
                    json.dump(generated_story, f, indent=2)
                logging.info(f"Story successfully saved.")
                print(f"\nSuccess! Story saved to {filepath}")
            except IOError as e:
                logging.error(f"Error saving story to file {filepath}: {e}", exc_info=True)
                print(f"\nError: Could not save story to {filepath}.")
            except Exception as e:
                logging.error(f"An unexpected error occurred while saving the file: {e}", exc_info=True)
                print(f"\nError: An unexpected error occurred while saving the file.")

        else:
            # Handle cases where Ollama returned something, but it wasn't the expected dict structure
            logging.warning("LLM response parsed, but is missing 'startNodeId' or 'nodes', or is not a dictionary.")
            print("\nWarning: Generated data structure seems incomplete or invalid.")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"invalid_structure_{timestamp}.json"
            filepath = os.path.join(output_dir_path, filename)
            try:
                logging.info(f"Attempting to save invalid structure data to {filepath}")
                with open(filepath, 'w') as f:
                    json.dump(generated_story, f, indent=2) # Save whatever we got
                logging.info(f"Saved invalid structure data to {filepath}")
            except Exception as e:
                logging.error(f"Failed to save invalid structure data: {e}", exc_info=True)


    else:
        # This case handles None returned from get_llm_cyoa_json (errors logged there)
        logging.error("Failed to get valid data from get_llm_cyoa_json.")
        # User message already printed in the exception handlers
        # print("\nError: Story generation failed. Check logs for details.") # Redundant now

    logging.info("--- CYOA Generation Script Finished ---")

# --- Trigger Main Function ---

if __name__ == "__main__":
    # Basic check: Can we even connect to the base Ollama URL?
    try:
        logging.debug(f"Performing initial connectivity check to {API_URL.replace('/api/chat','')}...")
        requests.get(API_URL.replace('/api/chat','/'), timeout=5) # Check base URL quickly
        logging.debug("Initial connectivity check successful.")
    except requests.exceptions.ConnectionError:
        logging.error(f"Initial check failed: Could not connect to Ollama base URL at {API_URL.replace('/api/chat','')}. Is Ollama running?")
        print(f"CRITICAL: Cannot connect to Ollama at {API_URL.replace('/api/chat','')}. Please ensure Ollama is running before executing the script.")
        # Exit early if we can't even connect
        exit()
    except Exception as e:
        logging.warning(f"Initial connectivity check encountered an issue: {e}")
        # Don't exit, maybe it was a temporary glitch

    main()