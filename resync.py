Resync · PY
"""
Canva -> Wix daily re-sync script.
 
STATUS: starter / test version. Only wired up for ONE design so far
(see DESIGN_MAP below) so we can confirm the Wix side actually replaces
the file the button already points to, before rolling out to all 42.
 
Required GitHub secrets:
  CANVA_CLIENT_ID
  CANVA_API_KEY        <- this is your Canva Client SECRET
  WIX_API_KEY
  WIX_SITE_ID
"""
 
import os
import time
import requests
 
CANVA_CLIENT_ID = os.environ["CANVA_CLIENT_ID"]
CANVA_CLIENT_SECRET = os.environ["CANVA_API_KEY"]
WIX_API_KEY = os.environ["WIX_API_KEY"]
WIX_SITE_ID = os.environ["WIX_SITE_ID"]
 
# --- CONFIG: map Canva design IDs to the Wix file they should update ---
# Fill in with real IDs before running. Start with just ONE wine to test.
# Canva design ID: found in the design's URL, e.g. canva.com/design/<THIS PART>/edit
# Wix file ID: found in Wix Media Manager file details / API response.
DESIGN_MAP = {
    # "canva_design_id": "wix_file_id",
    "DAHUn5cTig0": "9854a6fa70a94d42b47d425a25353dbf",
}
 
 
def get_canva_access_token():
    resp = requests.post(
        "https://api.canva.com/rest/v1/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CANVA_CLIENT_ID,
            "client_secret": CANVA_CLIENT_SECRET,
            "scope": "design:content:read design:meta:read",
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]
 
 
def export_design_as_pdf(token, design_id):
    # Start export job
    resp = requests.post(
        "https://api.canva.com/rest/v1/exports",
        headers={"Authorization": f"Bearer {token}"},
        json={"design_id": design_id, "format": {"type": "pdf"}},
    )
    resp.raise_for_status()
    job_id = resp.json()["job"]["id"]
 
    # Poll until export is done
    for _ in range(30):
        time.sleep(2)
        status_resp = requests.get(
            f"https://api.canva.com/rest/v1/exports/{job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        status_resp.raise_for_status()
        job = status_resp.json()["job"]
        if job["status"] == "success":
            return job["urls"][0]  # download URL for the exported PDF
        if job["status"] == "failed":
            raise RuntimeError(f"Canva export failed for design {design_id}: {job}")
    raise TimeoutError(f"Canva export timed out for design {design_id}")
 
 
def download_file(url):
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.content
 
 
def update_wix_file(wix_file_id, file_bytes):
    """
    NOTE: This is the untested part. Wix's Media Manager API does not have
    a clearly documented 'replace content of existing file' endpoint as of
    this writing. This function currently re-uploads as a NEW file and
    prints the new file ID so you can manually confirm whether Wix lets us
    point the button at it, or whether we need a different approach
    (e.g. re-linking the button each time via a different Wix API/App).
    """
    # Step 1: generate upload URL
    upload_resp = requests.post(
        "https://www.wixapis.com/site-media/v1/files/generate-upload-url",
        headers={
            "Authorization": WIX_API_KEY,
            "wix-site-id": WIX_SITE_ID,
        },
        json={"mimeType": "application/pdf", "fileName": "resync-test.pdf"},
    )
    upload_resp.raise_for_status()
    upload_url = upload_resp.json()["uploadUrl"]
 
    # Step 2: upload the actual bytes
    put_resp = requests.put(upload_url, data=file_bytes)
    put_resp.raise_for_status()
    new_file_info = put_resp.json()
 
    print("Uploaded new file to Wix:", new_file_info)
    print("!! Compare this new file ID to the original Wix file ID linked "
          "to your button. If they differ, the button will need to be "
          "re-linked -- this is the open question we need to resolve.")
    return new_file_info
 
 
def main():
    token = get_canva_access_token()
    for design_id, wix_file_id in DESIGN_MAP.items():
        if design_id.startswith("PLACEHOLDER"):
            print("Skipping placeholder entry -- fill in DESIGN_MAP first.")
            continue
        print(f"Exporting Canva design {design_id}...")
        pdf_url = export_design_as_pdf(token, design_id)
        pdf_bytes = download_file(pdf_url)
        print(f"Pushing update to Wix file {wix_file_id}...")
        update_wix_file(wix_file_id, pdf_bytes)
 
 
if __name__ == "__main__":
    main()
