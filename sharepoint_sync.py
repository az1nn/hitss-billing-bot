# -*- coding: utf-8 -*-
"""
SharePoint synchronisation module.
Connects to SharePoint via Microsoft Graph, traverses all folders recursively,
and downloads new PDF/XML files that have not yet been processed.
"""

import os
import sys
from typing import Optional, List, Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import msal
import requests

from config import DOWNLOAD_FOLDER, OUTPUT_FOLDER
from logger import get_logger
import sharepoint_db

logger = get_logger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPE = ["https://graph.microsoft.com/.default"]

_SUPPORTED_EXTENSIONS = (".pdf", ".xml")

# ---------------------------------------------------------------------------
# Connection helpers (reuses logic from sharepoint_connection_test.py)
# ---------------------------------------------------------------------------

_ENV_KEYS = (
    "SHAREPOINT_CLIENT_ID",
    "SHAREPOINT_CLIENT_SECRET",
    "SHAREPOINT_TENANT_ID",
    "SHAREPOINT_SITE_ID",
    "SHAREPOINT_DRIVE_ID",
)


def _get_config() -> Optional[Dict[str, str]]:
    config = {k: os.environ.get(k, "").strip() for k in _ENV_KEYS}
    missing = [k for k, v in config.items() if not v]
    if missing:
        logger.error("Missing SharePoint env vars: %s", ", ".join(missing))
        return None
    return config


def _get_token(config: Dict[str, str]) -> str:
    authority = f"https://login.microsoftonline.com/{config['SHAREPOINT_TENANT_ID']}"
    app = msal.ConfidentialClientApplication(
        config["SHAREPOINT_CLIENT_ID"],
        authority=authority,
        client_credential=config["SHAREPOINT_CLIENT_SECRET"],
    )
    result = app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" not in result:
        error = result.get("error_description") or result.get("error", "Unknown")
        raise RuntimeError(f"Token acquisition failed: {error}")
    return result["access_token"]


def connect() -> Optional[Dict[str, str]]:
    """
    Attempt to connect to SharePoint and return a dict with token + config.
    Returns None on failure and logs a notification suggestion.
    """
    config = _get_config()
    if not config:
        _suggest_notification("Missing SharePoint environment variables.")
        return None

    try:
        token = _get_token(config)
    except Exception as exc:
        _suggest_notification(f"Failed to acquire token: {exc}")
        return None

    headers = {"Authorization": f"Bearer {token}"}
    site_url = f"{GRAPH_BASE}/sites/{config['SHAREPOINT_SITE_ID']}"
    resp = requests.get(site_url, headers=headers, timeout=30)
    if resp.status_code != 200:
        _suggest_notification(
            f"Site request failed ({resp.status_code}): {resp.text[:300]}"
        )
        return None

    logger.info("SharePoint connection OK  (site: %s)",
                resp.json().get("displayName", "?"))
    return {**config, "token": token}


def _suggest_notification(reason: str) -> None:
    """Log the failure and suggest developer notification channels."""
    logger.error("SharePoint connection failed - %s", reason)
    logger.warning(
        "SUGESTAO: configure um mecanismo de notificacao para alertar os devs. "
        "Opcoes recomendadas:\n"
        "  1. Microsoft Teams Incoming Webhook (POST JSON para o canal)\n"
        "  2. Slack Incoming Webhook\n"
        "  3. E-mail via SMTP (smtplib)\n"
        "  4. PagerDuty / Opsgenie API\n"
        "Defina NOTIFICATION_WEBHOOK_URL no .env e implemente o envio "
        "quando necessario."
    )

# ---------------------------------------------------------------------------
# Graph API traversal
# ---------------------------------------------------------------------------


from config import SHAREPOINT_FOLDER_PATH

_MAX_DEPTH = 20


def _resolve_start_folder(token: str, site_id: str, drive_id: str) -> str:
    """
    Resolve SHAREPOINT_FOLDER_PATH to a Graph item ID.
    Returns the item ID, or "root" if no path is configured.
    """
    if not SHAREPOINT_FOLDER_PATH:
        return "root"

    path_encoded = requests.utils.quote(SHAREPOINT_FOLDER_PATH)
    url = (
        f"{GRAPH_BASE}/sites/{site_id}/drives/{drive_id}"
        f"/root:/{path_encoded}"
    )
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        logger.error(
            "Could not resolve folder path '%s': %s - %s",
            SHAREPOINT_FOLDER_PATH, resp.status_code, resp.text[:300],
        )
        raise RuntimeError(f"Folder path not found: {SHAREPOINT_FOLDER_PATH}")

    folder_id = resp.json()["id"]
    logger.info("Resolved folder '%s' -> ID %s", SHAREPOINT_FOLDER_PATH, folder_id)
    return folder_id


