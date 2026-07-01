"""
storage.py — Cloud storage backend for SMVS OCR.

Goal: convert thaya pachi original + output files server par RAKHVA NATHI.
Successful cloud upload pachi j local files delete thay. Fail thay to job
'upload_failed' status ma rahe, background retry thread try karto rahe,
max attempts pachi admin dashboard ma alert dekhay (files local j rahe -
data loss na thay tena mate, safety net).

Folder structure (banne provider mate same convention):
    <root>/Users/<username>/<job_id>_<original_stem>/
        - original uploaded file
        - all output files (txt/docx/pdf/zip)

Config (config.yaml):
    storage:
      provider: google_drive       # google_drive | onedrive | none
      google_drive:
        service_account_json: /path/to/service_account.json
        root_folder_id: "..."      # organizational Shared Drive folder ID
      onedrive:
        tenant_id: "..."
        client_id: "..."
        client_secret: "..."
        drive_id: "..."            # organizational SharePoint/OneDrive drive ID
        root_path: "/SMVS-OCR"
      max_retry_attempts: 8
      retry_interval_sec: 180
"""

import io
import logging
import os
import threading
import time

log = logging.getLogger("smvs.storage")


class StorageError(Exception):
    pass


# --------------------------------------------------------------- BASE CLASS

class BaseStorage:
    name = "none"

    def ensure_user_folder(self, username, job_folder_name):
        """Return an opaque folder handle/id where files for this job go."""
        raise NotImplementedError

    def upload_file(self, folder_ref, local_path, remote_name):
        raise NotImplementedError

    def folder_link(self, folder_ref):
        raise NotImplementedError


# --------------------------------------------------------------- GOOGLE DRIVE

class GoogleDriveStorage(BaseStorage):
    name = "google_drive"

    def __init__(self, service_account_json=None, root_folder_id="",
                 client_email=None, private_key=None, project_id=None):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        if service_account_json and os.path.isfile(service_account_json):
            # Legacy: JSON file path
            creds = service_account.Credentials.from_service_account_file(
                service_account_json, scopes=["https://www.googleapis.com/auth/drive"]
            )
        elif client_email and private_key:
            # New: individual fields (admin UI thi direct input)
            info = {
                "type": "service_account",
                "project_id": project_id or "smvs-ocr",
                "private_key": private_key.replace("\\n", "\n"),
                "client_email": client_email,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/drive"]
            )
        else:
            raise StorageError("Google Drive: provide client_email + private_key or service_account_json path")

        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        self.root_folder_id = root_folder_id

    def _find_or_create_folder(self, name, parent_id):
        q = (f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' "
             f"and '{parent_id}' in parents and trashed = false")
        res = self.svc.files().list(q=q, fields="files(id,name)", supportsAllDrives=True,
                                     includeItemsFromAllDrives=True).execute()
        files = res.get("files", [])
        if files:
            return files[0]["id"]
        meta = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
        f = self.svc.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
        return f["id"]

    def ensure_user_folder(self, username, job_folder_name):
        users_root = self._find_or_create_folder("Users", self.root_folder_id)
        user_folder = self._find_or_create_folder(username, users_root)
        job_folder = self._find_or_create_folder(job_folder_name, user_folder)
        return job_folder

    def upload_file(self, folder_ref, local_path, remote_name):
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(local_path, resumable=True)
        meta = {"name": remote_name, "parents": [folder_ref]}
        self.svc.files().create(body=meta, media_body=media, fields="id",
                                 supportsAllDrives=True).execute()

    def folder_link(self, folder_ref):
        return f"https://drive.google.com/drive/folders/{folder_ref}"


# ------------------------------------------------------------------ ONEDRIVE

