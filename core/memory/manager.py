from core.memory.database import (
    init_db,
    create_conversation,
    save_review,
    get_reviews_for_repo,
    save_chat_message,
    get_connection
)
from datetime import datetime
import uuid


class MemoryManager:
    def __init__(self):
        init_db()  # Ensure database is initialized

    def create_new_session(self) -> str:
        """Create a new conversation/session and return its ID"""
        conversation_id = str(uuid.uuid4())
        create_conversation(conversation_id)
        print(f"[green]New session created with ID: {conversation_id}[/green]")
        return conversation_id

    def save_review(self, conversation_id: str, repo_name: str, 
                    review_type: str, number: int, title: str, 
                    recommendation: str, summary: str):
        """Save a review (PR or Issue)"""
        save_review(
            conversation_id=conversation_id,
            repo_name=repo_name,
            review_type=review_type,
            number=number,
            title=title,
            recommendation=recommendation,
            summary=summary
        )
        print(f"[green]Review saved for {repo_name} #{number}[/green]")

    def get_recent_reviews(self, conversation_id: str, repo_name: str, limit: int = 5):
        """Get recent reviews for a repository in this conversation"""
        return get_reviews_for_repo(conversation_id, repo_name, limit)

    def save_chat(self, conversation_id: str, role: str, content: str):
        """Save a message in chat history"""
        save_chat_message(conversation_id, role, content)

    def get_chat_history(self, conversation_id: str, limit: int = 20):
        """Get recent chat history for a session"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content, timestamp FROM chat_history 
            WHERE conversation_id = ?
            ORDER BY timestamp ASC
            LIMIT ?
        """, (conversation_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def add_repository_to_session(self, conversation_id: str, repo_name: str):
        """Add a repository to the current session"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO repositories (conversation_id, repo_name)
            VALUES (?, ?)
        """, (conversation_id, repo_name))
        conn.commit()
        conn.close()
        print(f"[green]Repository {repo_name} added to session.[/green]")

    def get_repositories_in_session(self, conversation_id: str):
        """Get all repositories in a session"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT repo_name FROM repositories 
            WHERE conversation_id = ?
        """, (conversation_id,))
        rows = cursor.fetchall()
        conn.close()
        return [row["repo_name"] for row in rows]