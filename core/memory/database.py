import sqlite3
from pathlib import Path
from datetime import datetime
import json

DB_PATH = Path("data/codeturtle.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_connection():
    """Get SQLite connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize all tables"""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Conversations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. Repositories table (per conversation)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS repositories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT,
            repo_name TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)

    # 3. Reviews table (PRs and Issues)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT,
            repo_name TEXT,
            review_type TEXT,                    -- 'pr' or 'issue'
            number INTEGER,
            title TEXT,
            recommendation TEXT,
            summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)

    # 4. Chat History table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT,
            role TEXT,                           -- 'user' or 'agent'
            content TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)

    conn.commit()
    conn.close()
    print("[green]SQLite database initialized successfully.[/green]")


def create_conversation(conversation_id: str):
    """Create a new conversation/session"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO conversations (id) VALUES (?)",
        (conversation_id,)
    )
    conn.commit()
    conn.close()


def save_review(conversation_id: str, repo_name: str, review_type: str, 
                number: int, title: str, recommendation: str, summary: str):
    """Save a review (PR or Issue)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reviews 
        (conversation_id, repo_name, review_type, number, title, recommendation, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (conversation_id, repo_name, review_type, number, title, recommendation, summary))
    conn.commit()
    conn.close()


def get_reviews_for_repo(conversation_id: str, repo_name: str, limit: int = 5):
    """Get previous reviews of a repo in this conversation"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM reviews 
        WHERE conversation_id = ? AND repo_name = ?
        ORDER BY created_at DESC 
        LIMIT ?
    """, (conversation_id, repo_name, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_chat_message(conversation_id: str, role: str, content: str):
    """Save a chat message"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO chat_history (conversation_id, role, content)
        VALUES (?, ?, ?)
    """, (conversation_id, role, content))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()