def list_files_recursive(
    token: str,
    site_id: str,
    drive_id: str,
    folder_id: str = "root",
    _depth: int = 0,
    _visited: set = None,
) -> List[Dict]:
    """
    Recursively list all .pdf and .xml files under *folder_id*.
    Each returned dict is the raw Graph API item (contains 'id', 'name',
    'parentReference', '@microsoft.graph.downloadUrl', etc.).
    """
    if _visited is None:
        _visited = set()

    if folder_id in _visited:
        logger.warning("Folder %s already visited, skipping (cycle detected)", folder_id)
        return []
    _visited.add(folder_id)

    if _depth > _MAX_DEPTH:
        logger.warning("Max depth (%d) reached at folder %s, skipping", _MAX_DEPTH, folder_id)
        return []

    headers = {"Authorization": f"Bearer {token}"}
    items: List[Dict] = []
    url = (
        f"{GRAPH_BASE}/sites/{site_id}/drives/{drive_id}"
        f"/items/{folder_id}/children"
    )

    while url:
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code != 200:
            logger.error("Error listing folder %s: %s - %s",
                         folder_id, resp.status_code, resp.text[:300])
            break

        data = resp.json()
        for item in data.get("value", []):
            if "folder" in item:
                folder_name = item.get("name", "?")
                child_count = item.get("folder", {}).get("childCount", "?")
                logger.info("  %sEntering folder: %s (%s items)",
                            "  " * _depth, folder_name, child_count)
                items.extend(
                    list_files_recursive(
                        token, site_id, drive_id, item["id"],
                        _depth=_depth + 1, _visited=_visited,
                    )
                )
            elif "file" in item:
                name = item.get("name", "")
                if name.lower().endswith(_SUPPORTED_EXTENSIONS):
                    logger.debug("  %sFound: %s", "  " * _depth, name)
                    items.append(item)

        url = data.get("@odata.nextLink")

    return items


def _remote_path(item: Dict) -> str:
    """Build a human-readable remote path from the Graph item metadata."""
    parent = item.get("parentReference", {}).get("path", "")
    return f"{parent}/{item.get('name', '')}"


def download_file(token: str, drive_id: str, item: Dict, dest_folder: str) -> Optional[str]:
    """
    Download a single file to *dest_folder*.
    Returns the local path on success, None on failure.
    """
    download_url = item.get("@microsoft.graph.downloadUrl")
    if not download_url:
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item['id']}/content"
        resp = requests.get(url, headers=headers, timeout=120, stream=True)
    else:
        resp = requests.get(download_url, timeout=120, stream=True)

    if resp.status_code != 200:
        logger.error("Download failed for %s: %s", item.get("name"), resp.status_code)
        return None

    local_path = os.path.join(dest_folder, item["name"])

    with open(local_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=8192):
            fh.write(chunk)

    logger.info("Downloaded: %s -> %s", item["name"], local_path)
    return local_path

# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def sync() -> bool:
    """
    Full sync flow:
    1. Connect to SharePoint
    2. Initialise SQLite database
    3. List all remote PDF/XML files recursively
    4. For each file not yet processed, download and register
    Returns True if sync completed, False on connection failure.
    """
    ctx = connect()
    if ctx is None:
        return False

    sharepoint_db.init_db()

    token = ctx["token"]
    site_id = ctx["SHAREPOINT_SITE_ID"]
    drive_id = ctx["SHAREPOINT_DRIVE_ID"]

    start_folder = _resolve_start_folder(token, site_id, drive_id)
    logger.info("Listing remote files from '%s'...", SHAREPOINT_FOLDER_PATH or "root")
    remote_files = list_files_recursive(token, site_id, drive_id, folder_id=start_folder)
    logger.info("Found %d PDF/XML files on SharePoint", len(remote_files))

    downloaded = 0
    skipped = 0

    for item in remote_files:
        item_id = item["id"]

        if sharepoint_db.is_processed(item_id):
            skipped += 1
            continue

        local_path = download_file(token, drive_id, item, DOWNLOAD_FOLDER)
        if local_path:
            sharepoint_db.register_download(
                drive_item_id=item_id,
                file_name=item["name"],
                remote_path=_remote_path(item),
                local_path=local_path,
                file_size=item.get("size"),
                last_modified_remote=item.get("lastModifiedDateTime"),
            )
            downloaded += 1

    stats = sharepoint_db.get_stats()
    logger.info(
        "Sync finished  -  downloaded: %d | skipped (already processed): %d | "
        "DB totals -> total: %d, downloaded: %d, processed: %d",
        downloaded, skipped,
        stats["total"], stats["downloaded"], stats["processed"],
    )
    return True
