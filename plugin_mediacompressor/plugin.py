import os
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from mkdocs.plugins import BasePlugin
from mkdocs.config import config_options
from PIL import Image, ExifTags

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.ogg', '.mov', '.avi', '.mkv'}

class MediaCompressorPlugin(BasePlugin):
    """
    MkDocs plugin to compress images and videos in the built site.
    Uses a hash-based cache to avoid reprocessing unchanged files.
    """
    
    config_scheme = (
        ('cache_dir', config_options.Type(str, default='.mediacompressor_cache')),
        ('image_quality', config_options.Type(int, default=85)),
        ('image_max_width', config_options.Type(int, default=None)),
        ('image_max_height', config_options.Type(int, default=None)),
        ('video_crf', config_options.Type(int, default=23)),
        ('video_preset', config_options.Type(str, default='medium')),
        ('video_max_width', config_options.Type(int, default=None)),
        ('skip_images', config_options.Type(bool, default=False)),
        ('skip_videos', config_options.Type(bool, default=False)),
        ('max_workers', config_options.Type(int, default=4)),
    )

    def on_config(self, config):
        """Initialize cache and validate configuration."""
        self.docs_dir = Path(config['docs_dir']).parent
        self.cache_dir = self.docs_dir / self.config['cache_dir']
        self.cache_file = self.cache_dir / '.cache.json'
        self.cache_lock = Lock()
        
        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Load or initialize cache
        self._load_cache()
        
        return config

    def on_post_build(self, config):
        """
        Compress images and videos in the site directory after build completes.
        """
        site_dir = Path(config['site_dir'])
        
        print("[MediaCompressor] Starting media compression...")
        
        # Find all media files in site directory
        media_files = []
        for ext in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            media_files.extend(site_dir.rglob(f'*{ext}'))
        
        if not media_files:
            print("[MediaCompressor] No media files found.")
            return
        
        # Clean cache of orphaned files
        self._clean_orphaned_cache()
        
        # Process files in parallel
        processed = 0
        skipped = 0
        errors = 0
        
        max_workers = self.config.get('max_workers', 4)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_file = {
                executor.submit(self._process_media_file, media_file, site_dir): media_file 
                for media_file in media_files
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_file):
                media_file = future_to_file[future]
                try:
                    result = future.result()
                    if result:
                        processed += 1
                    else:
                        skipped += 1
                except Exception as e:
                    print(f"[MediaCompressor] Error processing {media_file}: {e}")
                    errors += 1
        
        # Save cache after all processing is complete
        self._save_cache()
        
        print(f"[MediaCompressor] Complete: {processed} processed, {skipped} skipped (cached), {errors} errors")

    def _load_cache(self):
        """Load cache from disk."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    cache_data = json.load(f)
                    
                # Cache format: { "config": {...}, "files": {...} }
                if isinstance(cache_data, dict) and "config" in cache_data:
                    # Check if config changed
                    current_config = self._get_current_config()
                    if cache_data["config"] != current_config:
                        print("[MediaCompressor] Configuration changed, clearing cache...")
                        print("[MediaCompressor] Config differences:")
                        for key in current_config:
                            old_val = cache_data["config"].get(key)
                            new_val = current_config.get(key)
                            if old_val != new_val:
                                print(f"  {key}: {old_val} → {new_val}")
                        self.cache = {}
                        return
                    
                    self.cache = cache_data.get("files", {})
                else:
                    # Old cache format without config, clear it
                    print("[MediaCompressor] Old cache format detected, clearing...")
                    self.cache = {}
            except Exception as e:
                print(f"[MediaCompressor] Error loading cache: {e}")
                self.cache = {}
        else:
            self.cache = {}

    def _save_cache(self):
        """Save cache to disk with config snapshot."""
        try:
            cache_data = {
                "config": self._get_current_config(),
                "files": self.cache
            }
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            print(f"[MediaCompressor] Error saving cache: {e}")

    def _get_current_config(self):
        """Get current configuration values from mkdocs.yml."""
        return {
            'image_quality': self.config.get('image_quality'),
            'image_max_width': self.config.get('image_max_width'),
            'image_max_height': self.config.get('image_max_height'),
            'video_crf': self.config.get('video_crf'),
            'video_preset': self.config.get('video_preset'),
            'video_max_width': self.config.get('video_max_width'),
            'skip_images': self.config.get('skip_images'),
            'skip_videos': self.config.get('skip_videos'),
        }

    def _save_config(self):
        """Save current configuration to disk."""
        config_data = self._get_current_config()
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config_data, f, indent=2)
        except Exception as e:
            print(f"[MediaCompressor] Error saving config: {e}")

    def _save_cached_config(self):
        """Save a snapshot of the config in the cache directory."""
        try:
            current_config = self._get_current_config()
            with open(self.cached_config_file, 'w') as f:
                json.dump(current_config, f, indent=2)
        except Exception as e:
            print(f"[MediaCompressor] Error saving cached config: {e}")

    def _load_or_create_config(self):
        """Load existing config file or create with defaults from mkdocs.yml."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    file_config = json.load(f)
                
                # Get current config from mkdocs.yml
                current_config = self._get_current_config()
                
                # Check if any parameters are missing and add defaults
                updated = False
                for key, value in current_config.items():
                    if key not in file_config:
                        file_config[key] = value
                        updated = True
                        print(f"[MediaCompressor] Added missing config parameter: {key} = {value}")
                
                # Save if we added any defaults
                if updated:
                    with open(self.config_file, 'w') as f:
                        json.dump(file_config, f, indent=2)
                    print("[MediaCompressor] Updated config file with missing parameters")
                
            except Exception as e:
                print(f"[MediaCompressor] Error loading config, creating new: {e}")
                self._save_config()
        else:
            # Create new config file with current settings
            self._save_config()
            print("[MediaCompressor] Created new config file")
    
    def _get_current_config(self):
        """Get current configuration values from mkdocs.yml."""
        return {
            'image_quality': self.config.get('image_quality'),
            'image_max_width': self.config.get('image_max_width'),
            'image_max_height': self.config.get('image_max_height'),
            'video_crf': self.config.get('video_crf'),
            'video_preset': self.config.get('video_preset'),
            'video_max_width': self.config.get('video_max_width'),
            'skip_images': self.config.get('skip_images'),
            'skip_videos': self.config.get('skip_videos'),
        }
    
    def _save_cached_config(self):
        """Save a snapshot of the config in the cache directory."""
        try:
            current_config = self._get_current_config()
            with open(self.cached_config_file, 'w') as f:
                json.dump(current_config, f, indent=2)
        except Exception as e:
            print(f"[MediaCompressor] Error saving cached config: {e}")
        """Save current configuration to disk."""
        config_data = {
            'image_quality': self.config['image_quality'],
            'image_max_width': self.config['image_max_width'],
            'image_max_height': self.config['image_max_height'],
            'video_crf': self.config['video_crf'],
            'video_preset': self.config['video_preset'],
            'video_max_width': self.config['video_max_width'],
            'skip_images': self.config['skip_images'],
            'skip_videos': self.config['skip_videos'],
        }
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config_data, f, indent=2)
        except Exception as e:
            print(f"[MediaCompressor] Error saving config: {e}")

    def _config_changed(self):
        """Check if configuration has changed by comparing with cached snapshot."""
        current_config = self._get_current_config()
        
        # Check the cached config in the cache directory (primary source of truth)
        if self.cached_config_file.exists():
            try:
                with open(self.cached_config_file, 'r') as f:
                    cached_config = json.load(f)
                
                if cached_config != current_config:
                    print("[MediaCompressor] Config differences detected:")
                    for key in current_config:
                        old_val = cached_config.get(key)
                        new_val = current_config.get(key)
                        if old_val != new_val:
                            print(f"  {key}: {old_val} → {new_val}")
                    return True
                return False
                
            except Exception as e:
                print(f"[MediaCompressor] Error reading cached config: {e}")
                return True
        
        # No cached config exists - this is a first run
        print("[MediaCompressor] No cached config found, first run")
        return True

    def _clear_cache(self):
        """Clear all cached files and cache data."""
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache = {}

    def _clean_orphaned_cache(self):
        """Remove cached files that no longer have originals."""
        orphaned = []
        for file_hash in list(self.cache.keys()):
            cache_entry = self.cache[file_hash]
            cached_file = self.cache_dir / cache_entry['cached_filename']
            
            # If cached file doesn't exist, remove from cache
            if not cached_file.exists():
                orphaned.append(file_hash)
        
        for file_hash in orphaned:
            del self.cache[file_hash]
        
        if orphaned:
            print(f"[MediaCompressor] Cleaned {len(orphaned)} orphaned cache entries")

    def _compute_file_hash(self, file_path):
        """Compute SHA256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _process_media_file(self, media_file, site_dir):
        """
        Process a media file: compress and replace with cached version.
        Returns True if processed, False if skipped (cached).
        """
        ext = media_file.suffix.lower()
        
        # Skip based on config
        if ext in IMAGE_EXTENSIONS and self.config['skip_images']:
            return False
        if ext in VIDEO_EXTENSIONS and self.config['skip_videos']:
            return False
        
        # Compute hash of original file
        file_hash = self._compute_file_hash(media_file)
        
        # Check if already cached and up-to-date (thread-safe read)
        with self.cache_lock:
            if file_hash in self.cache:
                cache_entry = self.cache[file_hash]
                cached_file = self.cache_dir / cache_entry['cached_filename']
                
                if cached_file.exists():
                    # Use cached version
                    shutil.copy2(cached_file, media_file)
                    return False
        
        # Not cached - need to compress
        if ext in IMAGE_EXTENSIONS:
            compressed_file = self._compress_image(media_file, file_hash)
        elif ext in VIDEO_EXTENSIONS:
            compressed_file = self._compress_video(media_file, file_hash)
        else:
            return False
        
        if compressed_file and compressed_file.exists():
            # Update cache (thread-safe write)
            with self.cache_lock:
                self.cache[file_hash] = {
                    'cached_filename': compressed_file.name,
                    'original_hash': file_hash,
                }
            
            # Replace original with compressed version
            print(f"[MediaCompressor] Replacing {media_file} with compressed version from {compressed_file}")
            shutil.copy2(compressed_file, media_file)
            
            # Verify the file was replaced
            new_size = media_file.stat().st_size
            print(f"[MediaCompressor] Site file now: {new_size:,} bytes")
            return True
        
        print(f"[MediaCompressor] Failed to create compressed file for {media_file.name}")
        return False

    def _fix_image_orientation(self, img):
        """Fix image orientation based on EXIF data."""
        try:
            # Get EXIF data
            exif = img.getexif()
            if exif is None:
                return img
            
            # Find orientation tag
            orientation = None
            for tag, value in exif.items():
                if tag in ExifTags.TAGS and ExifTags.TAGS[tag] == 'Orientation':
                    orientation = value
                    break
            
            # Apply rotation based on orientation
            if orientation == 3:
                img = img.rotate(180, expand=True)
            elif orientation == 6:
                img = img.rotate(270, expand=True)
            elif orientation == 8:
                img = img.rotate(90, expand=True)
            
            # Remove EXIF orientation tag to prevent double rotation
            if orientation is not None and hasattr(img, 'getexif'):
                exif_dict = img.getexif()
                if exif_dict:
                    for tag in ExifTags.TAGS.keys():
                        if ExifTags.TAGS[tag] == 'Orientation':
                            if tag in exif_dict:
                                del exif_dict[tag]
                            break
            
        except Exception:
            # If EXIF processing fails, just return the image as-is
            pass
        
        return img

    def _compress_image(self, image_path, file_hash):
        """Compress an image using Pillow with proper orientation handling."""
        try:
            img = Image.open(image_path)
            
            # Fix orientation based on EXIF data
            img = self._fix_image_orientation(img)
            
            # Convert RGBA to RGB if saving as JPEG
            if img.mode in ('RGBA', 'LA', 'P') and image_path.suffix.lower() in {'.jpg', '.jpeg'}:
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = rgb_img
            
            # Resize if needed (preserves aspect ratio)
            max_width = self.config.get('image_max_width')
            max_height = self.config.get('image_max_height')
            
            if max_width is not None or max_height is not None:
                width, height = img.size
                scale = 1.0
                
                if max_width is not None and width > max_width:
                    scale = min(scale, max_width / width)
                if max_height is not None and height > max_height:
                    scale = min(scale, max_height / height)
                
                if scale < 1.0:
                    new_size = (int(width * scale), int(height * scale))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                    print(f"[MediaCompressor] Resized {image_path.name}: {width}x{height} → {new_size[0]}x{new_size[1]}")
            
            # Save compressed image
            cached_filename = f"{file_hash}{image_path.suffix}"
            cached_path = self.cache_dir / cached_filename
            
            save_kwargs = {'optimize': True}
            if image_path.suffix.lower() in {'.jpg', '.jpeg'}:
                save_kwargs['quality'] = self.config['image_quality']
            elif image_path.suffix.lower() == '.png':
                save_kwargs['compress_level'] = 9
            elif image_path.suffix.lower() == '.webp':
                save_kwargs['quality'] = self.config['image_quality']
            
            img.save(cached_path, **save_kwargs)
            
            # Show compression stats
            original_size = image_path.stat().st_size
            compressed_size = cached_path.stat().st_size
            savings = (1 - compressed_size / original_size) * 100
            print(f"[MediaCompressor] {image_path.name}: {original_size:,} → {compressed_size:,} bytes ({savings:.1f}% reduction)")
            
            return cached_path
            
        except Exception as e:
            print(f"[MediaCompressor] Error compressing image {image_path}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _compress_video(self, video_path, file_hash):
        """Compress a video using ffmpeg."""
        # Check if ffmpeg is available
        if not shutil.which('ffmpeg'):
            print("[MediaCompressor] ffmpeg not found, skipping video compression")
            return None
        
        try:
            cached_filename = f"{file_hash}{video_path.suffix}"
            cached_path = self.cache_dir / cached_filename
            
            # Build ffmpeg command
            cmd = ['ffmpeg', '-i', str(video_path), '-y']
            
            # Video codec settings
            cmd.extend(['-c:v', 'libx264'])
            cmd.extend(['-crf', str(self.config['video_crf'])])
            cmd.extend(['-preset', self.config['video_preset']])
            
            # Resize if needed
            if self.config['video_max_width']:
                cmd.extend(['-vf', f"scale='min({self.config['video_max_width']},iw)':-2"])
            
            # Audio codec
            cmd.extend(['-c:a', 'aac', '-b:a', '128k'])
            
            # Output
            cmd.append(str(cached_path))
            
            # Run ffmpeg
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if result.returncode == 0 and cached_path.exists():
                # Show compression stats
                original_size = video_path.stat().st_size
                compressed_size = cached_path.stat().st_size
                savings = (1 - compressed_size / original_size) * 100
                print(f"[MediaCompressor] {video_path.name}: {original_size:,} → {compressed_size:,} bytes ({savings:.1f}% reduction)")
                
                return cached_path
            else:
                print(f"[MediaCompressor] ffmpeg error: {result.stderr}")
                return None
                
        except Exception as e:
            print(f"[MediaCompressor] Error compressing video {video_path}: {e}")
            return None