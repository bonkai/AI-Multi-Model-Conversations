import requests
import logging
from tkinter import *
import threading
from queue import Queue
import json
import time
import subprocess
import tkinter.ttk as ttk
import uuid
from datetime import datetime
from database_manager import DatabaseManager
import re
import tiktoken
import base64
import os
from tkinter import filedialog
from PIL import Image, ImageTk
import mimetypes
import io
from pathlib import Path
import sys

# At the very beginning of your script, add this code to import TkinterDnD
try:
    # Try to import TkinterDnD
    from tkinterdnd2 import TkinterDnD, DND_FILES
    has_dnd = True
except ImportError:
    # If not available, show a message and create a fallback
    print("TkinterDnD not found. Installing...")
    has_dnd = False
    try:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "tkinterdnd2"])
        from tkinterdnd2 import TkinterDnD, DND_FILES
        has_dnd = True
        print("TkinterDnD installed successfully.")
    except Exception as e:
        print(f"Could not install TkinterDnD: {e}")
        print("File drag and drop will not be available.")
        # Create dummy classes to avoid errors
        class DummyTkinterDnD:
            def __init__(self):
                pass
            def Tk(self):
                return Tk()
        TkinterDnD = DummyTkinterDnD()
        DND_FILES = ""

# Configure the logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s  -  %(levelname)s  -  %(message)s',
    handlers=[
        logging.FileHandler('chat_ait_debug.log'),
        logging.StreamHandler()
    ]
)

# LLaMA API configuration
API_URL = "http://localhost:11434/api/chat"
# MODEL_NAME = "deepseek-r1:32b"  # Local LLM model name deepseek-r1:8b
# MODEL_NAME = "deepseek-r1:8b"  # Local LLM model name deepseek-r1:8b
MODEL_NAME = "deepseek-r1:1.5b"  # Local LLM model name

# At the top with other constants
TOKEN_LIMIT = 128000  # Your current max_tokens value

