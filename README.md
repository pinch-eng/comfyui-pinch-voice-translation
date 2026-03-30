# ComfyUI Pinch Voice Translation

Dub audio/video files using the [Pinch](https://startpinch.com/docs) Dubbing API, directly from ComfyUI.

https://registry.comfy.org/publishers/pinch/nodes/pinch-dubbing

## Installation

### ComfyUI Manager
Search for "Pinch Voice Translation" in the ComfyUI Manager and install.

### Manual
Clone this repository into your `ComfyUI/custom_nodes/` directory:

```bash
cd ComfyUI/custom_nodes/
git clone https://github.com/pinch-eng/comfyui-pinch-voice-translation.git
pip install -r comfyui-pinch-voice-translation/requirements.txt
```

Restart ComfyUI.

## Nodes

### Pinch Voice Translation (Dubbing)

The main node. Provide either a public URL or a local file path to an audio/video file. The node uploads (if local), creates a dubbing job, polls until completion, and downloads the result to your ComfyUI output directory.

**Inputs:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `target_language` | Dropdown | Yes | `es` | Language to dub into |
| `source_language` | Dropdown | Yes | `auto` | Source language (auto-detect by default) |
| `api_key` | STRING | Yes | | Your Pinch API key |
| `media_url` | STRING | No | | Public HTTP(S) URL to an audio or video file |
| `local_file_path` | STRING | No | | Absolute path to a local audio or video file (max 500 MB) |
| `reduce_accent` | BOOLEAN | No | `False` | Reduce accent in dubbed audio |
| `translation_lag_time` | FLOAT | No | `0.0` | Delay before dubbed speech starts, in seconds (0–5) |
| `original_speech_volume` | FLOAT | No | `0.0` | Volume of original speech mixed under the dub (0–1) |
| `poll_interval` | INT | No | `10` | Seconds between status checks (5–60) |

Provide either `media_url` or `local_file_path` — not both.

**Outputs:**

| Name | Type | Description |
|------|------|-------------|
| `job_id` | STRING | Pinch dubbing job ID |
| `output_path` | STRING | Local path to the downloaded dubbed file |
| `status` | STRING | Final status message |
| `subtitles_original` | STRING | Original language subtitles (SRT format) |
| `subtitles_translated` | STRING | Translated language subtitles (SRT format) |

Subtitles are returned as SRT strings and also saved as `.srt` files alongside the dubbed media in your output directory (e.g. `pinch_dubbed_<job_id>_original.srt` and `pinch_dubbed_<job_id>_translated.srt`). Empty strings are returned if the API does not provide subtitles.

Jobs time out after 30 minutes. If a job times out, the `job_id` is still returned so you can check its status manually with the Status node.

---

### Pinch Voice Translation Status

Utility node to check the status of an existing dubbing job by ID.

**Inputs:**

| Name | Type | Description |
|------|------|-------------|
| `api_key` | STRING | Your Pinch API key |
| `job_id` | STRING | The job ID to check |

**Outputs:**

| Name | Type | Description |
|------|------|-------------|
| `status` | STRING | Current job status |
| `output_url` | STRING | Download URL (if completed) |
| `subtitles_original_url` | STRING | URL to original language subtitles (SRT) |
| `subtitles_translated_url` | STRING | URL to translated language subtitles (SRT) |

---

## Supported Formats

**Audio:** `.mp3`, `.wav`, `.flac`, `.ogg`, `.aac`, `.m4a`, `.wma`

**Video:** `.mp4`, `.mov`, `.mkv`, `.webm`, `.avi`, `.flv`, `.ts`

## Supported Languages

**Source:** `auto` (detect), `en`, `es`, `fr`, `de`, `it`, `pt`, `ru`, `ja`, `ko`, `zh`

**Target:** `en`, `es`, `fr`, `de`, `it`, `pt`, `ru`, `ja`, `ko`, `zh`

## Getting an API Key

1. Sign up at [startpinch.com](https://startpinch.com)
2. Go to your dashboard and create an API key
3. Paste it into the `api_key` input on the node

## License

MIT
