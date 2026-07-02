import ollama
import json
import os
from datetime import datetime
import re

# --- Helper Functions ---

def setup_session():
    """Creates a new session directory and returns its path and the paths for log files."""
    os.makedirs("sessions", exist_ok=True)
    session_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_dir = os.path.join("sessions", session_timestamp)
    os.makedirs(session_dir, exist_ok=True)
    paths = {
        'agent1_prompts': os.path.join(session_dir, 'agent1_prompts.json'),
        'agent2_prompts': os.path.join(session_dir, 'agent2_prompts.json'),
        'conversation_log': os.path.join(session_dir, 'conversation_log.json'),
        'plan': os.path.join(session_dir, 'master_plan.txt'),
        'story': os.path.join(session_dir, 'story.json')
    }
    return session_dir, paths

def save_system_prompt(new_prompt, history_file_path):
    """Appends a new system prompt with a timestamp to its history file."""
    history = []
    if os.path.exists(history_file_path) and os.path.getsize(history_file_path) > 0:
        try:
            with open(history_file_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
                if not isinstance(history, list): history = []
        except (json.JSONDecodeError, IOError):
            history = []
    new_entry = {"timestamp": datetime.now().isoformat(), "system_prompt": new_prompt}
    history.append(new_entry)
    with open(history_file_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2)

def log_conversation_turn(log_path, agent_name, message, active_prompt):
    """Logs a single turn of the conversation to the main log file."""
    print(f"📝 Logging {agent_name}'s turn...")
    history = []
    if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
                if not isinstance(history, list): history = []
        except (json.JSONDecodeError, IOError):
            history = []
    new_turn = {"timestamp": datetime.now().isoformat(), "agent": agent_name, "active_system_prompt": active_prompt, "message": message}
    history.append(new_turn)
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2)
    print("✅ Turn logged successfully.")

def create_initial_plan(initial_task, model_name, chapter_count: int = 30):
    """
    Generates a numbered outline with *exactly* `chapter_count` chapters.
    Each line must start with the chapter number followed by a period and a brief title / synopsis.
    """
    print("🧠 Generating a strategic plan...")
    plan_generation_prompt = (
        "You are a master story architect.\n"
        f"The user wants a story about: \"{initial_task}\"\n\n"
        f"Produce a numbered list with exactly {chapter_count} chapters (1-{chapter_count}). "
        "Each line should be 'N. Chapter Title – one-sentence synopsis'.\n"
        "Return ONLY the list — no preamble or trailing text."
    )
    response = ollama.chat(model=model_name, messages=[{'role': 'user', 'content': plan_generation_prompt}])
    return clean_response(response['message']['content'])

