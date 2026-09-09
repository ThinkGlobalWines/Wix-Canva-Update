"""
Daily Canva -> Dropbox re-sync script. Runs inside GitHub Actions.

What it does, each run:
  1. Exchanges the stored Canva refresh token for a new access token
     (Canva issues a NEW refresh token every time -- this script saves
     that new one back into GitHub's secrets automatically, so the
     next run has the right one).
  2. Exchanges the stored Dropbox refresh token for a new access token
     (Dropbox's refresh token never changes, so nothing to save back).
  3. For each wine in DESIGN_MAP: exports the current Canva design as a
     PDF, then uploads it to the SAME Dropbox path with overwrite mode
     -- so the Dropbox shared link your Wix button points to never
     changes, only its content does.

Required GitHub secrets:
  CANVA_CLIENT_ID
  CANVA_CLIENT_SECRET
  CANVA_REFRESH_TOKEN      <- auto-updated by this script after each run
  DROPBOX_APP_KEY
  DROPBOX_APP_SECRET
  DROPBOX_REFRESH_TOKEN
  GH_PAT                   <- personal access token, used ONLY to let
                               this script update CANVA_REFRESH_TOKEN
"""

import base64
import os
import time

import requests
from nacl import encoding, public

CANVA_CLIENT_ID = os.environ["CANVA_CLIENT_ID"]
CANVA_CLIENT_SECRET = os.environ["CANVA_CLIENT_SECRET"]
CANVA_REFRESH_TOKEN = os.environ["CANVA_REFRESH_TOKEN"]

DROPBOX_APP_KEY = os.environ["DROPBOX_APP_KEY"]
DROPBOX_APP_SECRET = os.environ["DROPBOX_APP_SECRET"]
DROPBOX_REFRESH_TOKEN = os.environ["DROPBOX_REFRESH_TOKEN"]

GH_PAT = os.environ["GH_PAT"]
GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]  # e.g. "ThinkGlobalWines/wine-sync"

# --- CONFIG: map each Canva design ID to a FIXED Dropbox path ---
# The Dropbox path must stay identical between runs -- that's what keeps
# the Dropbox shared link (and therefore the Wix button) stable.
DESIGN_MAP = {
    "DAHUn5cTig0": "/Wine Sheets/Priorat Natur.pdf",
}


def refresh_canva_token():
    credentials = base64.b64encode(
        f"{CANVA_CLIENT_ID}:{CANVA_CLIENT_SECRET}".encode()
    ).decode()
    resp = requests.post(
        "https://api.canva.com/rest/v1/oauth/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": CANVA_REFRESH_TOKEN,
        },
    )
    resp.raise_for_status()
    tokens = resp.json()

    # Canva issues a brand new refresh token every time -- save it so the
    # NEXT run doesn't fail.
    update_github_secret("CANVA_REFRESH_TOKEN", tokens["refresh_token"])

    return tokens["access_token"]


def refresh_dropbox_token():
    resp = requests.post(
        "https://api.dropbox.com/oauth2/token",
        auth=(DROPBOX_APP_KEY, DROPBOX_APP_SECRET),
        data={
            "grant_type": "refresh_token",
            "refresh_token": DROPBOX_REFRESH_TOKEN,
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def update_github_secret(secret_name, secret_value):
    owner_repo = GITHUB_REPOSITORY
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json",
    }

    key_resp = requests.get(
        f"https://api.github.com/repos/{owner_repo}/actions/secrets/public-key",
        headers=headers,
    )
    key_resp.raise_for_status()
    key_data = key_resp.json()

    public_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    encrypted_value = base64.b64encode(encrypted).decode("utf-8")

    put_resp = requests.put(
        f"https://api.github.com/repos/{owner_repo}/actions/secrets/{secret_name}",
        headers=headers,
        json={"encrypted_value": encrypted_value, "key_id": key_data["key_id"]},
    )
    put_resp.raise_for_status()
    print(f"Updated GitHub secret: {secret_name}")


def export_design_as_pdf(canva_token, design_id):
    resp = requests.post(
        "https://api.canva.com/rest/v1/exports",
        headers={"Authorization": f"Bearer {canva_token}"},
        json={"design_id": design_id, "format": {"type": "pdf"}},
    )
    resp.raise_for_status()
    job_id = resp.json()["job"]["id"]

    for _ in range(30):
        time.sleep(2)
        status_resp = requests.get(
            f"https://api.canva.com/rest/v1/exports/{job_id}",
            headers={"Authorization": f"Bearer {canva_token}"},
        )
        status_resp.raise_for_status()
        job = status_resp.json()["job"]
        if job["status"] == "success":
            return job["urls"][0]
        if job["status"] == "failed":
            raise RuntimeError(f"Canva export failed for design {design_id}: {job}")
    raise TimeoutError(f"Canva export timed out for design {design_id}")


def download_file(url):
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.content


def upload_to_dropbox(dropbox_token, dropbox_path, file_bytes):
    import json

    dropbox_api_arg = json.dumps({
        "path": dropbox_path,
        "mode": "overwrite",
        "mute": True,
    })
    resp = requests.post(
        "https://content.dropboxapi.com/2/files/upload",
        headers={
            "Authorization": f"Bearer {dropbox_token}",
            "Dropbox-API-Arg": dropbox_api_arg,
            "Content-Type": "application/octet-stream",
        },
        data=file_bytes,
    )
    resp.raise_for_status()
    print(f"Uploaded to Dropbox: {dropbox_path} ({len(file_bytes)} bytes)")
    return resp.json()


def main():
    print("Refreshing Canva access token...")
    canva_token = refresh_canva_token()

    print("Refreshing Dropbox access token...")
    dropbox_token = refresh_dropbox_token()

    for design_id, dropbox_path in DESIGN_MAP.items():
        print(f"\nExporting Canva design {design_id}...")
        pdf_url = export_design_as_pdf(canva_token, design_id)
        pdf_bytes = download_file(pdf_url)
        print(f"Pushing to Dropbox path {dropbox_path}...")
        upload_to_dropbox(dropbox_token, dropbox_path, pdf_bytes)

    print("\nDone.")


if __name__ == "__main__":
    main()
