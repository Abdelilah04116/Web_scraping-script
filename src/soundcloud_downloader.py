import os
import re
import time
import requests
from loguru import logger
from typing import Dict, List, Optional, Union, Any
from urllib.parse import urlparse, parse_qs
import yt_dlp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class SoundCloudDownloader:
    """
    Classe pour télécharger des pistes audio de SoundCloud
    """

    def __init__(self, config, output_folder="downloaded_media"):
        """
        Initialiser le téléchargeur SoundCloud

        Args:
            config: Configuration
            output_folder: Dossier de sortie
        """
        self.config = config
        self.output_folder = output_folder
        self.soundcloud_folder = os.path.join(output_folder, "soundcloud")

        # Créer les dossiers nécessaires
        os.makedirs(os.path.join(self.soundcloud_folder, "tracks"), exist_ok=True)
        os.makedirs(os.path.join(self.soundcloud_folder, "artwork"), exist_ok=True)

        logger.info("SoundCloudDownloader initialized successfully")

    def extract_track_id(self, url: str) -> Optional[str]:
        """
        Extraire l'ID de la piste à partir de l'URL SoundCloud

        Args:
            url: URL SoundCloud

        Returns:
            str: ID de la piste ou None si non trouvé
        """
        # Essayer d'extraire l'ID à partir de l'URL
        parsed_url = urlparse(url)
        path = parsed_url.path.strip('/')

        # Si c'est une URL de piste directe (ex: soundcloud.com/artist/track-name)
        if '/' in path:
            parts = path.split('/')
            if len(parts) >= 2:
                # Vérifier si c'est une piste (pas un profil ou une page de découverte)
                if parts[0] != 'discover' and parts[1] not in ['tracks', 'albums', 'playlists', 'reposts', 'followers', 'following']:
                    return f"{parts[0]}/{parts[1]}"  # Format: artist/track-name

        # Pour les URL de playlist (ex: soundcloud.com/artist/sets/playlist-name)
        if '/sets/' in path:
            parts = path.split('/')
            if len(parts) >= 3 and parts[1] == 'sets':
                return f"{parts[0]}/sets/{parts[2]}"  # Format: artist/sets/playlist-name

        # Si c'est une URL de profil (ex: soundcloud.com/artist)
        if path and '/' not in path:
            return f"profile/{path}"  # Format: profile/artist

        # Si c'est une URL de découverte ou autre page spéciale
        if path.startswith('discover') or path.startswith('search'):
            return f"page/{path}"  # Format: page/discover

        logger.warning(f"Could not extract track ID from URL: {url}")
        return None

    def get_track_info(self, url: str) -> Dict[str, Any]:
        """
        Obtenir les informations sur une piste SoundCloud

        Args:
            url: URL SoundCloud

        Returns:
            dict: Informations sur la piste
        """
        try:
            # Utiliser yt-dlp pour obtenir les informations
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'extract_flat': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                if not info:
                    logger.warning(f"Could not get track info for {url}")
                    return {}

                return {
                    'id': info.get('id'),
                    'title': info.get('title'),
                    'uploader': info.get('uploader'),
                    'thumbnail': info.get('thumbnail'),
                    'duration': info.get('duration'),
                    'view_count': info.get('view_count'),
                    'like_count': info.get('like_count'),
                    'comment_count': info.get('comment_count'),
                    'genre': info.get('genre'),
                    'description': info.get('description'),
                    'upload_date': info.get('upload_date'),
                }

        except Exception as e:
            logger.error(f"Error getting track info for {url}: {str(e)}")
            return {}

    def download_track(self, url: str, audio_format: str = 'mp3', audio_quality: str = '192k') -> Dict[str, Any]:
        """
        Télécharger une piste audio de SoundCloud

        Args:
            url: URL SoundCloud
            audio_format: Format audio (mp3, m4a, wav)
            audio_quality: Qualité audio (128k, 192k, 256k, 320k)

        Returns:
            dict: Informations sur le téléchargement
        """
        try:
            track_id = self.extract_track_id(url)
            if not track_id:
                logger.warning(f"Could not extract track ID from {url}")
                return {'success': False, 'error': 'Invalid SoundCloud URL'}

            # Vérifier si c'est une URL de profil ou de page spéciale
            if track_id.startswith('profile/') or track_id.startswith('page/'):
                logger.info(f"Skipping download for profile/page URL: {url}")
                return {'success': False, 'error': 'Not a track URL', 'type': track_id.split('/')[0]}

            # Configurer yt-dlp pour télécharger la piste audio
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(self.soundcloud_folder, 'tracks', f'{track_id.replace("/", "_")}_%(title)s.%(ext)s'),
                'quiet': False,
                'no_warnings': False,
                'ignoreerrors': True,
                'noplaylist': False if '/sets/' in url else True,  # Télécharger la playlist si c'est une playlist
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
                    logger.error(f"Failed to download track from {url}")
                    return {'success': False, 'error': 'Failed to download track'}

                # Gérer les playlists
                if '_type' in info and info['_type'] == 'playlist':
                    logger.info(f"Downloaded playlist with {len(info.get('entries', []))} tracks")

                    # Retourner les informations sur la première piste de la playlist
                    if info.get('entries') and len(info['entries']) > 0:
                        entry = info['entries'][0]
                        filepath = ydl.prepare_filename(entry)
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
                            'id': track_id,
                            'title': entry.get('title'),
                            'file_path': filepath,
                            'file_size': os.path.getsize(filepath) if os.path.exists(filepath) else None,
                            'format': audio_format,
                            'quality': audio_quality,
                            'is_playlist': True,
                            'playlist_title': info.get('title'),
                            'playlist_count': len(info.get('entries', []))
                        }
                    else:
                        return {'success': False, 'error': 'Empty playlist'}

                # Gérer les pistes individuelles
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
                    'id': track_id,
                    'title': info.get('title'),
                    'file_path': filepath,
                    'file_size': os.path.getsize(filepath) if os.path.exists(filepath) else None,
                    'format': audio_format,
                    'quality': audio_quality,
                    'is_playlist': False
                }

        except Exception as e:
            logger.error(f"Error downloading track from {url}: {str(e)}")
            return {'success': False, 'error': str(e)}

    def download_artwork(self, url: str) -> Dict[str, Any]:
        """
        Télécharger l'artwork d'une piste SoundCloud

        Args:
            url: URL SoundCloud

        Returns:
            dict: Informations sur le téléchargement
        """
        try:
            track_id = self.extract_track_id(url)
            if not track_id:
                logger.warning(f"Could not extract track ID from {url}")
                return {'success': False, 'error': 'Invalid SoundCloud URL'}

            # Vérifier si c'est une URL de profil ou de page spéciale
            if track_id.startswith('profile/') or track_id.startswith('page/'):
                logger.info(f"Skipping artwork download for profile/page URL: {url}")
                return {'success': False, 'error': 'Not a track URL', 'type': track_id.split('/')[0]}

            # Get track info to get artwork URL
            info = self.get_track_info(url)
            if not info or 'thumbnail' not in info:
                logger.warning(f"Could not get artwork URL for {url}")
                return {'success': False, 'error': 'Could not get artwork URL'}

            artwork_url = info['thumbnail']

            # Download the artwork
            response = requests.get(artwork_url, stream=True, verify=False)
            if response.status_code != 200:
                logger.warning(f"Failed to download artwork: HTTP {response.status_code}")
                return {'success': False, 'error': f'HTTP error {response.status_code}'}

            # Save the artwork
            filename = f"{track_id.replace('/', '_')}_artwork.jpg"
            filepath = os.path.join(self.soundcloud_folder, 'artwork', filename)

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return {
                'success': True,
                'id': track_id,
                'artwork_url': artwork_url,
                'file_path': filepath,
                'file_size': os.path.getsize(filepath)
            }

        except Exception as e:
            logger.error(f"Error downloading artwork for {url}: {str(e)}")
            return {'success': False, 'error': str(e)}
