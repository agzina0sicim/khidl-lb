from urllib.parse import unquote
import re
import os
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from typing import List, Optional, Tuple
from tqdm import tqdm
from .soundtrack import Soundtrack

try:
    from mutagen.id3 import APIC, ID3, ID3NoHeaderError
except Exception:  # pragma: no cover - handled at runtime if dependency is unavailable
    APIC = ID3 = ID3NoHeaderError = None

def preDownloadMusic(soundtrack:Soundtrack, format:str):
    urls = []

    for index, track in enumerate(soundtrack.tracks):
        print("\rPreparing download: {}/{}".format(index+1, len(soundtrack.tracks)), end="")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.6998.166 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Site":"same-site"}
        r = requests.get(track, headers=headers)
        parser = BeautifulSoup(r.text, 'html.parser')
        dllink = parser.select_one('.songDownloadLink')

        if not dllink:
            raise DLParseException

        dlanchor = dllink.parent

        if not dlanchor:
            raise DLParseException

        originURL = dlanchor.get('href').__str__()

        if not originURL:
            raise DLParseException

        base = str(originURL).rsplit(str('/'), 1)[0]
        trackname = originURL.rsplit(str('/'), 1)[-1].rsplit(str('.'), 1)[0]
        url = f'{base}/{trackname}.{format}'
        exists = requests.head(url)
        if (exists.status_code != 200):
            urls.append(f'{base}/{trackname}.mp3')
            print(f"\rCannot find track {index+1} '{unquote(trackname)}' in {format} format. Downloading the mp3 version instead.")
        else:
            urls.append(url)


    return urls

def download(dlurls:List[str], rawOutDir:str):
    # Keep the output directory path intact. Only file names should be sanitized.
    # Sanitizing the full path breaks absolute Windows paths like C:\Users\...
    output = Path(rawOutDir)
    output.mkdir(parents=True, exist_ok=True)
    for url in dlurls:
        fname = cleanPath(unquote(url.rsplit(str('/'), 1)[-1]))

        resp = requests.get(url, stream=True)
        total = int(resp.headers.get('content-length', 0))
        final_path = output / fname
        with open(final_path, 'wb') as file, tqdm(
            desc=fname,
            total=total,
            unit='iB',
            bar_format="{desc}: {percentage:3.0f}%|{bar}|{n_fmt}/{total_fmt} [{rate_fmt}]",
            unit_scale=True,
            unit_divisor=1024,
        ) as bar:
            for data in resp.iter_content(chunk_size=1024):
                size = file.write(data)
                bar.update(size)


def choosePreferredFormat(available_formats, wanted_format: str = "mp3") -> str:
    """Choose the best KHInsider audio format for a track/album.

    wanted_format keeps the old behavior. The special value 'best' prefers FLAC
    when KHInsider offers it and falls back to MP3.
    """
    formats = [str(fmt).lower() for fmt in (available_formats or [])]
    wanted = (wanted_format or "mp3").lower()
    if wanted in {"best", "auto"}:
        if "flac" in formats:
            return "flac"
        if "mp3" in formats:
            return "mp3"
        return formats[0] if formats else "mp3"
    if wanted in formats:
        return wanted
    if "mp3" in formats:
        return "mp3"
    return formats[0] if formats else wanted

def resolveDownloadUrl(track_page_url: str, format: str = "mp3") -> str:
    """Return the direct audio URL for a KHInsider track page.

    If the requested format is not available, mp3 is used as a fallback.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.6998.166 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Site":"same-site"}
    r = requests.get(track_page_url, headers=headers)
    parser = BeautifulSoup(r.text, 'html.parser')
    dllink = parser.select_one('.songDownloadLink')

    if not dllink:
        raise DLParseException

    dlanchor = dllink.parent

    if not dlanchor:
        raise DLParseException

    originURL = dlanchor.get('href').__str__()

    if not originURL:
        raise DLParseException

    base = str(originURL).rsplit(str('/'), 1)[0]
    trackname = originURL.rsplit(str('/'), 1)[-1].rsplit(str('.'), 1)[0]
    url = f'{base}/{trackname}.{format}'
    exists = requests.head(url)
    if exists.status_code != 200:
        return f'{base}/{trackname}.mp3'
    return url


def downloadFileAs(url: str, rawOutDir: str, filename: str) -> Path:
    # Keep the output directory path intact. Only file names should be sanitized.
    # Sanitizing the full path breaks absolute Windows paths like C:\Users\...
    output = Path(rawOutDir)
    output.mkdir(parents=True, exist_ok=True)
    fname = cleanPath(filename)

    resp = requests.get(url, stream=True)
    total = int(resp.headers.get('content-length', 0))
    final_path = output / fname
    with open(final_path, 'wb') as file, tqdm(
        desc=fname,
        total=total,
        unit='iB',
        bar_format="{desc}: {percentage:3.0f}%|{bar}|{n_fmt}/{total_fmt} [{rate_fmt}]",
        unit_scale=True,
        unit_divisor=1024,
    ) as bar:
        for data in resp.iter_content(chunk_size=1024):
            size = file.write(data)
            bar.update(size)
    return final_path


def embedCoverInMp3(audio_path: str | Path, cover_bytes: bytes, mime_type: str = 'image/jpeg') -> bool:
    """Embed album art into an MP3 file using ID3 APIC metadata."""
    if ID3 is None or APIC is None:
        raise RuntimeError('Cover embedding needs the mutagen package. Run: pip install mutagen')
    audio_path = Path(audio_path)
    if audio_path.suffix.lower() != '.mp3':
        return False
    try:
        tags = ID3(audio_path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall('APIC')
    tags.add(APIC(encoding=3, mime=mime_type or 'image/jpeg', type=3, desc='Cover', data=cover_bytes))
    tags.save(audio_path)
    return True

class DLParseException(Exception):
    """Raised when KHInsider page parsing fails unexpectedly."""


def cleanPath(path: str) -> str:
    """Return a file-name-safe version of *path*.

    This function is kept for compatibility with the original project.
    Only filenames should be passed here; full output directories must stay intact.
    """
    if os.environ.get("TERMUX_VERSION") is not None:
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", path)
    match os.name:
        case 'nt':
            return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", path)
        case _:
            return re.sub(r'[/]', "_", path)