def create_final_report(session_dir, model_name, initial_task):
    """Spawns a finalizer agent to read the structured story file and generate a high-quality HTML report."""
    print("\n" + "#"*20 + " PHASE 3: FINAL REPORT " + "#"*20)
    print("🤖 Spawning Finalizer Agent to compile results...")
    try:
        plan_path = os.path.join(session_dir, 'master_plan.txt')
        story_path = os.path.join(session_dir, 'story.json')

        with open(plan_path, 'r', encoding='utf-8') as f:
            master_plan = f.read()
        with open(story_path, 'r', encoding='utf-8') as f:
            story_content = json.load(f)

        story_for_prompt = json.dumps(story_content, indent=2)

        finalizer_prompt = f"""
You are a professional report generator. Your task is to synthesize a project's data into a polished, dark-themed, single-file HTML report.

**Project Data:**
1.  **Initial Task:** "{initial_task}"
2.  **Master Plan:**
{master_plan}
3.  **Completed Story Chapters (JSON):**
{story_for_prompt}

**Your Instructions:**
1.  Your primary goal is to create a beautiful, readable HTML version of the completed story.
2.  Start the report with the Master Plan inside its own 'card' div.
3.  After the plan, iterate through the provided JSON story data. For each chapter object, create a new 'card' div.
4.  Inside each chapter's card, use an `<h2>` tag for the chapter `title` and `<p>` tags for the chapter `content`.
5.  Generate a complete, self-contained HTML file using the provided CSS template. Ensure all content is properly escaped for HTML.

**Output ONLY the raw HTML code.** Start with `<!DOCTYPE html>`.

**HTML Template to Use:**
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Project Report: {initial_task}</title>
    <style>
        :root {{
            --bg-color: #1a1a1a;
            --text-color: #e0e0e0;
            --primary-color: #8a2be2;
            --card-bg: #2c2c2c;
            --border-color: #444;
            --header-font: 'Georgia', serif;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            line-height: 1.6;
            margin: 0;
            padding: 2rem;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
        }}
        h1, h2, h3 {{
            color: var(--primary-color);
            font-family: var(--header-font);
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 0.5rem;
        }}
        h1 {{ text-align: center; font-size: 2.5rem; border-bottom: none; }}
        .card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }}
        pre {{
            background-color: #111;
            padding: 1rem;
            border-radius: 5px;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-family: 'Courier New', Courier, monospace;
        }}
        ul {{ list-style-type: square; padding-left: 20px; }}
        strong {{ color: var(--primary-color); }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Project Report: {initial_task}</h1>
        
        <div class="card">
            <h2>Master Plan</h2>
            <pre>{master_plan}</pre>
        </div>

        <!-- 
        LLM: From here, generate the main body of the report.
        Based on the JSON data for the completed story, create a series of 'card' divs.
        Each card should represent one chapter from the story.
        Use <h2> for the chapter title and <p> for the content.
        
        Example for a story:
        <div class="card">
            <h2>Chapter 1: The Beginning</h2>
            <p>Once upon a time...</p>
        </div>
        -->

    </div>
</body>
</html>
```
"""
        response = ollama.chat(model=model_name, messages=[{'role': 'user', 'content': finalizer_prompt}])
        html_content = response['message']['content'].strip()
        
        raw_html_path = os.path.join(session_dir, 'raw_final_report_response.txt')
        with open(raw_html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"📄 Raw HTML response saved to: {raw_html_path}")

        if "```html" in html_content:
            html_content = html_content.split("```html")[1].strip()
        if "```" in html_content:
            html_content = html_content.split("```")[0].strip()
        
        report_path = os.path.join(session_dir, 'final_report.html')
        with open(report_path, 'w', encoding='utf-8') as f: f.write(html_content)
        print(f"✅ Final report successfully generated at: {report_path}")

    except FileNotFoundError:
        print(f"❌ Error: Could not find story files in {session_dir}. Was the story generated correctly?")
    except Exception as e:
        print(f"❌ Error during final report generation: {e}")

def extract_json_from_response(response_text):
    """Attempts to extract a JSON object from a response text."""
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return None

def extract_chapters(plan_text: str) -> list[str]:
    """
    Pull numbered chapters from the master plan, e.g.
        1. Chapter One: …
        2) Chapter Two …
    Returns an ordered list of raw chapter titles.
    """
    chapter_lines = re.findall(r'^\s*(\d+)[\.\)]\s*(.+)$', plan_text, flags=re.MULTILINE)
    return [title.strip() for _, title in chapter_lines]

def clean_response(response_text):
    """Removes any conversational or "thinking" tags from a response text."""
    return re.sub(r'<[^>]+>', '', response_text)

