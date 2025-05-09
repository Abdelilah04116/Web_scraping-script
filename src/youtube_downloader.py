import os
import re
import time
import requests
from loguru import logger
from typing import Dict, List, Optional, Union, Any
from urllib.parse import urlparse, parse_qs
import pytube
import yt_dlp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class YouTubeDownloader:
    """
    Class to handle YouTube video downloading and metadata extraction
    using both pytube and yt-dlp for redundancy and better success rate.
    """
    def __init__(self, config):
        self.config = config
        self.storage_config = config.config.get('storage', {})
        self.media_folder = self.storage_config.get('media_folder', 'downloaded_media')
        self.youtube_folder = os.path.join(self.media_folder, 'youtube')
        self.max_file_size = self.storage_config.get('max_file_size', 500) * 1024 * 1024  # Convert to bytes
        self._setup_folders()

    def _setup_folders(self):
        """Create necessary folders for storing YouTube videos and thumbnails"""
        os.makedirs(self.youtube_folder, exist_ok=True)
        os.makedirs(os.path.join(self.youtube_folder, 'videos'), exist_ok=True)
        os.makedirs(os.path.join(self.youtube_folder, 'thumbnails'), exist_ok=True)
        os.makedirs(os.path.join(self.youtube_folder, 'audio'), exist_ok=True)

    def extract_video_id(self, url: str) -> Optional[str]:
        """
        Extract YouTube video ID from various YouTube URL formats

        Args:
            url: YouTube URL

        Returns:
            str: YouTube video ID or None if not found
        """
        # Handle different YouTube URL formats
        if 'youtu.be' in url:
            # Short URL format: https://youtu.be/VIDEO_ID
            return url.split('/')[-1].split('?')[0]
        elif 'youtube.com/watch' in url:
            # Standard format: https://www.youtube.com/watch?v=VIDEO_ID
            parsed_url = urlparse(url)
            return parse_qs(parsed_url.query).get('v', [None])[0]
        elif 'youtube.com/embed/' in url:
            # Embed format: https://www.youtube.com/embed/VIDEO_ID
            return url.split('/embed/')[-1].split('?')[0]
        elif 'youtube.com/shorts/' in url:
            # Shorts format: https://www.youtube.com/shorts/VIDEO_ID
            return url.split('/shorts/')[-1].split('?')[0]
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=30),
        retry=retry_if_exception_type((pytube.exceptions.PytubeError, Exception))
    )
    def get_video_info_pytube(self, url: str) -> Dict[str, Any]:
        """
        Get video information using pytube

        Args:
            url: YouTube URL

        Returns:
            dict: Video information
        """
        try:
            video_id = self.extract_video_id(url)
            if not video_id:
                logger.warning(f"Could not extract video ID from {url}")
                return {}

            yt = pytube.YouTube(url)

            # Get video details
            info = {
                'id': video_id,
                'title': yt.title,
                'description': yt.description,
                'author': yt.author,
                'channel_id': yt.channel_id,
                'channel_url': yt.channel_url,
                'length': yt.length,
                'views': yt.views,
                'publish_date': str(yt.publish_date) if yt.publish_date else None,
                'thumbnail_url': yt.thumbnail_url,
                'keywords': yt.keywords,
                'url': url,
                'streams': {
                    'video': [],
                    'audio': []
                }
            }

            # Get available streams
            for stream in yt.streams.filter(progressive=True).order_by('resolution').desc():
                info['streams']['video'].append({
                    'itag': stream.itag,
                    'mime_type': stream.mime_type,
                    'resolution': stream.resolution,
                    'fps': stream.fps,
                    'size': stream.filesize
                })

            for stream in yt.streams.filter(only_audio=True).order_by('abr').desc():
                info['streams']['audio'].append({
                    'itag': stream.itag,
                    'mime_type': stream.mime_type,
                    'abr': stream.abr,
                    'size': stream.filesize
                })

            return info

        except Exception as e:
            logger.error(f"Error getting video info with pytube: {str(e)}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=30)
    )
    def get_video_info_ytdlp(self, url: str) -> Dict[str, Any]:
        """
        Get video information using yt-dlp

        Args:
            url: YouTube URL

        Returns:
            dict: Video information
        """
        try:
            video_id = self.extract_video_id(url)
            if not video_id:
                logger.warning(f"Could not extract video ID from {url}")
                return {}

            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'format': 'best',
                'ignoreerrors': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                if not info:
                    logger.warning(f"Could not extract info from {url}")
                    return {}

                # Format the information
                formatted_info = {
                    'id': video_id,
                    'title': info.get('title'),
                    'description': info.get('description'),
                    'author': info.get('uploader'),
                    'channel_id': info.get('channel_id'),
                    'channel_url': info.get('channel_url'),
                    'length': info.get('duration'),
                    'views': info.get('view_count'),
                    'publish_date': info.get('upload_date'),
                    'thumbnail_url': info.get('thumbnail'),
                    'url': url,
                    'formats': []
                }

                # Get available formats
                if 'formats' in info:
                    for fmt in info['formats']:
                        formatted_info['formats'].append({
                            'format_id': fmt.get('format_id'),
                            'ext': fmt.get('ext'),
                            'resolution': fmt.get('resolution'),
                            'fps': fmt.get('fps'),
                            'filesize': fmt.get('filesize'),
                            'vcodec': fmt.get('vcodec'),
                            'acodec': fmt.get('acodec')
                        })

                return formatted_info

        except Exception as e:
            logger.error(f"Error getting video info with yt-dlp: {str(e)}")
            return {}

    def download_video(self, url: str, resolution: str = '720p') -> Dict[str, Any]:
        """
        Download a YouTube video

        Args:
            url: YouTube URL
            resolution: Desired resolution (default: 720p)

        Returns:
            dict: Download information
        """
        try:
            video_id = self.extract_video_id(url)
            if not video_id:
                logger.warning(f"Could not extract video ID from {url}")
                return {'success': False, 'error': 'Invalid YouTube URL'}

            # Try with pytube first
            try:
                yt = pytube.YouTube(url)

                # Get the stream with the desired resolution
                stream = yt.streams.filter(progressive=True, resolution=resolution).first()

                # If no stream with the desired resolution, get the highest resolution
                if not stream:
                    stream = yt.streams.filter(progressive=True).order_by('resolution').desc().first()

                if not stream:
                    logger.warning(f"No suitable stream found for {url}")
                    return {'success': False, 'error': 'No suitable stream found'}

                # Download the video
                filename = f"{video_id}_{int(time.time())}.{stream.subtype}"
                filepath = os.path.join(self.youtube_folder, 'videos', filename)

                stream.download(output_path=os.path.join(self.youtube_folder, 'videos'), filename=filename)

                return {
                    'success': True,
                    'id': video_id,
                    'title': yt.title,
                    'resolution': stream.resolution,
                    'file_path': filepath,
                    'file_size': stream.filesize,
                    'mime_type': stream.mime_type
                }

            except Exception as e:
                logger.warning(f"Error downloading with pytube: {str(e)}, trying yt-dlp")

                # Vérifier si on doit extraire l'audio
                extract_audio = self.config.config.get('youtube', {}).get('extract_audio', False)
                audio_only = self.config.config.get('youtube', {}).get('download_audio_only', False)
                audio_format = self.config.config.get('youtube', {}).get('audio_format', 'mp3')
                audio_quality = self.config.config.get('youtube', {}).get('audio_quality', '192k')

                # Déterminer le format à télécharger
                if audio_only:
                    format_spec = 'bestaudio/best'
                    output_folder = 'audio'
                else:
                    format_spec = f'bestvideo[height<={resolution[:-1]}]+bestaudio/best[height<={resolution[:-1]}]'
                    output_folder = 'videos'

                # Ajouter le post-processeur pour extraire l'audio si nécessaire
                postprocessors = []
                if extract_audio or audio_only:
                    postprocessors.append({
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': audio_format,
                        'preferredquality': audio_quality,
                    })
                    # Ajouter un post-processeur pour convertir les métadonnées
                    postprocessors.append({'key': 'FFmpegMetadata'})
                    # Ajouter un post-processeur pour convertir les miniatures en couverture
                    postprocessors.append({'key': 'EmbedThumbnail'})

                # Try with yt-dlp as fallback
                ydl_opts = {
                    'format': format_spec,
                    'outtmpl': os.path.join(self.youtube_folder, output_folder, f'{video_id}_%(title)s.%(ext)s'),
                    'quiet': False,  # Afficher les logs pour le débogage
                    'no_warnings': False,
                    'ignoreerrors': True,
                    'noplaylist': True,
                    'skip_download': False,
                    'writethumbnail': True,
                    'writesubtitles': True,
                    'writeautomaticsub': True,
                    'subtitleslangs': ['en', 'fr'],
                    'merge_output_format': 'mp4',
                    'postprocessors': postprocessors,
                    # Options pour améliorer la compatibilité
                    'extractor_args': {
                        'youtube': {
                            'skip': ['dash', 'hls'] if not audio_only else [],
                            'player_client': ['android', 'web'],
                        }
                    }
                }

                # Si c'est un Short YouTube, utiliser des options spécifiques
                if '/shorts/' in url:
                    # Options spécifiques pour les Shorts YouTube
                    ydl_opts = {
                        'format': 'best[ext=mp4]/best' if not audio_only else 'bestaudio/best',
                        'outtmpl': os.path.join(self.youtube_folder, 'videos' if not audio_only else 'audio', f'{video_id}_%(title)s.%(ext)s'),
                        'quiet': False,  # Afficher les logs pour le débogage
                        'no_warnings': False,
                        'ignoreerrors': True,
                        'noplaylist': True,
                        'skip_download': False,
                        'writethumbnail': True,
                        'writesubtitles': False,
                        'merge_output_format': 'mp4',
                        'postprocessors': postprocessors,
                        # Utiliser l'extracteur de shorts spécifique
                        'extractor_args': {
                            'youtube': {
                                'player_client': ['android', 'web'],
                                'skip': [],
                            }
                        }
                    }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)

                    if not info:
                        logger.error(f"Failed to download {url} with yt-dlp")
                        return {'success': False, 'error': 'Download failed with both pytube and yt-dlp'}

                    # Get the downloaded file path
                    filepath = ydl.prepare_filename(info)

                    return {
                        'success': True,
                        'id': video_id,
                        'title': info.get('title'),
                        'file_path': filepath,
                        'file_size': os.path.getsize(filepath) if os.path.exists(filepath) else None,
                        'format': info.get('format')
                    }

        except Exception as e:
            logger.error(f"Error downloading video {url}: {str(e)}")
            return {'success': False, 'error': str(e)}

    def download_audio(self, url: str, audio_format: str = 'mp3', audio_quality: str = '192k') -> Dict[str, Any]:
        """
        Download audio from a YouTube video

        Args:
            url: YouTube URL
            audio_format: Audio format (mp3, m4a, wav)
            audio_quality: Audio quality (128k, 192k, 256k, 320k)

        Returns:
            dict: Download information
        """
        try:
            video_id = self.extract_video_id(url)
            if not video_id:
                logger.warning(f"Could not extract video ID from {url}")
                return {'success': False, 'error': 'Invalid YouTube URL'}

            # Configurer yt-dlp pour télécharger uniquement l'audio
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(self.youtube_folder, 'audio', f'{video_id}_%(title)s.%(ext)s'),
                'quiet': False,
                'no_warnings': False,
                'ignoreerrors': True,
                'noplaylist': True,
                'writethumbnail': True,
                'postprocessors': [
                    {
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': audio_format,
                        'preferredquality': audio_quality,
                    },
                    {'key': 'FFmpegMetadata'},
                    {'key': 'EmbedThumbnail'},
                ],
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if not info:
                    logger.error(f"Failed to download audio from {url}")
                    return {'success': False, 'error': 'Failed to download audio'}

                # Get the downloaded file path
                filepath = ydl.prepare_filename(info)
                # Change extension to match the audio format
                filepath = os.path.splitext(filepath)[0] + f'.{audio_format}'

                if not os.path.exists(filepath):
                    # Try to find the file with the correct extension
                    base_path = os.path.splitext(filepath)[0]
                    for ext in [audio_format, 'mp3', 'm4a', 'wav', 'webm']:
                        test_path = f"{base_path}.{ext}"
                        if os.path.exists(test_path):
                            filepath = test_path
                            break

                return {
                    'success': True,
                    'id': video_id,
                    'title': info.get('title'),
                    'file_path': filepath,
                    'file_size': os.path.getsize(filepath) if os.path.exists(filepath) else None,
                    'format': audio_format,
                    'quality': audio_quality
                }

        except Exception as e:
            logger.error(f"Error downloading audio from {url}: {str(e)}")
            return {'success': False, 'error': str(e)}

    def download_thumbnail(self, url: str) -> Dict[str, Any]:
        """
        Download a YouTube video thumbnail

        Args:
            url: YouTube URL

        Returns:
            dict: Thumbnail information
        """
        try:
            video_id = self.extract_video_id(url)
            if not video_id:
                logger.warning(f"Could not extract video ID from {url}")
                return {'success': False, 'error': 'Invalid YouTube URL'}

            # Get video info to get thumbnail URL
            info = self.get_video_info_pytube(url)
            if not info or 'thumbnail_url' not in info:
                info = self.get_video_info_ytdlp(url)

            if not info or 'thumbnail_url' not in info:
                logger.warning(f"Could not get thumbnail URL for {url}")
                return {'success': False, 'error': 'Could not get thumbnail URL'}

            thumbnail_url = info['thumbnail_url']

            # Download the thumbnail
            response = requests.get(thumbnail_url, stream=True, verify=False)
            if response.status_code != 200:
                logger.warning(f"Failed to download thumbnail: HTTP {response.status_code}")
                return {'success': False, 'error': f'HTTP error {response.status_code}'}

            # Save the thumbnail
            filename = f"{video_id}_thumbnail.jpg"
            filepath = os.path.join(self.youtube_folder, 'thumbnails', filename)

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return {
                'success': True,
                'id': video_id,
                'thumbnail_url': thumbnail_url,
                'file_path': filepath,
                'file_size': os.path.getsize(filepath)
            }

        except Exception as e:
            logger.error(f"Error downloading thumbnail for {url}: {str(e)}")
            return {'success': False, 'error': str(e)}
