import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "monitoring.db"

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            session_id TEXT,
            question TEXT,
            reponse TEXT,
            nb_chunks INTEGER,
            ville_filtre TEXT,
            duree_ms REAL,
            est_echec INTEGER DEFAULT 0,
            feedback INTEGER            -- NULL / 1 (👍) / 0 (👎)
        )
    """)
    conn.commit()
    conn.close()


def logger_interaction(session_id: str, question: str, reponse: str,
                       nb_chunks: int, ville: str, duree_ms: float) -> int:
    """Enregistre une interaction. Retourne l'id de la ligne créée."""
    phrases_echec = [
        "je n'ai pas trouvé",
        "aucun événement",
        "ne couvre pas cette période",
        "je suis spécialisé"
    ]
    est_echec = int(any(p in reponse.lower() for p in phrases_echec))

    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        """INSERT INTO interactions
           (timestamp, session_id, question, reponse, nb_chunks,
            ville_filtre, duree_ms, est_echec)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), session_id, question,
         reponse[:500], nb_chunks, ville or "", round(duree_ms, 1), est_echec)
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def logger_feedback(interaction_id: int, feedback: int):
    """Met à jour le feedback (1 = positif, 0 = négatif)."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE interactions SET feedback = ? WHERE id = ?",
        (feedback, interaction_id)
    )
    conn.commit()
    conn.close()


def charger_interactions() -> list:
    """Charge toutes les interactions pour le dashboard."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM interactions ORDER BY timestamp DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]