class OneDriveStorage(BaseStorage):
    name = "onedrive"

    def __init__(self, tenant_id, client_id, client_secret, drive_id, root_path="/SMVS-OCR"):
        import msal
        self.drive_id = drive_id
        self.root_path = root_path.strip("/")
        self._app = msal.ConfidentialClientApplication(
            client_id, authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential=client_secret,
        )
        self._token = None
        self._token_exp = 0

    def _access_token(self):
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        result = self._app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise StorageError(f"OneDrive auth failed: {result.get('error_description')}")
        self._token = result["access_token"]
        self._token_exp = time.time() + result.get("expires_in", 3600)
        return self._token

    def _headers(self):
        return {"Authorization": f"Bearer {self._access_token()}"}

    def ensure_user_folder(self, username, job_folder_name):
        import requests
        path = f"{self.root_path}/Users/{username}/{job_folder_name}"
        url = (f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/"
               f"{path}")
        # PATCH-like idiom: create via path with createUploadSession not needed for folders;
        # use the "special" folder creation by PUT on parent with conflictBehavior.
        r = requests.patch(url, headers=self._headers())
        if r.status_code in (200, 201):
            return path
        # fallback: create stepwise (parent may not exist yet)
        parts = path.split("/")
        cur = ""
        for part in parts:
            cur = f"{cur}/{part}" if cur else part
            create_url = (f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/"
                          f"{cur.rsplit('/',1)[0]}:/children" if "/" in cur else
                          f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root/children")
            body = {"name": cur.rsplit("/", 1)[-1], "folder": {},
                    "@microsoft.graph.conflictBehavior": "replace"}
            requests.post(create_url, headers={**self._headers(), "Content-Type": "application/json"},
                          json=body)
        return path

    def upload_file(self, folder_ref, local_path, remote_name):
        import requests
        url = (f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/"
               f"{folder_ref}/{remote_name}:/content")
        with open(local_path, "rb") as f:
            data = f.read()
        r = requests.put(url, headers=self._headers(), data=data)
        if r.status_code not in (200, 201):
            raise StorageError(f"OneDrive upload failed ({r.status_code}): {r.text[:200]}")

    def folder_link(self, folder_ref):
        # Fetch the actual browser-openable webUrl of the folder so admin can click & download
        import requests
        try:
            url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/{folder_ref}?$select=webUrl"
            r = requests.get(url, headers=self._headers())
            if r.status_code == 200:
                web = r.json().get("webUrl")
                if web:
                    return web
        except Exception:
            pass
        return f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/{folder_ref}"


# ------------------------------------------------------------------ FACTORY

_BACKEND = None
_CFG = {}


def configure(cfg):
    """cfg = full _CFG['storage'] dict from config.yaml. Call once at startup."""
    global _BACKEND, _CFG
    _CFG = cfg or {}
    provider = (_CFG.get("provider") or "none").strip().lower()
    active = _CFG.get("active", True)  # False hoy to deactivated chhe — credentials safe rehse
    try:
        if not active:
            _BACKEND = None  # deactivated — no upload, credentials intact
        elif provider == "google_drive":
            gd = _CFG.get("google_drive", {})
            _BACKEND = GoogleDriveStorage(
                service_account_json=gd.get("service_account_json"),
                root_folder_id=gd.get("root_folder_id", ""),
                client_email=gd.get("client_email"),
                private_key=gd.get("private_key"),
                project_id=gd.get("project_id"),
            )
        elif provider == "onedrive":
            od = _CFG.get("onedrive", {})
            _BACKEND = OneDriveStorage(od["tenant_id"], od["client_id"], od["client_secret"],
                                        od["drive_id"], od.get("root_path", "/SMVS-OCR"))
        else:
            _BACKEND = None
    except Exception as e:
        log.error("Storage backend init failed (%s): %s — uploads will queue as upload_failed.",
                   provider, e)
        _BACKEND = None
    return _BACKEND


def is_enabled():
    return _BACKEND is not None


def max_retry_attempts():
    return int(_CFG.get("max_retry_attempts", 8))


def retry_interval_sec():
    return int(_CFG.get("retry_interval_sec", 180))


# --------------------------------------------------------- RUNTIME CONFIG (admin UI)
# Admin page thi save kareli settings yaha persist thay chhe (jobs/_data/storage_config.json),
# config.yaml ne touch karva ni jarur nathi — server restart vagar j apply thai jay chhe.

def _runtime_paths(jobs_root):
    data_dir = os.path.join(jobs_root, "_data")
    os.makedirs(data_dir, exist_ok=True)
    secrets_dir = os.path.join(data_dir, "secrets")
    os.makedirs(secrets_dir, exist_ok=True)
    return os.path.join(data_dir, "storage_config.json"), secrets_dir


def load_runtime_config(jobs_root):
    cfg_path, _ = _runtime_paths(jobs_root)
    if not os.path.isfile(cfg_path):
        return None
    try:
        import json
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_runtime_config(jobs_root, cfg):
    cfg_path, _ = _runtime_paths(jobs_root)
    import json
    tmp = cfg_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, cfg_path)


