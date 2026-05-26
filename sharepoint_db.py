# -*- coding: utf-8 -*-
"""
SQLite persistence layer for SharePoint file sync state.
Tracks which files have been downloaded and/or processed to avoid redundant work.
"""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Dict

from config import SHAREPOINT_STATE_DB
from logger import get_logger

logger = get_logger(__name__)

STATUS_CONCLUIDO = "concluido"
STATUS_CANCELADO = "cancelado"
_VALID_STATUSES = {STATUS_CONCLUIDO, STATUS_CANCELADO}

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sharepoint_files (
    drive_item_id       TEXT PRIMARY KEY,
    file_name           TEXT NOT NULL,
    remote_path         TEXT NOT NULL,
    local_path          TEXT,
    file_size           INTEGER,
    last_modified_remote TEXT,
    downloaded_at       TEXT,
    processed           INTEGER DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'concluido'
)
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SHAREPOINT_STATE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_status_column(conn: sqlite3.Connection) -> None:
    """Migra bases antigas adicionando a coluna status quando ausente."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(sharepoint_files)")}
    if "status" not in cols:
        conn.execute(
            "ALTER TABLE sharepoint_files "
            "ADD COLUMN status TEXT NOT NULL DEFAULT 'concluido'"
        )
        logger.info("Migrated sharepoint_files: added 'status' column (default 'concluido')")


def init_db() -> None:
    """Create the sharepoint_files table if it does not exist."""
    conn = _connect()
    try:
        conn.execute(_CREATE_TABLE)
        _ensure_status_column(conn)
        conn.commit()
        logger.debug("SQLite database initialized at %s", SHAREPOINT_STATE_DB)
    finally:
        conn.close()


def is_processed(drive_item_id: str) -> bool:
    """Return True if the file has already been processed."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT processed FROM sharepoint_files WHERE drive_item_id = ?",
            (drive_item_id,),
        ).fetchone()
        return bool(row and row["processed"])
    finally:
        conn.close()


def is_downloaded(drive_item_id: str) -> bool:
    """Return True if the file has already been downloaded."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT downloaded_at FROM sharepoint_files WHERE drive_item_id = ?",
            (drive_item_id,),
        ).fetchone()
        return bool(row and row["downloaded_at"])
    finally:
        conn.close()


def register_download(
    drive_item_id: str,
    file_name: str,
    remote_path: str,
    local_path: str,
    file_size: Optional[int] = None,
    last_modified_remote: Optional[str] = None,
) -> None:
    """Record that a file has been downloaded (upsert)."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO sharepoint_files
                (drive_item_id, file_name, remote_path, local_path,
                 file_size, last_modified_remote, downloaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(drive_item_id) DO UPDATE SET
                local_path = excluded.local_path,
                file_size  = excluded.file_size,
                last_modified_remote = excluded.last_modified_remote,
                downloaded_at = excluded.downloaded_at
            """,
            (drive_item_id, file_name, remote_path, local_path,
             file_size, last_modified_remote, now),
        )
        conn.commit()
        logger.debug("Registered download: %s -> %s", file_name, local_path)
    finally:
        conn.close()


def mark_processed(drive_item_id: str) -> None:
    """Mark a previously-downloaded file as processed."""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE sharepoint_files SET processed = 1 WHERE drive_item_id = ?",
            (drive_item_id,),
        )
        conn.commit()
    finally:
        conn.close()


def set_status_by_file_name(file_name: str, status: str) -> bool:
    """
    Atualiza a coluna ``status`` do arquivo pelo nome (basename).

    Args:
        file_name: nome do arquivo (basename, ex.: ``nfe_123.xml``).
        status: ``"concluido"`` ou ``"cancelado"``.

    Returns:
        True se alguma linha foi atualizada; False se o arquivo não
        está registrado no DB (ex.: processamento puramente local sem
        ter passado pelo --sync).
    """
    if status not in _VALID_STATUSES:
        raise ValueError(
            f"Status inválido: {status!r}. Esperado: {sorted(_VALID_STATUSES)}"
        )

    base = os.path.basename(file_name)
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE sharepoint_files SET status = ? WHERE file_name = ?",
            (status, base),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_stats() -> Dict[str, int]:
    """Return counters useful for summary logging."""
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM sharepoint_files").fetchone()[0]
        downloaded = conn.execute(
            "SELECT COUNT(*) FROM sharepoint_files WHERE downloaded_at IS NOT NULL"
        ).fetchone()[0]
        processed = conn.execute(
            "SELECT COUNT(*) FROM sharepoint_files WHERE processed = 1"
        ).fetchone()[0]
        cancelados = conn.execute(
            "SELECT COUNT(*) FROM sharepoint_files WHERE status = ?",
            (STATUS_CANCELADO,),
        ).fetchone()[0]
        return {
            "total": total,
            "downloaded": downloaded,
            "processed": processed,
            "cancelados": cancelados,
        }
    finally:
        conn.close()
