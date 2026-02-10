import mysql.connector
import uuid
import logging
import re

class DatabaseManager:
    def __init__(self):
        logging.info("Initializing DatabaseManager...")
        self.connection_params = {
            'host': 'localhost',
            'user': 'root',  # Update with your MySQL username
            'password': '',  # Update with your MySQL password
            'database': 'llm_memory',
            'allow_local_infile': True
        }
        self.create_tables()
        
        # Migrate any missing context messages
        migrated_count = self.migrate_missing_context_messages()
        if migrated_count > 0:
            logging.info(f"Migrated {migrated_count} messages to context_messages table")

    def create_tables(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Create conversations table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        id VARCHAR(36) PRIMARY KEY,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        title VARCHAR(255),
                        system_prompt TEXT
                    )
                """)
                
                # Create messages table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        conversation_id VARCHAR(36),
                        role ENUM('user', 'assistant', 'system'),
                        content TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                    )
                """)
                
                # Create context_messages table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS context_messages (
                        id INT PRIMARY KEY,
                        conversation_id VARCHAR(36),
                        cleaned_content TEXT,
                        FOREIGN KEY (id) REFERENCES messages(id),
                        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                    )
                """)
                conn.commit()
                logging.info("Tables created successfully")
        except mysql.connector.Error as err:
            logging.error(f"Error creating tables: {err}")

    def get_connection(self):
        return mysql.connector.connect(**self.connection_params)

    def create_conversation(self, title, system_prompt=""):
        try:
            conv_id = str(uuid.uuid4())
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO conversations (id, title, system_prompt) VALUES (%s, %s, %s)",
                    (conv_id, title, system_prompt)
                )
                conn.commit()
            return conv_id
        except mysql.connector.Error as err:
            logging.error(f"Error creating conversation: {err}")
            return None

    def save_message(self, conversation_id, role, content):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO messages (conversation_id, role, content)
                       VALUES (%s, %s, %s)""",
                    (conversation_id, role, content)
                )
                message_id = cursor.lastrowid
                conn.commit()
                return message_id
        except mysql.connector.Error as err:
            logging.error(f"Error saving message: {err}")
            return None

    def get_conversations(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, created_at, title 
                    FROM conversations 
                    ORDER BY created_at DESC
                """)
                return cursor.fetchall()
        except mysql.connector.Error as err:
            logging.error(f"Error fetching conversations: {err}")
            return []

    def get_messages(self, conversation_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, created_at, role, content
                    FROM messages
                    WHERE conversation_id = %s
                    ORDER BY created_at ASC
                """, (conversation_id,))
                return cursor.fetchall()
        except mysql.connector.Error as err:
            logging.error(f"Error fetching messages: {err}")
            return []

    def get_conversation_system_prompt(self, conv_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT system_prompt FROM conversations WHERE id = %s",
                    (conv_id,)
                )
                result = cursor.fetchone()
                return result[0] if result else ""
        except mysql.connector.Error as err:
            logging.error(f"Error fetching system prompt: {err}")
            return ""

    def update_conversation_system_prompt(self, conv_id, system_prompt):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE conversations SET system_prompt = %s WHERE id = %s",
                    (system_prompt, conv_id)
                )
                conn.commit()
            return True
        except mysql.connector.Error as err:
            logging.error(f"Error updating system prompt: {err}")
            return False

    def save_context_message(self, message_id, conversation_id, cleaned_content):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO context_messages (id, conversation_id, cleaned_content)
                       VALUES (%s, %s, %s)""",
                    (message_id, conversation_id, cleaned_content)
                )
                conn.commit()
            return True
        except mysql.connector.Error as err:
            logging.error(f"Error saving context message: {err}")
            return False

    def get_context_messages(self, conversation_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT m.role, cm.cleaned_content 
                    FROM context_messages cm
                    JOIN messages m ON cm.id = m.id
                    WHERE cm.conversation_id = %s
                    ORDER BY m.created_at ASC
                """, (conversation_id,))
                return cursor.fetchall()
        except mysql.connector.Error as err:
            logging.error(f"Error fetching context messages: {err}")
            return []

    def migrate_missing_context_messages(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get all messages that don't have corresponding context entries
                cursor.execute("""
                    SELECT m.id, m.conversation_id, m.role, m.content
                    FROM messages m
                    LEFT JOIN context_messages cm ON m.id = cm.id
                    WHERE cm.id IS NULL
                """)
                
                missing_messages = cursor.fetchall()
                
                for msg in missing_messages:
                    msg_id, conv_id, role, content = msg
                    # Clean content if it's an assistant message
                    cleaned_content = (
                        re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
                        if role == 'assistant'
                        else content
                    )
                    
                    # Insert into context_messages
                    cursor.execute(
                        """INSERT INTO context_messages (id, conversation_id, cleaned_content)
                           VALUES (%s, %s, %s)""",
                        (msg_id, conv_id, cleaned_content)
                    )
                
                conn.commit()
                return len(missing_messages)
        except mysql.connector.Error as err:
            logging.error(f"Error migrating context messages: {err}")
            return 0 