def save_google_service_account(jobs_root, json_text):
    """Admin UI thi pasted service-account JSON ne secrets folder ma save kare, path return kare."""
    import json as _json
    _json.loads(json_text)  # validate it's real JSON before saving
    _, secrets_dir = _runtime_paths(jobs_root)
    path = os.path.join(secrets_dir, "google_service_account.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json_text)
    return path


def masked_status():
    """Frontend-safe status — secrets kadi pan expose nathi thata, fakt 'set'/'not set'."""
    provider = (_CFG.get("provider") or "none").strip().lower()
    active = _CFG.get("active", True)
    out = {"provider": provider, "connected": is_enabled(),
           "active": active,
           "max_retry_attempts": max_retry_attempts(), "retry_interval_sec": retry_interval_sec()}
    if provider == "google_drive":
        gd = _CFG.get("google_drive", {})
        out["google_drive"] = {
            "root_folder_id": gd.get("root_folder_id", ""),
            "client_email": gd.get("client_email", ""),
            "project_id": gd.get("project_id", ""),
            "private_key_configured": bool(gd.get("private_key")),
        }
    elif provider == "onedrive":
        od = _CFG.get("onedrive", {})
        out["onedrive"] = {
            "tenant_id": od.get("tenant_id", ""),
            "client_id": od.get("client_id", ""),
            "client_secret_configured": bool(od.get("client_secret")),
            "drive_id": od.get("drive_id", ""),
            "root_path": od.get("root_path", "/SMVS-OCR"),
        }
    return out


def test_connection():
    """Admin 'Test Connection' button — ek dummy folder banavi try kare, error hoy to raise."""
    if _BACKEND is None:
        raise StorageError("No provider configured yet.")
    folder_ref = _BACKEND.ensure_user_folder("_connection_test", "ping")
    link = _BACKEND.folder_link(folder_ref)
    return {"ok": True, "provider": _BACKEND.name, "link": link}


def upload_job_files(username, job_id, original_stem, file_paths):
    """Upload all file_paths (original + outputs) into one job folder.
    Returns (provider_name, folder_link). Raises StorageError on failure."""
    if _BACKEND is None:
        raise StorageError("No storage backend configured")
    job_folder_name = f"{job_id}_{original_stem}"
    folder_ref = _BACKEND.ensure_user_folder(username, job_folder_name)
    for p in file_paths:
        if os.path.isfile(p):
            _BACKEND.upload_file(folder_ref, p, os.path.basename(p))
    return _BACKEND.name, _BACKEND.folder_link(folder_ref)


# ------------------------------------------------------------- RETRY WORKER

_retry_thread = None
_retry_stop = threading.Event()


def start_retry_worker(db_module, jobs_root):
    """Background thread: periodically retries jobs stuck in 'upload_failed'."""
    global _retry_thread
    if _retry_thread and _retry_thread.is_alive():
        return

    def _loop():
        while not _retry_stop.is_set():
            try:
                _retry_pass(db_module, jobs_root)
            except Exception as e:
                log.error("Retry worker error: %s", e)
            _retry_stop.wait(retry_interval_sec())

    _retry_thread = threading.Thread(target=_loop, daemon=True)
    _retry_thread.start()


def _retry_pass(db_module, jobs_root):
    if not is_enabled():
        return
    for job in db_module.jobs_failed_uploads():
        attempts = job.get("upload_attempts", 0) or 0
        if attempts >= max_retry_attempts():
            continue  # admin dashboard will surface this as a permanent alert
        job_dir = os.path.join(jobs_root, job["job_id"])
        out_dir = os.path.join(job_dir, "out")
        if not os.path.isdir(out_dir):
            db_module.job_update(job["job_id"], status="error",
                                  error_message="Local files missing, cannot upload")
            continue
        file_paths = [os.path.join(out_dir, f) for f in os.listdir(out_dir)]
        try:
            provider, link = upload_job_files(
                job["username"], job["job_id"],
                os.path.splitext(job["original_filename"] or "file")[0], file_paths)
            db_module.job_update(job["job_id"], status="completed",
                                  cloud_provider=provider, cloud_folder_link=link,
                                  upload_attempts=attempts + 1)
            import shutil
            shutil.rmtree(job_dir, ignore_errors=True)
            log.info("Retry upload succeeded for job %s", job["job_id"])
        except Exception as e:
            db_module.job_update(job["job_id"], upload_attempts=attempts + 1,
                                  error_message=str(e)[:300])
            log.warning("Retry upload failed for job %s: %s", job["job_id"], e)


# ------------------------------------------------- EMAIL RUNTIME CONFIG
def _email_config_path(jobs_root):
    data_dir = os.path.join(jobs_root, "_data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "email_config.json")


def load_email_config(jobs_root):
    p = _email_config_path(jobs_root)
    if not os.path.isfile(p):
        return None
    try:
        import json
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_email_config(jobs_root, cfg):
    import json
    p = _email_config_path(jobs_root)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, p)
