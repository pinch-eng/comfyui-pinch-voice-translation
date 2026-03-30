"""ComfyUI custom nodes for Pinch Voice Translation (dubbing)."""

import os
import time
import json

import requests


API_BASE_URL = "https://api.startpinch.com"

LANGUAGE_OPTIONS = ["auto", "en", "es", "fr", "de", "it", "pt", "ru", "ja", "ko", "zh"]
TARGET_LANGUAGE_OPTIONS = ["en", "es", "fr", "de", "it", "pt", "ru", "ja", "ko", "zh"]

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".ts",
                        ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma"}

JOB_TIMEOUT_SECONDS = 30 * 60  # 30 minutes
POLL_RETRY_LIMIT = 3  # consecutive network failures before giving up


def _get_output_dir() -> str:
    """Return ComfyUI's output directory, falling back to cwd/output."""
    try:
        import folder_paths
        return folder_paths.get_output_directory()
    except ImportError:
        out = os.path.join(os.getcwd(), "output")
        os.makedirs(out, exist_ok=True)
        return out


def _api_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _parse_api_error(resp: requests.Response) -> str:
    """Extract a human-readable error from a Pinch API error response."""
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error", {})
            if isinstance(err, dict):
                return f"{err.get('code', 'error')}: {err.get('message', resp.text)}"
            if isinstance(err, str):
                return err
            return body.get("message", resp.text)
    except (json.JSONDecodeError, ValueError):
        pass
    return resp.text[:500]


def _raise_for_status(resp: requests.Response, context: str = "API request"):
    """Like resp.raise_for_status() but with a clear, parsed error message."""
    if resp.ok:
        return
    detail = _parse_api_error(resp)
    raise Exception(f"[Pinch] {context} failed ({resp.status_code}): {detail}")


def _safe_extension(media_url: str) -> str:
    """Extract a safe file extension from a URL, defaulting to .mp4."""
    url_path = media_url.split("?")[0].split("#")[0]
    ext = os.path.splitext(url_path)[1].lower()
    if ext in SUPPORTED_EXTENSIONS:
        return ext
    return ".mp4"


_CONTENT_TYPE_MAP = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".flv": "video/x-flv",
    ".ts": "video/mp2t",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".wma": "audio/x-ms-wma",
}

MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


def _infer_content_type(file_path: str) -> str:
    """Return the MIME type for a local file based on its extension."""
    ext = os.path.splitext(file_path)[1].lower()
    return _CONTENT_TYPE_MAP.get(ext, "application/octet-stream")


