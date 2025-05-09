import os
import re
import time
import hashlib
import mimetypes
import requests
import base64
from urllib.parse import urljoin, urlparse
from loguru import logger
from typing import Dict, List, Optional, Any
from PIL import Image
import io
from tenacity import retry, stop_after_attempt, wait_exponential

class MediaDownloader:
    """
    Enhanced class to handle downloading of various media types from web pages.
    Supports images, videos, and other media files with improved error handling.
    """
    def __init__(self, config):
        self.config = config
        self.storage_config = config.config.get('storage', {})
        self.media_folder = self.storage_config.get('media_folder', 'downloaded_media')
        self.media_types = self.storage_config.get('media_types', {})
        self.max_file_size = self.storage_config.get('max_file_size', 100) * 1024 * 1024  # Convert to bytes
        self._setup_folders()

        # Initialize session with SSL verification disabled
        self.session = requests.Session()
        self.session.verify = False

        # Disable SSL warnings
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _setup_folders(self):
        """Create necessary folders for storing media files"""
        # Create main media folder
        os.makedirs(self.media_folder, exist_ok=True)

        # Create subfolders for different media types
        os.makedirs(os.path.join(self.media_folder, 'images'), exist_ok=True)
        os.makedirs(os.path.join(self.media_folder, 'videos'), exist_ok=True)
        os.makedirs(os.path.join(self.media_folder, 'audio'), exist_ok=True)
        os.makedirs(os.path.join(self.media_folder, 'documents'), exist_ok=True)
        os.makedirs(os.path.join(self.media_folder, 'other'), exist_ok=True)

    def _get_extension(self, url: str, content_type: Optional[str] = None) -> Optional[str]:
        """
        Get file extension from URL or content-type

        Args:
            url: URL of the media file
            content_type: Content-Type header from HTTP response

        Returns:
            str: File extension or None if not determined
        """
        # Try to get extension from URL first
        ext = os.path.splitext(urlparse(url).path)[1].lower()
        if ext and self._is_valid_extension(ext):
            return ext

        # Try to get extension from content-type
        if content_type:
            ext = mimetypes.guess_extension(content_type)
            if ext and self._is_valid_extension(ext):
                return ext

        # Try to determine extension from URL patterns
        if 'youtube' in url and '/vi/' in url:
            return '.jpg'  # YouTube thumbnail

        # Default extensions based on content type
        if content_type:
            if content_type.startswith('image/'):
                return '.jpg'
            elif content_type.startswith('video/'):
                return '.mp4'
            elif content_type.startswith('audio/'):
                return '.mp3'

        return None

    def _is_valid_extension(self, ext: str) -> bool:
        """
        Check if file extension is in allowed media types

        Args:
            ext: File extension

        Returns:
            bool: True if extension is valid
        """
        if not ext.startswith('.'):
            ext = '.' + ext

        # Check if extension is in any of the media types
        for media_type, extensions in self.media_types.items():
            if ext in extensions:
                return True

        return False

    def _get_media_type(self, ext: str) -> str:
        """
        Determine media type from file extension

        Args:
            ext: File extension

        Returns:
            str: Media type (images, videos, audio, documents, other)
        """
        if not ext.startswith('.'):
            ext = '.' + ext

        for media_type, extensions in self.media_types.items():
            if ext in extensions:
                return media_type

        # Default to 'other' if not found
        return 'other'

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def download_media(self, url: str, page_url: str) -> Optional[Dict[str, Any]]:
        """
        Download media file from URL

        Args:
            url: URL of the media file
            page_url: URL of the page containing the media

        Returns:
            dict: Information about the downloaded file or None if download failed
        """
        if not self.storage_config.get('download_media', True):
            return None

        try:
            # Resolve relative URL
            absolute_url = urljoin(page_url, url)

            # Skip data URLs
            if absolute_url.startswith('data:'):
                return self._handle_data_url(absolute_url, page_url)

            # Make request with SSL verification disabled
            response = self.session.get(absolute_url, stream=True, verify=False, timeout=30)

            if response.status_code != 200:
                logger.warning(f"Failed to download {absolute_url}: HTTP {response.status_code}")
                return None

            # Check content length
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > self.max_file_size:
                logger.warning(f"File too large: {absolute_url} ({content_length} bytes)")
                return None

            # Get file extension and media type
            content_type = response.headers.get('content-type', '')
            ext = self._get_extension(url, content_type)
            if not ext:
                logger.warning(f"Could not determine file extension for {absolute_url}")
                return None

            # Determine media type and subfolder
            media_type = self._get_media_type(ext)
            if not media_type:
                media_type = 'other'

            # Download content in chunks
            content = b''
            for chunk in response.iter_content(chunk_size=8192):
                content += chunk
                if len(content) > self.max_file_size:
                    logger.warning(f"File too large during download: {absolute_url}")
                    return None

            # Generate unique filename
            file_hash = hashlib.md5(content).hexdigest()[:10]
            filename = f"{file_hash}{ext}"
            filepath = os.path.join(self.media_folder, media_type, filename)

            # Save file
            with open(filepath, 'wb') as f:
                f.write(content)

            # Get file metadata
            file_size = len(content)

            # For images, get dimensions
            dimensions = None
            if media_type == 'images':
                try:
                    with Image.open(io.BytesIO(content)) as img:
                        dimensions = img.size
                except Exception as e:
                    logger.warning(f"Could not get image dimensions: {str(e)}")

            return {
                'original_url': url,
                'absolute_url': absolute_url,
                'local_path': filepath,
                'media_type': media_type,
                'size': file_size,
                'filename': filename,
                'content_type': content_type,
                'dimensions': dimensions
            }

        except Exception as e:
            logger.error(f"Error downloading media from {url}: {str(e)}")
            raise  # Re-raise for retry

    def _handle_data_url(self, data_url: str, page_url: str) -> Optional[Dict[str, Any]]:
        """
        Handle data URLs (e.g., data:image/png;base64,...)

        Args:
            data_url: Data URL
            page_url: URL of the page containing the data URL

        Returns:
            dict: Information about the extracted file or None if extraction failed
        """
        try:
            # Parse data URL
            if not data_url.startswith('data:'):
                return None

            # Extract MIME type and data
            mime_type = data_url.split(',')[0].split(':')[1].split(';')[0]
            is_base64 = ';base64,' in data_url
            data = data_url.split(',', 1)[1]

            # Decode data
            if is_base64:
                content = base64.b64decode(data)
            else:
                # URL-encoded data
                from urllib.parse import unquote
                content = unquote(data).encode('utf-8')

            # Get file extension
            ext = mimetypes.guess_extension(mime_type)
            if not ext:
                if 'image/png' in mime_type:
                    ext = '.png'
                elif 'image/jpeg' in mime_type:
                    ext = '.jpg'
                elif 'image/gif' in mime_type:
                    ext = '.gif'
                elif 'image/svg+xml' in mime_type:
                    ext = '.svg'
                else:
                    ext = '.bin'

            # Determine media type
            if mime_type.startswith('image/'):
                media_type = 'images'
            elif mime_type.startswith('video/'):
                media_type = 'videos'
            elif mime_type.startswith('audio/'):
                media_type = 'audio'
            else:
                media_type = 'other'

            # Generate unique filename
            file_hash = hashlib.md5(content).hexdigest()[:10]
            filename = f"{file_hash}{ext}"
            filepath = os.path.join(self.media_folder, media_type, filename)

            # Save file
            with open(filepath, 'wb') as f:
                f.write(content)

            # Get file metadata
            file_size = len(content)

            # For images, get dimensions
            dimensions = None
            if media_type == 'images':
                try:
                    with Image.open(io.BytesIO(content)) as img:
                        dimensions = img.size
                except Exception as e:
                    logger.warning(f"Could not get image dimensions: {str(e)}")

            return {
                'original_url': data_url[:50] + '...',  # Truncate for readability
                'local_path': filepath,
                'media_type': media_type,
                'size': file_size,
                'filename': filename,
                'content_type': mime_type,
                'dimensions': dimensions,
                'is_data_url': True
            }

        except Exception as e:
            logger.error(f"Error processing data URL: {str(e)}")
            return None

    def find_and_download_media(self, html_content: str, page_url: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Find and download all media from HTML content

        Args:
            html_content: HTML content
            page_url: URL of the page

        Returns:
            dict: Dictionary of downloaded media files by type
        """
        media_files = {
            'images': [],
            'videos': [],
            'audio': [],
            'documents': [],
            'other': []
        }

        # Find all image tags
        img_tags = re.findall(r'<img[^>]+src=["\'](.*?)["\']', html_content)

        # Find all video tags
        video_tags = re.findall(r'<video[^>]*>.*?<source[^>]+src=["\'](.*?)["\']', html_content, re.DOTALL)
        video_tags += re.findall(r'<video[^>]+src=["\'](.*?)["\']', html_content)

        # Find all audio tags
        audio_tags = re.findall(r'<audio[^>]*>.*?<source[^>]+src=["\'](.*?)["\']', html_content, re.DOTALL)
        audio_tags += re.findall(r'<audio[^>]+src=["\'](.*?)["\']', html_content)

        # Find all iframe tags (for embedded content like YouTube)
        iframe_tags = re.findall(r'<iframe[^>]+src=["\'](.*?)["\']', html_content)

        # Find all link tags with media types
        media_links = re.findall(r'<a[^>]+href=["\'](.*?\.(?:jpg|jpeg|png|gif|mp4|webm|mp3|pdf))["\']', html_content, re.IGNORECASE)

        # Download images
        for img_url in img_tags:
            result = self.download_media(img_url, page_url)
            if result and result.get('media_type') == 'images':
                media_files['images'].append(result)

        # Download videos
        for video_url in video_tags:
            result = self.download_media(video_url, page_url)
            if result and result.get('media_type') == 'videos':
                media_files['videos'].append(result)

        # Download audio
        for audio_url in audio_tags:
            result = self.download_media(audio_url, page_url)
            if result and result.get('media_type') == 'audio':
                media_files['audio'].append(result)

        # Process iframes (potential YouTube embeds)
        for iframe_url in iframe_tags:
            if 'youtube.com/embed/' in iframe_url or 'youtube.com/watch' in iframe_url or 'youtu.be/' in iframe_url:
                # Store YouTube iframe URL for later processing
                media_files['videos'].append({
                    'original_url': iframe_url,
                    'absolute_url': urljoin(page_url, iframe_url),
                    'media_type': 'videos',
                    'is_youtube_embed': True
                })

        # Download media from links
        for link_url in media_links:
            result = self.download_media(link_url, page_url)
            if result:
                media_type = result.get('media_type', 'other')
                media_files[media_type].append(result)

        return media_files
