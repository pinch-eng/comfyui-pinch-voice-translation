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


class PinchVoiceTranslation:
    """Dub/translate a media file via the Pinch API given a public URL."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "media_url": ("STRING", {"default": "", "multiline": False}),
                "target_language": (TARGET_LANGUAGE_OPTIONS, {"default": "es"}),
                "source_language": (LANGUAGE_OPTIONS, {"default": "auto"}),
                "api_key": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                "reduce_accent": ("BOOLEAN", {"default": False}),
                "translation_lag_time": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 5.0, "step": 0.1}),
                "original_speech_volume": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "poll_interval": ("INT", {"default": 10, "min": 5, "max": 60}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("output_path", "status", "subtitles_original", "subtitles_translated")
    FUNCTION = "translate"
    CATEGORY = "Pinch/Voice Translation"

    def translate(
        self,
        media_url: str,
        target_language: str,
        source_language: str,
        api_key: str,
        reduce_accent: bool = False,
        translation_lag_time: float = 0.0,
        original_speech_volume: float = 0.0,
        poll_interval: int = 10,
    ):
        media_url = media_url.strip()
        api_key = api_key.strip()

        if not media_url:
            raise ValueError("media_url is required")
        if not media_url.startswith(("http://", "https://")):
            raise ValueError(
                f"media_url must be a public HTTP(S) URL, got: {media_url[:80]}"
            )
        if not api_key:
            raise ValueError("api_key is required")

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
        print(f"[Pinch] Job created: {job_id}")

        # --- Step 2: Poll until complete ---
        start = time.time()
        consecutive_errors = 0
        status_data = {}

        while True:
            elapsed = time.time() - start
            if elapsed > JOB_TIMEOUT_SECONDS:
                return ("", f"Timed out after {JOB_TIMEOUT_SECONDS // 60} minutes. Job ID: {job_id}", "", "")

            time.sleep(poll_interval)

            try:
                resp = requests.get(
                    f"{API_BASE_URL}/api/dubbing/jobs/{job_id}",
                    headers=headers,
                    timeout=30,
                )
                _raise_for_status(resp, "Poll job status")
                status_data = resp.json()
                consecutive_errors = 0
            except (requests.RequestException, Exception) as e:
                consecutive_errors += 1
                print(f"[Pinch] Poll error ({consecutive_errors}/{POLL_RETRY_LIMIT}): {e}")
                if consecutive_errors >= POLL_RETRY_LIMIT:
                    raise Exception(
                        f"[Pinch] Lost connection to API after {POLL_RETRY_LIMIT} retries. "
                        f"Job ID: {job_id} — check status manually."
                    )
                continue

            status = status_data.get("status", "unknown")
            progress = status_data.get("progress", {})
            stage_name = progress.get("stage_name", "")
            percent = progress.get("percent", "")
            progress_str = f" ({stage_name} {percent}%)" if stage_name else ""
            print(f"[Pinch] Job {job_id}: {status}{progress_str} ({int(elapsed)}s elapsed)")

            if status == "completed":
                break
            elif status in ("failed", "error", "cancelled"):
                msg = status_data.get("error", status)
                return ("", f"Job {status}: {msg}", "", "")

        # --- Step 3: Download dubbed output ---
        print("[Pinch] Fetching download URL...")
        resp = requests.get(
            f"{API_BASE_URL}/api/dubbing/jobs/{job_id}/result",
            headers=headers,
            timeout=30,
        )
        _raise_for_status(resp, "Fetch download URL")

        result_data = resp.json()
        output_url = (
            result_data.get("download_url")
            or result_data.get("output_url")
            or status_data.get("output_url")
        )
        if not output_url:
            return ("", f"Job completed but no output URL returned. Job ID: {job_id}", "", "")

        ext = _safe_extension(media_url)
        out_name = f"pinch_dubbed_{job_id}{ext}"
        out_path = os.path.join(_get_output_dir(), out_name)

        print(f"[Pinch] Downloading result to {out_path}...")
        dl_resp = requests.get(output_url, stream=True, timeout=600)
        dl_resp.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in dl_resp.iter_content(chunk_size=8192):
                f.write(chunk)

        size_mb = os.path.getsize(out_path) / (1024 * 1024)

        # --- Step 4: Download subtitles if available ---
        output_dir = _get_output_dir()
        srt_base = f"pinch_dubbed_{job_id}"
        subtitles_original = ""
        subtitles_translated = ""

        subs_orig_url = status_data.get("subtitles_original_url") or result_data.get("subtitles_original_url")
        subs_trans_url = status_data.get("subtitles_translated_url") or result_data.get("subtitles_translated_url")

        if subs_orig_url:
            try:
                print("[Pinch] Downloading original subtitles...")
                subtitles_original = requests.get(subs_orig_url, timeout=30).text
                srt_path = os.path.join(output_dir, f"{srt_base}_original.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(subtitles_original)
                print(f"[Pinch] Saved original subtitles to {srt_path}")
            except requests.RequestException as e:
                print(f"[Pinch] Warning: failed to download original subtitles: {e}")

        if subs_trans_url:
            try:
                print("[Pinch] Downloading translated subtitles...")
                subtitles_translated = requests.get(subs_trans_url, timeout=30).text
                srt_path = os.path.join(output_dir, f"{srt_base}_translated.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(subtitles_translated)
                print(f"[Pinch] Saved translated subtitles to {srt_path}")
            except requests.RequestException as e:
                print(f"[Pinch] Warning: failed to download translated subtitles: {e}")

        msg = f"Completed. Downloaded {size_mb:.1f} MB to {out_path}"
        print(f"[Pinch] {msg}")
        return (out_path, msg, subtitles_original, subtitles_translated)


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
