# MkDocs MediaCompressor

A MkDocs plugin that automatically compresses images and videos in the built site using a hash-based cache to avoid reprocessing unchanged files.

## Installation

```yaml
# mkdocs.yml
plugins:
  - mediacompressor:
      cache_dir: .mediacompressor_cache
      image_quality: 85
      image_max_width: null
      image_max_height: null
      video_crf: 23
      video_preset: medium
      video_max_width: null
      skip_images: false
      skip_videos: false
      max_workers: 4
```

## Requirements

- **Pillow** (≥9.0) - Required for image compression
- **ffmpeg** - Required for video compression (must be in PATH)

## Configuration Reference

| Option | Default | Description |
|--------|---------|-------------|
| `cache_dir` | `.mediacompressor_cache` | Directory for cached compressed files |
| `image_quality` | `85` | JPEG/WebP quality (1-100) |
| `image_max_width` | `null` | Maximum image width (preserves aspect ratio) |
| `image_max_height` | `null` | Maximum image height (preserves aspect ratio) |
| `video_crf` | `23` | Video quality (0-51, lower = better quality) |
| `video_preset` | `medium` | ffmpeg preset (`ultrafast`, `fast`, `medium`, `slow`, `veryslow`) |
| `video_max_width` | `null` | Maximum video width (preserves aspect ratio) |
| `skip_images` | `false` | Skip image compression entirely |
| `skip_videos` | `false` | Skip video compression entirely |
| `max_workers` | `4` | Number of parallel compression threads |

---

## How It Works

### Processing Flow

```
MkDocs Build Complete
        │
        ▼
┌───────────────────────────────┐
│  on_post_build()              │
│  Scan site_dir for media      │
└───────────────────────────────┘
        │
        ▼
┌───────────────────────────────┐
│  For each media file:         │
│  ┌─────────────────────────┐  │
│  │ Compute SHA256 hash     │  │
│  └─────────────────────────┘  │
│  ┌─────────────────────────┐  │
│  │ Check cache for hash    │──┼──► Cache hit: copy cached file
│  └─────────────────────────┘  │
│           │                   │
│           ▼ Cache miss        │
│  ┌─────────────────────────┐  │
│  │ Compress file           │  │
│  │ Save to cache           │  │
│  │ Replace original        │  │
│  └─────────────────────────┘  │
└───────────────────────────────┘
        │
        ▼
┌───────────────────────────────┐
│  Save cache manifest          │
│  Report compression stats     │
└───────────────────────────────┘
```

### Caching System

The plugin uses a hash-based caching system:

1. **Hash Calculation** - SHA256 hash of each source file
2. **Cache Lookup** - Previously compressed files are reused if hash matches
3. **Config Awareness** - Cache is invalidated when compression settings change
4. **Orphan Cleanup** - Cached files without matching sources are removed

Cache is stored in `cache_dir` (default: `.mediacompressor_cache/`) with:
- `.cache.json` - Cache manifest with file hashes and config snapshot
- `{hash}.{ext}` - Compressed media files

---

## Supported Formats

### Images

| Extension | Compression Method |
|-----------|-------------------|
| `.png` | PNG optimization (compress_level=9) |
| `.jpg`, `.jpeg` | JPEG quality reduction |
| `.gif` | GIF optimization |
| `.webp` | WebP quality reduction |
| `.bmp` | BMP optimization |

**Image Features:**
- EXIF orientation auto-correction
- RGBA to RGB conversion for JPEG output
- Aspect-ratio-preserving resize
- LANCZOS resampling for high quality

### Videos

| Extension | Codec |
|-----------|-------|
| `.mp4` | H.264 (libx264) |
| `.webm` | H.264 (libx264) |
| `.ogg` | H.264 (libx264) |
| `.mov` | H.264 (libx264) |
| `.avi` | H.264 (libx264) |
| `.mkv` | H.264 (libx264) |

**Video Features:**
- CRF-based quality control
- Configurable encoding preset
- AAC audio at 128kbps
- Optional width limiting

---

## Examples

### Basic Usage

```yaml
plugins:
  - mediacompressor
```

Compresses all images at quality 85 and videos at CRF 23.

### High Quality Images

```yaml
plugins:
  - mediacompressor:
      image_quality: 95
      image_max_width: 2560
```

### Aggressive Compression

```yaml
plugins:
  - mediacompressor:
      image_quality: 70
      image_max_width: 1920
      image_max_height: 1080
      video_crf: 28
      video_preset: slow
      video_max_width: 1280
```

### Images Only

```yaml
plugins:
  - mediacompressor:
      skip_videos: true
      image_quality: 80
```

### Fast Builds (More Workers)

```yaml
plugins:
  - mediacompressor:
      max_workers: 8
```

---

## Output

During build, the plugin reports compression statistics:

```
[MediaCompressor] Starting media compression...
[MediaCompressor] photo1.jpg: 2,456,789 → 892,345 bytes (63.7% reduction)
[MediaCompressor] photo2.png: 1,234,567 → 456,789 bytes (63.0% reduction)
[MediaCompressor] video.mp4: 45,678,901 → 12,345,678 bytes (73.0% reduction)
[MediaCompressor] Complete: 3 processed, 12 skipped (cached), 0 errors
```

---

## License

MIT