class ChatApp:
    def __init__(self):
        if has_dnd:
            self.root = TkinterDnD.Tk()
        else:
            self.root = Tk()
        self.root.title("Chat with LLM")
        
        # Set minimum window size
        self.root.minsize(800, 600)
        
        # Create conversation history panel first
        conv_frame = Frame(self.root)
        conv_frame.pack(side=LEFT, fill=Y, padx=5, pady=5)
        
        # Conversation list
        self.conv_list = Listbox(conv_frame, width=30)
        self.conv_list.pack(fill=Y, expand=True, pady=(0, 5))
        self.conv_list.bind('<<ListboxSelect>>', self.load_conversation)
        
        # New conversation button
        new_conv_btn = Button(conv_frame, text="New Conversation", command=self.start_new_conversation)
        new_conv_btn.pack(fill=X, pady=2)
        
        # Refresh conversations button
        refresh_btn = Button(conv_frame, text="Refresh", command=self.load_conversation_list)
        refresh_btn.pack(fill=X, pady=2)
        
        # Create main frame that will expand
        main_frame = Frame(self.root)
        main_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=5, pady=5)
        
        # Create model selection frame
        model_frame = Frame(main_frame)
        model_frame.pack(fill=X, pady=(0, 5))
        
        Label(model_frame, text="Model:").pack(side=LEFT)
        self.model_var = StringVar()
        self.model_dropdown = ttk.Combobox(
            model_frame, 
            textvariable=self.model_var,
            state="readonly"
        )
        self.model_dropdown.pack(side=LEFT, fill=X, expand=True, padx=(5, 0))
        
        # Populate models
        self.refresh_models()
        
        # Create file upload area
        self.create_file_upload_area(main_frame)
        
        # Create UI elements
        self.system_prompt_label = Label(main_frame, text="System Prompt:")
        self.system_prompt_entry = Entry(main_frame)
        self.system_prompt_entry.pack(fill=X, pady=(0, 5))
        
        # Add this at a suitable place in your UI (perhaps as a default system prompt)
        self.system_prompt_entry.insert(0, """**ROLE:** You are a Novel Structure Architect AI.
**PRIMARY GOAL:** To analyze a short story summary and develop a comprehensive chapter outline for a full-length novel based upon it. The output should be a list of chapters, each with a brief, descriptive summary of its key contents.

**CORE TASK:**
1.  **Analyze Summary:** Carefully read the provided short story summary to identify the core concept, protagonist(s), primary goal/conflict, main antagonist/obstacle(s), setting, suggested beginning, middle, and end points, and overall tone or genre (if discernible).
2.  **Extrapolate Narrative Arc:** Expand the basic plot points from the summary into a plausible and engaging narrative arc suitable for a full-length novel. This involves:
    *   Establishing the initial setup and inciting incident.
    *   Developing rising action through a series of escalating conflicts, challenges, revelations, or turning points.
    *   Identifying a clear climax where the central conflict comes to a head.
    *   Mapping out the falling action and resolution.
    *   Considering necessary subplots or character arcs that support the main story.
3.  **Structure into Chapters:** Divide the complete narrative arc into a logical sequence of chapters. Aim for a number of chapters appropriate for a standard full-length novel (e.g., typically 20-40 chapters, but adjust based on the perceived complexity of the story, unless the user specifies a target).
4.  **Summarize Each Chapter:** For *each* chapter in the sequence, write a brief summary (typically 1-3 sentences). This summary should clearly state:
    *   The main event(s) occurring in the chapter.
    *   The primary character focus or point-of-view character (if applicable).
    *   Key information revealed or plot advancements made.
    *   Significant character development or relationship changes.
5.  **Ensure Flow and Pacing:** The sequence of chapters should demonstrate logical progression, build narrative tension effectively, and vary pacing as appropriate for the story arc (e.g., introducing key elements early, building stakes, culminating in a climax, providing resolution).

**INPUTS FOR THE PROCESS:**
1.  **The Short Story Summary:** Provided by the user.
2.  **Optional User Specifications:** User might provide desired genre, approximate target chapter count, or specific plot beats they want included.

**OUTPUT EXPECTATIONS:**
*   A numbered list of chapters (e.g., Chapter 1, Chapter 2, ... Chapter X).
*   For each chapter number, a concise summary (1-3 sentences) describing its core content and purpose within the overall narrative.
*   The total number of chapters should feel appropriate for a full-length novel derived from the summary's scope.

**INTERACTION MODE:**
*   If the summary is very brief or ambiguous, ask clarifying questions *before* generating the full outline (e.g., "To build the rising action, would the protagonist face primarily internal struggles or external antagonists?").
*   Present the complete chapter list with summaries as the primary output.
*   Be prepared to revise the outline based on user feedback (e.g., "Can we add a chapter focusing on the antagonist's perspective?" or "Let's break down Chapter 10 into two separate chapters.").

**EXAMPLE OUTPUT FORMAT:**

1.  **Chapter 1:** Introduce the protagonist, Elara, in her ordinary life as a village healer. Hint at a past tragedy. Establish the peaceful setting before the inciting incident occurs – a strange blight appears on the village's crops.
2.  **Chapter 2:** Elara attempts traditional remedies for the blight, which fail. Village elders express concern, referencing an old legend. Elara feels a personal responsibility to find a cure.
3.  **Chapter 3:** A travelling scholar arrives, mentioning rumours of a hidden Sunstone grove said to hold potent healing magic. He warns the journey is perilous. Elara resolves to seek the grove, facing initial opposition from the elders.
    ... (and so on for all chapters) ...""")
        
        self.uestion_label = Label(main_frame, text="Question:")
        self.uestion_label.pack(fill=X)
        self.question_entry = Entry(main_frame)
        self.question_entry.pack(fill=X, pady=(0, 5))
        
        # Create button frame
        button_frame = Frame(main_frame)
        button_frame.pack(fill=X, pady=(0, 5))
        
        self.send_button = Button(
            button_frame,
            text="Ask",
            command=self.start_chat_thread
        )
        self.send_button.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        
        self.stop_button = Button(
            button_frame,
            text="⏹ Stop",
            command=self.stop_generation,
            state=DISABLED,
            fg='red',
            font=('Arial', 10, 'bold')
        )
        self.stop_button.pack(side=LEFT)
        
        # Create frame for response text and scrollbar
        response_frame = Frame(main_frame)
        response_frame.pack(fill=BOTH, expand=True)
        
        # Add scrollbar
        scrollbar = Scrollbar(response_frame)
        scrollbar.pack(side=RIGHT, fill=Y)
        
        # Response display with scrollbar
        self.response_text = Text(
            response_frame, 
            wrap=WORD, 
            bg='black',
            font=('Courier', 20)
        )
        self.response_text.pack(side=LEFT, fill=BOTH, expand=True)
        
        # Configure text tags for different colors and formatting
        self.response_text.tag_configure('thinking', foreground='light blue', font=('Courier', 16))
        self.response_text.tag_configure('regular', foreground='lime', font=('Courier', 20))
        self.response_text.tag_configure('separator', foreground='gray', font=('Courier', 12))
        self.response_text.tag_configure('role', foreground='yellow', font=('Courier', 16, 'bold'))
        self.response_text.tag_configure('tokens', foreground='orange', font=('Courier', 12))
        
        # Configure scrollbar
        scrollbar.config(command=self.response_text.yview)
        self.response_text.config(yscrollcommand=scrollbar.set)
        
        # Initialize variables
        self.running = False
        self.response_queue = Queue()
        self.is_thinking = False
        
        # Add database manager
        self.db = DatabaseManager()
        
        # Initialize conversation tracking
        self.current_conversation_id = None
        self.current_conversation_messages = []
        
        # Load existing conversations
        self.load_conversation_list()
        
        # Create token counter label frame
        token_frame = Frame(main_frame, bg='black')
        token_frame.pack(fill=X, pady=(0, 5))
        self.token_label = Label(
            token_frame, 
            text="Tokens: 0 / 128,000 (0.0%)", 
            fg='orange',
            bg='black',
            font=('Courier', 12)
        )
        self.token_label.pack(fill=X)
        
        self.stop_event = threading.Event()  # Add this with other instance variables
        
        # Add file tracking variables
        self.uploaded_files = []
        self.file_preview_images = []

    def refresh_models(self):
        try:
            result = subprocess.run(['ollama', 'list'], capture_output=True, text=True)
            if result.returncode == 0:
                models = []
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                for line in lines:
                    if line.strip():
                        model_name = line.split()[0]  # Get first column (NAME)
                        models.append(model_name)
                self.model_dropdown['values'] = models
                if models:
                    self.model_var.set(models[0])
                else:
                    self.model_var.set("")
                logging.info(f"Found models: {models}")
            else:
                logging.error(f"Error running ollama list: {result.stderr}")
                self.model_dropdown['values'] = [MODEL_NAME]
                self.model_var.set(MODEL_NAME)
        except Exception as e:
            logging.error(f"Error refreshing models: {str(e)}")
            self.model_dropdown['values'] = [MODEL_NAME]
            self.model_var.set(MODEL_NAME)

    def add_conversation_ui(self):
        conv_frame = Frame(self.root)
        conv_frame.pack(side=LEFT, fill=Y, padx=5)
        self.conv_list = Listbox(conv_frame, width=25)
        self.conv_list.pack(fill=Y, expand=True)
        self.conv_list.bind('<<ListboxSelect>>', self.load_conversation)
        new_conv_btn = Button(conv_frame, text="New Conversation", command=self.start_new_conversation)
        new_conv_btn.pack(pady=5)
        refresh_btn = Button(conv_frame, text="Refresh", command=self.load_conversation_list)
        refresh_btn.pack(pady=5)
        self.load_conversation_list()

    def start_new_conversation(self):
        self.current_conversation_id = None
        self.system_prompt_entry.delete(0, END)
        self.question_entry.delete(0, END)
        self.clear_response()
        self.current_conversation_messages = []
        self.update_token_count()

    def load_conversation_list(self):
        self.conv_list.delete(0, END)
        conversations = self.db.get_conversations()
        for conv in conversations:
            self.conv_list.insert(END, f"{conv[2]} - {conv[1].strftime('%Y-%m-%d %H:%M')}")
            
    def load_conversation(self, event):
        selection = self.conv_list.curselection()
        if not selection:
            return
        index = selection[0]
        conversations = self.db.get_conversations()
        if index < len(conversations):
            conv_id = conversations[index][0]
            self.current_conversation_id = conv_id
            messages = self.db.get_messages(conv_id)
            self.clear_response()
            self.system_prompt_entry.delete(0, END)
            system_prompt = self.db.get_conversation_system_prompt(conv_id)
            self.system_prompt_entry.insert(0, system_prompt)
            self.response_text.config(state=NORMAL)
            for msg in messages:
                role = "User" if msg[2] == "user" else "Assistant"
                self.response_text.insert(END, f"\n{role}:\n", 'role')
                self.response_text.insert(END, f"{msg[3]}\n", 'regular')
                self.response_text.insert(END, "="*50 + "\n", 'separator')
            self.response_text.config(state=DISABLED)
            self.current_conversation_messages = messages
            self.update_token_count()

    def start_chat_thread(self):
        if not self.running:
            self.send_button.config(text="Processing...", state=DISABLED)
            self.response_text.config(state=NORMAL)
            self.response_text.insert(END, "\nThinking...", 'thinking')
            self.response_text.see(END)
            self.response_text.config(state=DISABLED)
            self.root.update()
            if self.current_conversation_id:
                current_prompt = self.db.get_conversation_system_prompt(self.current_conversation_id)
                new_prompt = self.system_prompt_entry.get().strip()
                if current_prompt != new_prompt:
                    self.db.update_conversation_system_prompt(
                        self.current_conversation_id,
                        new_prompt
                    )
                    logging.info("Updated system prompt for existing conversation")
            if not self.current_conversation_id:
                self.current_conversation_id = self.db.create_conversation(
                    title="New Chat " + datetime.now().strftime("%H:%M"),
                    system_prompt=self.system_prompt_entry.get().strip()
                )
                self.clear_response()
            logging.info("Starting chat thread...")
            self.running = True
            self.stop_button.config(state=NORMAL)
            system_rompt = self.system_prompt_entry.get().strip()
            question = self.question_entry.get().strip()
            logging.debug(f"System Prompt: {system_rompt}")
            logging.debug(f"Question:       {question}")
            chat_thread = threading.Thread(
                target=self.stream_chat,
                args=(system_rompt, question)
             )
            logging.info(f"Thread started with ID: {threading.get_ident()}")
            chat_thread.start()
            self.root.after(100, self.update_ui)

    def clear_response(self):
        self.response_text.config(state=NORMAL)
        self.response_text.delete(1.0, END)
        self.response_text.update()
        self.response_text.config(state=DISABLED)

    def stream_chat(self, system_rompt, question):
        try:
            # Save the user message to the database
            message_id = self.save_message_with_context(
                role="user",
                content=question,
                conversation_id=self.current_conversation_id
            )
            logging.info(f"Saved user message (ID: {message_id}): {question}")
            
            logging.info("Preparing API request...")
            selected_model = self.model_var.get()
            
            conversation_history = []
            if self.current_conversation_id:
                context_messages = self.db.get_context_messages(self.current_conversation_id)
                logging.info(f"Raw context messages: {context_messages}")
                conversation_history = [
                    {"role": msg[0], "content": msg[1]} 
                    for msg in context_messages
                ]
                logging.info("=== Conversation Context ===")
                for i, msg in enumerate(conversation_history, 1):
                    logging.info(f"[{i}] {msg['role']}: {msg['content']}")
            
            if system_rompt.strip() and not any(
                msg['role'] == 'system' for msg in conversation_history
            ):
                conversation_history.insert(0, {
                    "role": "system",
                    "content": system_rompt
                })
                logging.info(f"Added system prompt to context: {system_rompt}")
            
            # Prepare payload for API request
            payload_dict = {
                "model": selected_model,
                "messages": conversation_history,
                "temperature": 0.8,
                "num_predict": 32768,
                "stream": True,
                "reset": False
            }
            
            # Process any files for API inclusion
            prepared_files = self.prepare_files_for_api()
            if prepared_files:
                image_data_list = []
                text_files_content = ""
                for file in prepared_files:
                    if file['type'] == 'image':
                        image_data_list.append(file['data'])
                        logging.info(f"Added image: {file['name']} ({self.format_file_size(file['size'])})")
                    else:
                        text_files_content += f"\n\nFile: {file['name']} (Type: {file['type']})\n"
                        if file['type'] in ['text', 'code']:
                            text_files_content += f"```\n{file['data']}\n```\n"
                        else:
                            text_files_content += f"[Binary content, size: {self.format_file_size(file['size'])}]\n"
                # If images are present, attach them to the latest user message
                if image_data_list:
                    base64_images = [base64.b64encode(img).decode('utf-8') for img in image_data_list]
                    # Find the last user message and add the "images" field
                    for message in reversed(conversation_history):
                        if message.get("role") == "user":
                            message["images"] = base64_images
                            logging.info("Attached images to the user message.")
                            break
                if text_files_content:
                    for i in range(len(conversation_history) - 1, -1, -1):
                        if conversation_history[i]['role'] == 'user':
                            conversation_history[i]['content'] += text_files_content
                            break
                logging.info(f"Enhanced request with {len(image_data_list)} images and {len(prepared_files) - len(image_data_list)} text files")
            
            logging.info(f"\nUsing model: {selected_model}")
            logging.debug(f"Payload structure: {json.dumps({k: '...' for k in payload_dict.keys()}, indent=2)}")
            
            start_time = time.time()
            with requests.post(API_URL, json=payload_dict, stream=True) as response:
                end_time = time.time()
                elapsed_time = end_time - start_time

                if response.status_code == 200:
                    logging.info(f"API request received successfully in {elapsed_time:.3f} seconds.")
                    
                    full_response = []
                    
                    for chunk_num, chunk in enumerate(response.iter_lines(), 1):
                        if self.stop_event.is_set() or not self.running:
                            logging.info("Stopping generation due to user request")
                            break
                        
                        if chunk:
                            decoded_chunk = chunk.decode('utf-8').strip()
                            try:
                                json_data = json.loads(decoded_chunk)
                                token_content = json_data.get('message', {}).get('content', '')
                                # logging.debug(f"[Chunk #{chunk_num}] Received message content: {token_content}")
                                self.response_queue.put(token_content)
                                # logging.debug(f"[Chunk #{chunk_num}] Added to queue.")
                                full_response.append(token_content)
                            except json.JSONDecodeError as e:
                                logging.error(f"JSON decode error for chunk #{chunk_num}: {str(e)}")

                    if self.stop_event.is_set():
                        logging.warning("Generation stopped prematurely by user")
                        self.stop_event.clear()

                    if full_response:
                        assistant_response = ''.join(full_response)
                        logging.info("\n=== Assistant's Full Response ===")
                        logging.info(assistant_response)
                        
                        message_id = self.save_message_with_context(
                            role="assistant",
                            content=assistant_response,
                            conversation_id=self.current_conversation_id
                        )
                        logging.info(f"Saved assistant response (ID: {message_id})")
                        
                        cleaned_response = self.clean_thinking_tags(assistant_response)
                        logging.info("\n=== Cleaned Response (Saved to Context) ===")
                        logging.info(cleaned_response)
                        
                        self.update_token_count()

                else:
                    logging.error(f"API request failed with status code {response.status_code}: {response.text}")
                    self.response_queue.put(f"ERROR: API request failed with status code {response.status_code}")

        except Exception as e:
            logging.error(f"An error occurred in stream_chat: {str(e)}")
        
        self.response_queue.put(None)
        logging.info("Streaming process completed.")

    def clean_thinking_tags(self, content):
        cleaned = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
        cleaned = cleaned.replace('<think>', '').replace('</think>', '')
        return cleaned.strip()

    def update_ui(self):
        if not self.response_queue.empty():
            token_content = self.response_queue.get()
            # logging.debug(f"[UI Update] Received content: {token_content}")

            if token_content is None:
                self.running = False
                self.send_button.config(text="Ask", state=NORMAL)
                self.stop_button.config(state=DISABLED)
                self.response_text.config(state=NORMAL)
                self.response_text.insert(END, "\n" + "="*50 + "\n\n", 'separator')
                self.response_text.config(state=DISABLED)
                logging.info("Streaming has completed.")
                return
            
            try:
                self.response_text.config(state=NORMAL)
                
                if '<think>' in token_content:
                    self.is_thinking = True
                    token_content = token_content.replace('<think>', '')
                    if not hasattr(self, 'thinking_header_added'):
                        self.response_text.insert(END, "\nThinking Process:\n", 'role')
                        self.thinking_header_added = True
                
                if '</think>' in token_content:
                    self.is_thinking = False
                    token_content = token_content.replace('</think>', '')
                    self.response_text.insert(END, "\nResponse:\n", 'role')
                    self.thinking_header_added = False
                
                if token_content.strip():
                    tag = 'thinking' if self.is_thinking else 'regular'
                    self.response_text.insert(END, token_content, tag)
                
                self.response_text.see(END)
                self.response_text.config(state=DISABLED)
                # logging.debug(f"[UI Update] Successfully added content: {token_content}")
            except Exception as e:
                logging.error(f"Error updating UI: {str(e)}")

        if self.running:
            self.root.after(100, self.update_ui)

    def run(self):
        self.root.mainloop()

    def save_message_with_context(self, role, content, conversation_id):
        message_id = self.db.save_message(
            conversation_id=conversation_id,
            role=role,
            content=content
        )
        
        if message_id:
            cleaned_content = (
                self.clean_thinking_tags(content) 
                if role == "assistant" 
                else content
            )
            
            self.db.save_context_message(
                message_id=message_id,
                conversation_id=conversation_id,
                cleaned_content=cleaned_content
            )
        return message_id

    def count_tokens(self, text):
        try:
            encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
            return len(encoding.encode(text))
        except Exception as e:
            logging.error(f"Error counting tokens: {e}")
            return 0

    def update_token_count(self):
        try:
            total_tokens = 0
            system_prompt = self.system_prompt_entry.get().strip()
            if system_prompt:
                total_tokens += self.count_tokens(system_prompt)
            
            if self.current_conversation_id:
                context_messages = self.db.get_context_messages(self.current_conversation_id)
                for msg in context_messages:
                    total_tokens += self.count_tokens(msg[1])
            
            token_info = f"Tokens: {total_tokens:,} / {TOKEN_LIMIT:,} ({(total_tokens/TOKEN_LIMIT*100):.1f}%)"
            self.token_label.config(text=token_info)
            
        except Exception as e:
            logging.error(f"Error updating token count: {e}")

    def stop_generation(self):
        logging.warning("USER REQUESTED GENERATION STOP")
        self.stop_button.config(state=DISABLED)
        self.running = False
        
        while not self.response_queue.empty():
            self.response_queue.get()
            
        self.response_text.config(state=NORMAL)
        self.response_text.insert(END, "\n\n[ GENERATION STOPPED BY USER ]\n", 'tokens')
        self.response_text.see(END)
        self.response_text.config(state=DISABLED)
        
        self.send_button.config(state=NORMAL)
        self.stop_event.set()

    def create_file_upload_area(self, parent):
        file_frame = Frame(parent, bd=2, relief=GROOVE)
        file_frame.pack(fill=X, pady=(0, 5))
        Label(file_frame, text="Drop Files for Context:", font=('Arial', 10, 'bold')).pack(pady=(5, 0))
        self.drop_area = Frame(file_frame, bg='#f0f0f0', height=80)
        self.drop_area.pack(fill=X, padx=10, pady=5)
        if has_dnd:
            self.drop_area.drop_target_register(DND_FILES)
            self.drop_area.dnd_bind('<<Drop>>', self.handle_drop)
        else:
            Label(self.drop_area, text="Drag & Drop not available\nUse Browse button", 
                  bg='#f0f0f0', fg='red').pack(pady=5)
        self.drop_label = Label(self.drop_area, text="Drag & Drop Files Here", bg='#f0f0f0')
        self.drop_label.pack(expand=True, fill=BOTH)
        file_button_frame = Frame(file_frame)
        file_button_frame.pack(fill=X, padx=10, pady=(0, 5))
        browse_btn = Button(file_button_frame, text="Browse Files", command=self.browse_files)
        browse_btn.pack(side=LEFT, padx=(0, 5))
        clear_btn = Button(file_button_frame, text="Clear Files", command=self.clear_files)
        clear_btn.pack(side=LEFT)
        self.preview_frame = Frame(file_frame)
        self.preview_frame.pack(fill=X, padx=10, pady=(0, 5))
        self.file_list_frame = Frame(self.preview_frame)
        self.file_list_frame.pack(fill=X)

    def handle_drop(self, event):
        file_paths = self.parse_drop_data(event.data)
        self.process_files(file_paths)

    def parse_drop_data(self, data):
        if os.name == 'nt':
            file_paths = data.split('} {')
            file_paths[0] = file_paths[0].lstrip('{')
            file_paths[-1] = file_paths[-1].rstrip('}')
        else:
            file_paths = data.split()
        return file_paths

    def browse_files(self):
        file_paths = filedialog.askopenfilenames(
            title="Select Files for Context",
            filetypes=[
                ("All Files", "*.*"),
                ("Images", "*.png *.jpg *.jpeg *.gif *.bmp"),
                ("Documents", "*.pdf *.docx *.txt"),
                ("Code Files", "*.py *.js *.html *.css *.java *.cpp")
            ]
        )
        if file_paths:
            self.process_files(file_paths)

    def process_files(self, file_paths):
        for path in file_paths:
            if path and os.path.exists(path):
                file_size = os.path.getsize(path)
                if file_size > 20 * 1024 * 1024:
                    self.show_error(f"File too large: {os.path.basename(path)}")
                    continue
                file_type = self.get_file_type(path)
                file_info = {
                    'path': path,
                    'name': os.path.basename(path),
                    'type': file_type,
                    'size': file_size,
                    'data': None
                }
                self.uploaded_files.append(file_info)
                self.add_file_to_preview(file_info)
        self.update_drop_area_status()

    def get_file_type(self, file_path):
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.py', '.js', '.html', '.css', '.java', '.cpp', '.c', '.h']:
                return 'code'
            elif ext in ['.txt', '.md', '.csv']:
                return 'text'
            else:
                return 'binary'
        if mime_type.startswith('image/'):
            return 'image'
        elif mime_type.startswith('text/'):
            return 'text'
        elif mime_type == 'application/pdf':
            return 'pdf'
        elif 'wordprocessing' in mime_type or mime_type == 'application/msword':
            return 'document'
        elif 'spreadsheet' in mime_type:
            return 'spreadsheet'
        else:
            return 'binary'

    def add_file_to_preview(self, file_info):
        file_item = Frame(self.file_list_frame, bd=1, relief=SOLID)
        file_item.pack(fill=X, pady=2)
        icon_text = self.get_file_icon(file_info['type'])
        icon_label = Label(file_item, text=icon_text, font=('Arial', 10), width=3)
        icon_label.pack(side=LEFT, padx=5)
        name_label = Label(file_item, text=file_info['name'], anchor='w')
        name_label.pack(side=LEFT, fill=X, expand=True, padx=5)
        size_text = self.format_file_size(file_info['size'])
        size_label = Label(file_item, text=size_text)
        size_label.pack(side=LEFT, padx=5)
        remove_btn = Button(
            file_item, 
            text="✕", 
            font=('Arial', 8),
            command=lambda fi=file_info, item=file_item: self.remove_file(fi, item)
        )
        remove_btn.pack(side=LEFT, padx=5)
        file_info['frame'] = file_item

    def get_file_icon(self, file_type):
        icons = {
            'image': '🖼️',
            'text': '📄',
            'code': '💻',
            'pdf': '📑',
            'document': '📝',
            'spreadsheet': '📊',
            'binary': '📦'
        }
        return icons.get(file_type, '📎')

    def format_file_size(self, size_bytes):
        for unit in ['B', 'KB', 'MB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} GB"

    def remove_file(self, file_info, item_frame):
        self.uploaded_files.remove(file_info)
        item_frame.destroy()
        self.update_drop_area_status()

    def clear_files(self):
        self.uploaded_files = []
        for widget in self.file_list_frame.winfo_children():
            widget.destroy()
        self.update_drop_area_status()

    def update_drop_area_status(self):
        if self.uploaded_files:
            self.drop_label.config(text=f"{len(self.uploaded_files)} files ready")
        else:
            self.drop_label.config(text="Drag & Drop Files Here")

    def show_error(self, message):
        import tkinter.messagebox as messagebox
        messagebox.showerror("Error", message)

    def prepare_files_for_api(self):
        prepared_files = []
        for file_info in self.uploaded_files:
            file_path = file_info['path']
            file_type = file_info['type']
            try:
                file_data_info = file_info.copy()
                if file_type == 'image':
                    with open(file_path, 'rb') as f:
                        file_data_info['data'] = f.read()
                elif file_type in ['text', 'code']:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        file_data_info['data'] = f.read()
                elif file_type == 'pdf':
                    with open(file_path, 'rb') as f:
                        file_data_info['data'] = f.read()
                else:
                    with open(file_path, 'rb') as f:
                        file_data_info['data'] = f.read()
                prepared_files.append(file_data_info)
            except Exception as e:
                logging.error(f"Error preparing file {file_path}: {str(e)}")
        return prepared_files

    def guess_image_format(self, image_path):
        ext = os.path.splitext(image_path)[1].lower().lstrip('.')
        if ext in ['jpg', 'jpeg']:
            return 'jpeg'
        elif ext in ['png', 'gif', 'webp', 'bmp', 'tiff', 'svg']:
            return ext
        mime_type, _ = mimetypes.guess_type(image_path)
        if mime_type and mime_type.startswith('image/'):
            return mime_type.split('/')[1]
        return 'jpeg'

if __name__ == "__main__":
    app = ChatApp()
    app.run()