def _upload_local_file(api_key: str, file_path: str) -> str:
    """Upload a local media file to Pinch S3 and return the source_url for dubbing.

    Steps:
      1. Validate the file exists and is within the 500 MB limit.
      2. POST /api/dubbing/upload-url to get a presigned PUT URL + source_url.
      3. PUT the raw file bytes to S3 (no auth header — URL is pre-signed).
      4. Return source_url to use as the dubbing job's source.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"[Pinch] Local file not found: {file_path}")

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        raise ValueError(f"[Pinch] Local file is empty (0 bytes): {file_path}")
    if file_size > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"[Pinch] File exceeds 500 MB limit "
            f"({file_size / (1024 * 1024):.1f} MB): {file_path}"
        )

    filename = os.path.basename(file_path)
    content_type = _infer_content_type(file_path)
    size_mb = file_size / (1024 * 1024)
    print(f"[Pinch] Uploading local file: {file_path} ({size_mb:.2f} MB, {content_type})")

    # Step 1: Get presigned upload URL from Pinch
    url_resp = requests.post(
        f"{API_BASE_URL}/api/dubbing/upload-url",
        headers=_api_headers(api_key),
        json={"filename": filename, "content_type": content_type},
        timeout=30,
    )
    _raise_for_status(url_resp, "Get upload URL")
    url_data = url_resp.json()

    upload_url = url_data.get("upload_url")
    source_url = url_data.get("source_url")
    if not upload_url or not source_url:
        raise Exception(f"[Pinch] Unexpected response from upload-url endpoint: {url_data}")

    expires_in = url_data.get("expires_in_sec", 3600)
    print(f"[Pinch] Got upload URL (expires in {expires_in}s). Uploading to S3...")

    # Step 2: PUT file bytes directly to S3 (pre-signed URL — no Authorization header)
    with open(file_path, "rb") as f:
        put_resp = requests.put(
            upload_url,
            data=f,
            headers={"Content-Type": content_type},
            timeout=600,
        )
    if not put_resp.ok:
        raise Exception(
            f"[Pinch] S3 upload failed ({put_resp.status_code}): {put_resp.text[:500]}"
        )

    print(f"[Pinch] Upload complete. source_url={source_url}")
    return source_url


class PinchVoiceTranslation:
    """Dub/translate a media file via the Pinch API given a public URL."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "target_language": (TARGET_LANGUAGE_OPTIONS, {"default": "es"}),
                "source_language": (LANGUAGE_OPTIONS, {"default": "auto"}),
                "api_key": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                "media_url": ("STRING", {"default": "", "multiline": False}),
                "local_file_path": ("STRING", {"default": "", "multiline": False}),
                "reduce_accent": ("BOOLEAN", {"default": False}),
                "translation_lag_time": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 5.0, "step": 0.1}),
                "original_speech_volume": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "poll_interval": ("INT", {"default": 10, "min": 5, "max": 60}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("job_id", "output_path", "status", "subtitles_original", "subtitles_translated")
    OUTPUT_NODE = True
    FUNCTION = "translate"
    CATEGORY = "Pinch/Voice Translation"

    def translate(
        self,
        target_language: str,
        source_language: str,
        api_key: str,
        media_url: str = "",
        local_file_path: str = "",
        reduce_accent: bool = False,
        translation_lag_time: float = 0.0,
        original_speech_volume: float = 0.0,
        poll_interval: int = 10,
    ):
        media_url = media_url.strip()
        local_file_path = local_file_path.strip()
        api_key = api_key.strip()

        if not api_key:
            raise ValueError("api_key is required")

        if media_url and local_file_path:
            raise ValueError(
                "Provide either media_url or local_file_path, not both."
            )
        if not media_url and not local_file_path:
            raise ValueError(
                "Either media_url (public URL) or local_file_path must be provided."
            )

        # --- Local file mode: upload to Pinch S3, resolve to a source_url ---
        if local_file_path:
            media_url = _upload_local_file(api_key, local_file_path)
        else:
            if not media_url.startswith(("http://", "https://")):
                raise ValueError(
                    f"media_url must be a public HTTP(S) URL, got: {media_url[:80]}"
                )

        headers = _api_headers(api_key)

        # --- Step 1: Create dubbing job ---
        job_body = {
            "source_url": media_url,
            "source_lang": source_language,
            "target_lang": target_language,
            "reduce_accent": reduce_accent,
            "translation_lag_time": translation_lag_time,
            "original_speech_volume": original_speech_volume,
        }
        print(f"[Pinch] Creating dubbing job ({source_language} -> {target_language})...")
        print(f"[Pinch] Source URL: {media_url}")
        print(f"[Pinch] Job params: reduce_accent={reduce_accent}, "
              f"translation_lag_time={translation_lag_time}, "
              f"original_speech_volume={original_speech_volume}")

        resp = requests.post(
            f"{API_BASE_URL}/api/dubbing/jobs",
            headers=headers,
            json=job_body,
            timeout=30,
        )
        _raise_for_status(resp, "Create dubbing job")

        job = resp.json()
        if "job_id" not in job:
            raise Exception(f"[Pinch] API returned unexpected response (no job_id): {job}")

        job_id = job["job_id"]
        print(f"[Pinch] Job created successfully. job_id={job_id}")

        # --- Step 2: Poll until completed and result URL is confirmed ready ---
        # Mirrors the n8n loop:
        #   completed  -> call /result; if URL present break, else keep waiting
        #   failed/cancelled -> stop with error
        #   otherwise  -> wait poll_interval and retry
        start = time.time()
        consecutive_errors = 0
        status_data = {}
        result_data = {}
        output_url = None

        while True:
            elapsed = time.time() - start
            if elapsed > JOB_TIMEOUT_SECONDS:
                print(f"[Pinch] Timeout reached after {int(elapsed)}s. job_id={job_id}")
                return (job_id, "", f"Timed out after {JOB_TIMEOUT_SECONDS // 60} minutes. Job ID: {job_id}", "", "")

            print(f"[Pinch] Waiting {poll_interval}s before next poll... ({int(elapsed)}s elapsed)")
            time.sleep(poll_interval)

            # Poll job status
            try:
                resp = requests.get(
                    f"{API_BASE_URL}/api/dubbing/jobs/{job_id}",
                    headers=headers,
                    timeout=30,
                )
                consecutive_errors = 0
            except requests.RequestException as e:
                consecutive_errors += 1
                print(f"[Pinch] Poll network error ({consecutive_errors}/{POLL_RETRY_LIMIT}): {e}")
                if consecutive_errors >= POLL_RETRY_LIMIT:
                    raise Exception(
                        f"[Pinch] Lost connection to API after {POLL_RETRY_LIMIT} retries. "
                        f"Job ID: {job_id} — check status manually."
                    )
                continue

            # Raise immediately on HTTP errors (401, 404, 5xx, etc.) — do NOT retry these
            _raise_for_status(resp, "Poll job status")
            status_data = resp.json()

            status = status_data.get("status", "unknown")
            progress = status_data.get("progress", {})
            stage_name = progress.get("stage_name", "")
            percent = progress.get("percent", "")
            progress_str = f" ({stage_name} {percent}%)" if stage_name else ""
            print(f"[Pinch] Poll result — job_id={job_id} status={status}{progress_str} ({int(elapsed)}s elapsed)")

            # Terminal failure states — stop immediately
            if status in ("failed", "error", "cancelled"):
                err_detail = status_data.get("error", status)
                print(f"[Pinch] Job terminated. job_id={job_id} status={status} detail={err_detail}")
                return (job_id, "", f"Job {status}: {err_detail}", "", "")

            # Completed — but do NOT assume result is instantly available.
            # Call /result and only proceed if the download URL is actually present.
            if status == "completed":
                print(f"[Pinch] Job marked completed. Calling /result to confirm download URL... job_id={job_id}")
                try:
                    result_resp = requests.get(
                        f"{API_BASE_URL}/api/dubbing/jobs/{job_id}/result",
                        headers=headers,
                        timeout=30,
                    )
                    _raise_for_status(result_resp, "Fetch result")
                    result_data = result_resp.json()
                    print(f"[Pinch] /result response keys: {list(result_data.keys())}")
                    output_url = (
                        result_data.get("download_url")
                        or result_data.get("output_url")
                        or status_data.get("output_url")
                    )
                except Exception as e:
                    print(f"[Pinch] Warning: /result call failed: {e}. Will wait and retry...")
                    output_url = None

                if output_url:
                    print(f"[Pinch] Output URL confirmed: {output_url}")
                    break
                else:
                    print(f"[Pinch] Job completed but output URL not yet available. "
                          f"Waiting {poll_interval}s before retry...")
                    continue

            # Any other status (processing, queued, pending, etc.) — keep waiting
            print(f"[Pinch] Job not yet complete (status={status}). Will poll again in {poll_interval}s...")

        # --- Step 3: Download dubbed output locally ---
        ext = _safe_extension(media_url)
        out_name = f"pinch_dubbed_{job_id}{ext}"
        out_path = os.path.join(_get_output_dir(), out_name)

        print(f"[Pinch] Downloading result from URL to local path: {out_path}")
        try:
            dl_resp = requests.get(output_url, stream=True, timeout=600)
            dl_resp.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in dl_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
        except Exception as e:
            print(f"[Pinch] Download failed: {e}")
            return (job_id, "", f"Download failed for job {job_id}: {e}", "", "")

        # Validate the file was actually written with content
        if not os.path.exists(out_path):
            print(f"[Pinch] ERROR: File not found on disk after download: {out_path}")
            return (job_id, "", f"Download appeared to succeed but file missing on disk: {out_path}", "", "")

        file_size = os.path.getsize(out_path)
        if file_size == 0:
            print(f"[Pinch] ERROR: File on disk is 0 bytes: {out_path}")
            return (job_id, "", f"Download completed but file is empty (0 bytes): {out_path}", "", "")

        size_mb = file_size / (1024 * 1024)
        print(f"[Pinch] File saved successfully: {out_path} ({size_mb:.2f} MB, {file_size} bytes)")

        # --- Step 4: Download subtitles if available ---
        output_dir = _get_output_dir()
        srt_base = f"pinch_dubbed_{job_id}"
        subtitles_original = ""
        subtitles_translated = ""

        subs_orig_url = status_data.get("subtitles_original_url") or result_data.get("subtitles_original_url")
        subs_trans_url = status_data.get("subtitles_translated_url") or result_data.get("subtitles_translated_url")

        print(f"[Pinch] Subtitle URLs — original: {subs_orig_url or 'none'}, translated: {subs_trans_url or 'none'}")

        if subs_orig_url:
            try:
                print("[Pinch] Downloading original subtitles...")
                subtitles_original = requests.get(subs_orig_url, timeout=30).text
                srt_path = os.path.join(output_dir, f"{srt_base}_original.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(subtitles_original)
                print(f"[Pinch] Saved original subtitles to {srt_path} ({len(subtitles_original)} chars)")
            except requests.RequestException as e:
                print(f"[Pinch] Warning: failed to download original subtitles: {e}")

        if subs_trans_url:
            try:
                print("[Pinch] Downloading translated subtitles...")
                subtitles_translated = requests.get(subs_trans_url, timeout=30).text
                srt_path = os.path.join(output_dir, f"{srt_base}_translated.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(subtitles_translated)
                print(f"[Pinch] Saved translated subtitles to {srt_path} ({len(subtitles_translated)} chars)")
            except requests.RequestException as e:
                print(f"[Pinch] Warning: failed to download translated subtitles: {e}")

        msg = f"Completed. Downloaded {size_mb:.1f} MB to {out_path}"
        print(f"[Pinch] SUCCESS — {msg}")
        return (job_id, out_path, msg, subtitles_original, subtitles_translated)


class PinchVoiceTranslationStatus:
    """Check the status of an existing Pinch dubbing job."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": ("STRING", {"default": "", "multiline": False}),
                "job_id": ("STRING", {"default": "", "multiline": False}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("status", "output_url", "subtitles_original_url", "subtitles_translated_url")
    FUNCTION = "check_status"
    CATEGORY = "Pinch/Voice Translation"

    def check_status(
        self,
        api_key: str,
        job_id: str,
    ):
        api_key = api_key.strip()
        job_id = job_id.strip()

        if not api_key:
            raise ValueError("api_key is required")
        if not job_id:
            raise ValueError("job_id is required")

        headers = _api_headers(api_key)

        resp = requests.get(
            f"{API_BASE_URL}/api/dubbing/jobs/{job_id}",
            headers=headers,
            timeout=30,
        )
        _raise_for_status(resp, "Get job status")

        data = resp.json()
        status = data.get("status", "unknown")
        output_url = data.get("output_url", "")
        subs_orig_url = data.get("subtitles_original_url", "")
        subs_trans_url = data.get("subtitles_translated_url", "")

        if status == "completed":
            try:
                result_resp = requests.get(
                    f"{API_BASE_URL}/api/dubbing/jobs/{job_id}/result",
                    headers=headers,
                    timeout=30,
                )
                _raise_for_status(result_resp, "Fetch download URL")
                result_data = result_resp.json()
                output_url = result_data.get("download_url") or result_data.get("output_url", output_url)
                subs_orig_url = result_data.get("subtitles_original_url", subs_orig_url)
                subs_trans_url = result_data.get("subtitles_translated_url", subs_trans_url)
            except Exception:
                pass

        return (status, output_url, subs_orig_url, subs_trans_url)
