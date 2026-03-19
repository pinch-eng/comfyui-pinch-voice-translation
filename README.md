# ComfyUI Pinch Voice Translation

Dub and translate audio/video files using the [Pinch](https://startpinch.com/docs) Dubbing API, directly from ComfyUI.

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

The main node. Provide a public URL to an audio/video file, and the node creates a dubbing job, polls until completion, and downloads the result.

**Inputs:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `media_url` | STRING | | Public URL to an audio or video file |
| `target_language` | Dropdown | `es` | Target language for dubbing |
| `source_language` | Dropdown | `auto` | Source language (auto-detect by default) |
| `api_key` | STRING | | Your Pinch API key |
| `reduce_accent` | BOOLEAN | `False` | Reduce accent in dubbed audio |
| `translation_lag_time` | FLOAT | `0.0` | Translation lag time (0-5 seconds) |
| `original_speech_volume` | FLOAT | `0.0` | Volume of original speech in output (0-1) |
| `poll_interval` | INT | `10` | Seconds between status checks (5-60) |

**Outputs:**
| Name | Type | Description |
|------|------|-------------|
| `output_path` | STRING | Path to the downloaded dubbed file |
| `status` | STRING | Final status message |
| `subtitles_original` | STRING | Original language subtitles in SRT format |
| `subtitles_translated` | STRING | Translated language subtitles in SRT format |

Subtitles are returned as SRT format strings that can be piped to other nodes. They are also automatically saved as `.srt` files alongside the output media file in the output directory (e.g., `pinch_dubbed_<job_id>_original.srt` and `pinch_dubbed_<job_id>_translated.srt`). If the API does not return subtitles (older API versions), empty strings are returned.

### Pinch Voice Translation Status

Utility node to check the status of an existing dubbing job.

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

## Supported Formats

Audio: `.mp3`, `.wav`, `.flac`, `.ogg`, `.aac`, `.m4a`, `.wma`
Video: `.mp4`, `.mkv`, `.avi`, `.mov`, `.webm`

## Supported Languages

`en` (English), `es` (Spanish), `fr` (French), `de` (German), `it` (Italian), `pt` (Portuguese), `ru` (Russian), `ja` (Japanese), `ko` (Korean), `zh` (Chinese)

## Getting an API Key

1. Sign up at [startpinch.com](https://startpinch.com)
2. Go to your dashboard and create an API key
3. Paste it into the `api_key` input on the node

## License

MIT