# --- Main Application Logic ---
def main():
    """Orchestrates a Director/Artist conversation to write a story chapter by chapter."""
    MODEL_NAME = 'llama3.1:latest'

    session_dir, paths = setup_session()
    agent1_prompts_path = paths['agent1_prompts']
    agent2_prompts_path = paths['agent2_prompts']
    conversation_log_path = paths['conversation_log']
    plan_path = paths['plan']
    story_path = paths['story']
    
    print("🤖 Director/Artist Conversation System Initialized 🤖")
    print(f"✅ Session logs will be saved to: {session_dir}")
    initial_task = input("Please provide the initial task or topic for the agents: ")

    master_plan = create_initial_plan(initial_task, MODEL_NAME, chapter_count=30)
    with open(plan_path, 'w', encoding='utf-8') as f: f.write(master_plan)
    print("\n" + "!"*20 + " MASTER PLAN ESTABLISHED " + "!"*20 + "\n" + master_plan + "\n" + "!"*62 + "\n")

    # NEW: Parse the chapters from the plan
    chapters = extract_chapters(master_plan)
    if not chapters:
        print("❌ No chapters detected in the master plan. Aborting.")
        return
    print(f"📝 Detected {len(chapters)} chapters.")

    conversation_history, last_message = [], ""
    story_data: list[dict] = [] # Will store {'title': ..., 'content': ...}

    try:
        for chap_idx, chap_title in enumerate(chapters, start=1):
            story_so_far = "\n\n".join(c['content'] for c in story_data) if story_data else \
                           "This is the first chapter."
            print("\n" + "="*20 + f" CHAPTER {chap_idx}: {chap_title} " + "="*20)
            
            # ---------- Director Phase ----------
            current_agent_name = "Agent 2 (Director)"
            director_meta_prompt = (
                "Create a system prompt for an AI Director overseeing continuity of a multi-chapter story.\n"
                f"Overall story request: \"{initial_task}\"\n"
                f"Master Plan:\n{master_plan}\n\n"
                f"Story so far:\n{story_so_far}\n\n"
                f"Your current job is to outline Chapter {chap_idx}: \"{chap_title}\" in 3-5 concise bullet points "
                "that logically follow from previous chapters and advance the plot. After the outline, "
                "output a JSON object with keys:\n"
                "  outline   – the bullet-point outline\n"
                "  next_task – an imperative sentence telling the Artist to write the chapter.\n"
                "Return ONLY the JSON."
            )

            meta_response = ollama.chat(model=MODEL_NAME, messages=[{'role': 'user', 'content': director_meta_prompt}])
            director_system_prompt = meta_response['message']['content'].strip().strip('"')
            save_system_prompt(director_system_prompt, paths['agent2_prompts'])
            print(f"💡 New Director Persona: \"{director_system_prompt[:80]}...\"")

            director_messages = [
                {'role': 'system', 'content': director_system_prompt},
                {'role': 'user', 'content': "Produce the outline JSON now."}
            ]
            director_reply = ollama.chat(model=MODEL_NAME, messages=director_messages)['message']['content']
            print(f"\n--- Director's JSON ---\n{director_reply}\n--- End Director ---")

            log_conversation_turn(paths['conversation_log'], current_agent_name, director_reply, director_system_prompt)
            conversation_history.append({'role': 'assistant', 'content': f"[{current_agent_name}]: {director_reply}"})
            
            # Extract the outline / task for Artist
            director_json = extract_json_from_response(director_reply) or {}
            outline = director_json.get("outline", "")
            next_task = director_json.get("next_task", f"Write Chapter {chap_idx}: {chap_title}")

            # ---------- Artist Phase ----------
            current_agent_name = "Agent 1 (Artist)"
            artist_meta_prompt = (
                "Create a system prompt for an AI Artist who is writing a chapter of a story.\n"
                f"Overall story request: \"{initial_task}\".\n"
                f"Master Plan:\n{master_plan}\n\n"
                f"Story so far:\n{story_so_far}\n\n"
                f"Current chapter title: \"{chap_title}\".\n"
                f"Director's outline:\n{outline}\n\n"
                "Instruct the Artist to write the full, polished prose for this chapter, "
                "maintaining consistency with previous chapters, characters, and tone. "
                "Return ONLY the raw text of the system prompt."
            )
            meta_response = ollama.chat(model=MODEL_NAME, messages=[{'role': 'user', 'content': artist_meta_prompt}])
            artist_system_prompt = meta_response['message']['content'].strip().strip('"')
            save_system_prompt(artist_system_prompt, paths['agent1_prompts'])
            print(f"🎨 New Artist Persona: \"{artist_system_prompt[:80]}...\"")

            artist_messages = [
                {'role': 'system', 'content': artist_system_prompt},
                {'role': 'user', 'content': next_task}
            ]
            artist_reply = ollama.chat(model=MODEL_NAME, messages=artist_messages)['message']['content']
            print(f"\n--- Artist's Chapter ---\n{artist_reply}\n--- End Artist ---")

            log_conversation_turn(paths['conversation_log'], current_agent_name, artist_reply, artist_system_prompt)
            conversation_history.append({'role': 'assistant', 'content': f"[{current_agent_name}]: {artist_reply}"})

            new_chapter_data = {"title": chap_title, "content": artist_reply}
            story_data.append(new_chapter_data)
            with open(story_path, 'w', encoding='utf-8') as f:
                json.dump(story_data, f, indent=2)

            last_message = artist_reply

    except KeyboardInterrupt:
        print("\nConversation interrupted by user.")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")

    create_final_report(session_dir, MODEL_NAME, initial_task)
    print("\n✅ Story finished. All logs and final report saved.")

if __name__ == "__main__":
    main()