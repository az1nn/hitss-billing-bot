# -*- coding: utf-8 -*-
"""
Test script for SharePoint connection via Microsoft Graph API.
Uses Client ID, Client Secret, Tenant ID, Site ID and Drive ID from environment variables.
Run: python sharepoint_connection_test.py
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import msal
import requests

# Environment variable names
ENV_CLIENT_ID = "SHAREPOINT_CLIENT_ID"
ENV_CLIENT_SECRET = "SHAREPOINT_CLIENT_SECRET"
ENV_TENANT_ID = "SHAREPOINT_TENANT_ID"
ENV_SITE_ID = "SHAREPOINT_SITE_ID"
ENV_DRIVE_ID = "SHAREPOINT_DRIVE_ID"

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPE = ["https://graph.microsoft.com/.default"]


def get_config():
    """Load configuration from environment. Returns dict or None if missing vars."""
    config = {
        "client_id": os.environ.get(ENV_CLIENT_ID),
        "client_secret": os.environ.get(ENV_CLIENT_SECRET),
        "tenant_id": os.environ.get(ENV_TENANT_ID),
        "site_id": os.environ.get(ENV_SITE_ID),
        "drive_id": os.environ.get(ENV_DRIVE_ID),
    }
    missing = [k for k, v in config.items() if not (v and str(v).strip())]
    if missing:
        print(f"Missing environment variables: {missing}")
        print(f"Required: {ENV_CLIENT_ID}, {ENV_CLIENT_SECRET}, {ENV_TENANT_ID}, {ENV_SITE_ID}, {ENV_DRIVE_ID}")
        return None
    return config


def get_token(config):
    """Obtain access token using client credentials flow."""
    authority = f"https://login.microsoftonline.com/{config['tenant_id']}"
    app = msal.ConfidentialClientApplication(
        config["client_id"],
        authority=authority,
        client_credential=config["client_secret"],
    )
    result = app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" not in result:
        error = result.get("error_description") or result.get("error", "Unknown error")
        raise RuntimeError(f"Failed to acquire token: {error}")
    return result["access_token"]


def test_site(access_token, site_id):
    """GET site to verify connection. Returns (success, message or data)."""
    url = f"{GRAPH_BASE}/sites/{site_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        return False, f"Site request failed: {resp.status_code} - {resp.text}"
    data = resp.json()
    name = data.get("displayName") or data.get("name") or "(no name)"
    return True, f"Site: {name}"


def test_drive(access_token, site_id, drive_id):
    """GET drive root (and optionally children) to verify drive access."""
    url = f"{GRAPH_BASE}/sites/{site_id}/drives/{drive_id}/root"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        return False, f"Drive request failed: {resp.status_code} - {resp.text}"
    data = resp.json()
    name = data.get("name") or "(root)"
    return True, f"Drive root: {name}"


def main():
    config = get_config()
    if not config:
        sys.exit(1)

    print("Testing SharePoint connection via Microsoft Graph...")
    try:
        token = get_token(config)
        print("  Token acquired successfully.")
    except Exception as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    ok_site, msg_site = test_site(token, config["site_id"])
    if ok_site:
        print(f"  {msg_site}")
    else:
        print(f"  ERROR: {msg_site}")
        sys.exit(1)

    ok_drive, msg_drive = test_drive(token, config["site_id"], config["drive_id"])
    if ok_drive:
        print(f"  {msg_drive}")
    else:
        print(f"  ERROR: {msg_drive}")
        sys.exit(1)

    print("Connection test completed successfully.")


if __name__ == "__main__":
    main()
