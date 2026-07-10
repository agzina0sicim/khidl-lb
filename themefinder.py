import json
import hashlib
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional, Any
from urllib.parse import quote_plus, unquote, urljoin

import requests
from bs4 import BeautifulSoup

from .downloader import cleanPath, resolveDownloadUrl, downloadFileAs, embedCoverInMp3, choosePreferredFormat
from .soundtrack import BASEURL, Soundtrack

try:
    import yaml
except Exception:  # PyYAML is optional until a custom scoring file is used.
    yaml = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.6998.166 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "identity",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Site": "same-site",
}

CACHE_VERSION = 5
DEFAULT_CACHE_FILE = ".khidl-theme-cache.json"

DEFAULT_SCORING: dict[str, Any] = {
    "album": {
        "prefer": {
            "complete gamerip": 2550, "complete game rip": 2550, "gamerip": 2450,
            "game rip": 2450, "game-rip": 2450, "sound track cd": 1350,
            "original game soundtrack": 1260, "official soundtrack": 1200,
            "original soundtrack": 1160, "sound track": 960, "ost": 900,
            "soundtrack": 850, "complete": 100,
        },
        "penalize": {
            "lost tracks": -1400, "the lost tracks": -1450, "bonus": -650,
            "unused": -850, "unreleased": -850, "arrange": -850, "arranged": -850,
            "arrangement": -850, "remix": -950, "tribute": -900, "piano": -850,
            "orchestra": -850, "orchestral": -850, "concert": -760, "cover": -980,
            "fan": -1100, "doujin": -980, "sound effect": -1200, "sound effects": -1200,
            "sfx": -1200, "prototype": -700, "beta": -700, "demo": -360, "vinyl": -160,
        },
        "allowed_markers": ["gamerip", "game rip", "game-rip", "official soundtrack", "original soundtrack", "original game soundtrack", "soundtrack", "sound track", "ost"],
        "not_allowed_penalty": -1700,
        "vol_penalty": -420,
        "region": {"usa": 90, "us": 80, "u s": 80, "europe": 75, "eur": 70, "world": 65, "japan": -10, "jp": -10},
        "title": {
            "exact": 1400, "contains": 900, "starts_with": 420, "similarity_multiplier": 650,
            "token_match": 70, "missing_token": -160, "clean_suffix": 360, "allowed_suffix": 220, "bad_suffix": -900,
        },
        "platform": {"wanted": 1050, "wrong": -2200},
        "year": {"missing": -70, "inside_range": 480, "near_range": 120, "after_base": -560, "after_per_year": -45, "after_cap": -900, "before_base": -340, "before_per_year": -30, "before_cap": -600},
    },
    "track": {
        "prefer": {
            "main theme": 520, "title theme": 500, "title screen": 485,
            "opening theme": 455, "main title": 450, "theme of": 430,
            "opening": 410, "intro": 365, "main menu": 360, "menu": 315,
            "file select": 300, "character select": 245, "select": 210,
            "overworld": 255, "world map": 220, "field": 190, "title": 320,
            "staff roll": 85, "ending": 70, "credits": 45,
            "stage 1": 30, "level 1": 30, "track 1": 25,
        },
        "penalize": {
            "sound effect": -260, "sound effects": -260, "sfx": -260, "jingle": -260,
            "fanfare": -260, "victory": -260, "game over": -260, "boss": -260,
            "battle": -260, "fight": -260, "stage clear": -260, "lose": -260,
            "win": -260, "unused": -260, "demo": -260, "prototype": -260,
            "beta": -260, "voice": -260, "ambient": -260, "ambience": -260,
            "cutscene": -260, "movie": -260,
        },
        "base_start": 100, "base_index_penalty": -3, "track_one_bonus": 25,
    },
}

SCORING = json.loads(json.dumps(DEFAULT_SCORING))


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_scoring_config(scoring_file: Optional[str] = None) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_SCORING))
    if not scoring_file:
        default_path = Path("scoring.yaml")
        scoring_file = str(default_path) if default_path.exists() else None
    if scoring_file:
        path = Path(scoring_file)
        if not path.exists():
            raise FileNotFoundError(f"Scoring config not found: {path}")
        if yaml is None:
            raise RuntimeError("Custom scoring requires PyYAML. Install dependencies with: pip install .")
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("Scoring config must be a YAML object/dictionary.")
        _deep_merge(config, loaded)
    return config


def set_scoring_config(scoring_file: Optional[str] = None) -> None:
    global SCORING
    SCORING = load_scoring_config(scoring_file)
    if scoring_file:
        print(f"Scoring config: {scoring_file}")


def scoring_signature() -> str:
    payload = json.dumps(SCORING, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def scoring_pairs(section: str, kind: str):
    return list((SCORING.get(section, {}).get(kind, {}) or {}).items())

PLATFORM_ALIASES = {
    "nintendo64": ("nintendo 64", "n64"), "n64": ("nintendo 64", "n64"),
    "nintendosnes": ("super nintendo", "snes", "super famicom"), "snes": ("super nintendo", "snes", "super famicom"),
    "nintendones": ("nes", "nintendo entertainment system", "famicom"), "nes": ("nes", "nintendo entertainment system", "famicom"),
    "nintendogb": ("game boy", "gameboy", "gb"), "gb": ("game boy", "gameboy", "gb"),
    "nintendogbc": ("game boy color", "gameboy color", "gbc"), "gbc": ("game boy color", "gameboy color", "gbc"),
    "nintendogba": ("game boy advance", "gba"), "gba": ("game boy advance", "gba"),
    "nintendogc": ("gamecube", "game cube", "gc"), "gamecube": ("gamecube", "game cube", "gc"),
    "nintendods": ("nintendo ds", "nds", "ds"), "nds": ("nintendo ds", "nds", "ds"),
    "nintendo3ds": ("nintendo 3ds", "3ds"), "3ds": ("nintendo 3ds", "3ds"),
    "nintendowii": ("wii",), "wii": ("wii",), "nintendowiiu": ("wii u", "wiiu"), "wiiu": ("wii u", "wiiu"),
}
OTHER_PLATFORM_MARKERS = {"nes", "famicom", "super nintendo", "snes", "super famicom", "nintendo 64", "n64", "game boy", "gameboy", "gb", "game boy color", "gameboy color", "gbc", "game boy advance", "gba", "gamecube", "game cube", "gc", "nintendo ds", "nds", "ds", "nintendo 3ds", "3ds", "wii", "wii u", "wiiu", "switch", "nintendo switch", "ps1", "ps2", "ps3", "ps4", "ps5", "playstation", "xbox", "xbox 360", "xbox one", "pc", "windows", "steam", "dreamcast", "saturn", "genesis", "mega drive", "sega", "arcade", "mobile", "android", "ios"}
PLATFORM_YEAR_RANGES = {"nintendones": (1983, 1995), "nes": (1983, 1995), "nintendosnes": (1990, 1998), "snes": (1990, 1998), "nintendogb": (1989, 2001), "gb": (1989, 2001), "nintendogbc": (1998, 2003), "gbc": (1998, 2003), "nintendogba": (2001, 2008), "gba": (2001, 2008), "nintendo64": (1996, 2002), "n64": (1996, 2002), "nintendogc": (2001, 2007), "gamecube": (2001, 2007), "nintendods": (2004, 2014), "nds": (2004, 2014), "nintendo3ds": (2011, 2020), "3ds": (2011, 2020), "nintendowii": (2006, 2014), "wii": (2006, 2014), "nintendowiiu": (2012, 2018), "wiiu": (2012, 2018)}
NON_TITLE_TOKENS = {"gamerip", "game", "rip", "complete", "official", "original", "soundtrack", "sound", "track", "cd", "ost", "music", "score", "expanded", "edition", "version", "usa", "us", "europe", "eur", "world", "japan", "jp", "nintendo", "super", "nes", "snes", "n64", "gb", "gbc", "gba", "gameboy", "gamecube", "cube", "ds", "nds", "3ds", "wii", "wiiu", "u", "famicom", "color", "advance"}

@dataclass
class AlbumResult:
    name: str
    ost_id: str
    year: str = ""
    score: int = 0
    source_query: str = ""

@dataclass
class TrackChoice:
    title: str
    page_url: str
    score: int
    duration_seconds: Optional[int] = None

@dataclass
class ThemeCacheEntry:
    game_title: str
    platform: Optional[str]
    album_name: str
    album_id: str
    album_year: str
    album_score: int
    track_title: str
    track_page_url: str
    track_score: int
    duration_seconds: Optional[int]
    cover_url: str = ""


def normalize(text: str) -> str:
    text = text.replace("&", " and ").replace("é", "e").replace("É", "e")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def clean_game_title(title: str) -> str:
    # Helps fuzzy matching without changing the output filename.
    title = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", title)
    title = re.sub(r"\b(usa|europe|japan|world|rev\s*\d+|proto|beta)\b", " ", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip()


def title_tokens(title: str) -> set[str]:
    stop = {"the", "a", "and", "of", "for", "in", "edition", "version", "special", "deluxe"}
    return {tok for tok in normalize(clean_game_title(title)).split() if tok not in stop and len(tok) > 1}


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(clean_game_title(a)), normalize(clean_game_title(b))).ratio()


def canonical_platform_key(platform: Optional[str]) -> Optional[str]:
    if not platform:
        return None
    key = normalize(platform).replace(" ", "")
    return key if key in PLATFORM_ALIASES else None


def platform_aliases(platform: Optional[str]) -> tuple[str, ...]:
    key = canonical_platform_key(platform)
    if key:
        return PLATFORM_ALIASES[key]
    return (normalize(platform),) if platform else ()


def platform_marker_state(album_name: str, platform: Optional[str]) -> tuple[bool, bool]:
    if not platform:
        return False, False
    album_norm = normalize(album_name)
    wanted = {normalize(alias) for alias in platform_aliases(platform)}
    has_wanted = any(re.search(rf"\b{re.escape(alias)}\b", album_norm) for alias in wanted)
    other_markers = OTHER_PLATFORM_MARKERS - wanted
    has_other = any(re.search(rf"\b{re.escape(marker)}\b", album_norm) for marker in other_markers)
    return has_wanted, has_other


def is_wrong_platform(album_name: str, platform: Optional[str]) -> bool:
    has_wanted, has_other = platform_marker_state(album_name, platform)
    return bool(platform and has_other and not has_wanted)


def score_platform(album_name: str, platform: Optional[str]) -> int:
    if not platform:
        return 0
    has_wanted, has_other = platform_marker_state(album_name, platform)
    cfg = SCORING["album"].get("platform", {})
    return (int(cfg.get("wanted", 1050)) if has_wanted else 0) + (int(cfg.get("wrong", -2200)) if has_other and not has_wanted else 0)


def score_album_year(year: str, platform: Optional[str]) -> int:
    key = canonical_platform_key(platform)
    if not key or key not in PLATFORM_YEAR_RANGES:
        return 0
    cfg = SCORING["album"].get("year", {})
    match = re.search(r"\b(19\d{2}|20\d{2})\b", str(year))
    if not match:
        return int(cfg.get("missing", -70))
    album_year = int(match.group(1))
    start, end = PLATFORM_YEAR_RANGES[key]
    if start <= album_year <= end:
        return int(cfg.get("inside_range", 480))
    distance = min(abs(album_year - start), abs(album_year - end))
    if distance <= 2:
        return int(cfg.get("near_range", 120))
    if album_year > end:
        return int(cfg.get("after_base", -560)) - min(abs(int(cfg.get("after_cap", -900))), distance * abs(int(cfg.get("after_per_year", -45))))
    return int(cfg.get("before_base", -340)) - min(abs(int(cfg.get("before_cap", -600))), distance * abs(int(cfg.get("before_per_year", -30))))

def score_title_suffix(game_title: str, album_name: str) -> int:
    cfg = SCORING["album"].get("title", {})
    title_norm = normalize(clean_game_title(game_title))
    album_norm = normalize(album_name)
    if title_norm not in album_norm:
        return 0
    after = album_norm.split(title_norm, 1)[1].strip()
    if not after:
        return int(cfg.get("clean_suffix", 360))
    meaningful = []
    for token in after.split()[:5]:
        if token.isdigit() and len(token) == 4:
            continue
        if token in NON_TITLE_TOKENS:
            continue
        meaningful.append(token)
    return int(cfg.get("bad_suffix", -900)) if meaningful else int(cfg.get("allowed_suffix", 220))


def is_allowed_album_type(album_name: str) -> bool:
    album_norm = normalize(album_name)
    return any(normalize(str(marker)) in album_norm for marker in SCORING["album"].get("allowed_markers", []))


def quality_score(album_name: str) -> int:
    norm = normalize(album_name)
    score = 0
    for key, value in scoring_pairs("album", "prefer"):
        if normalize(str(key)) in norm:
            score += int(value)
    for key, value in scoring_pairs("album", "penalize"):
        if normalize(str(key)) in norm:
            score += int(value)
    if not is_allowed_album_type(album_name):
        score += int(SCORING["album"].get("not_allowed_penalty", -1700))
    return score


def score_album(game_title: str, album_name: str, query_tokens: Optional[set[str]] = None, platform: Optional[str] = None, year: str = "") -> int:
    query_tokens = query_tokens or title_tokens(game_title)
    album_norm = normalize(album_name)
    album_tokens = set(album_norm.split())
    normalized_title = normalize(clean_game_title(game_title))
    cfg = SCORING["album"].get("title", {})
    score = 0
    # Exact game recognition and fuzzy tolerance are the strongest non-type signals.
    if normalized_title == album_norm:
        score += int(cfg.get("exact", 1400))
    if normalized_title in album_norm:
        score += int(cfg.get("contains", 900))
    if album_norm.startswith(normalized_title):
        score += int(cfg.get("starts_with", 420))
    score += int(title_similarity(game_title, album_name) * int(cfg.get("similarity_multiplier", 650)))
    score += int(cfg.get("token_match", 70)) * len(query_tokens & album_tokens)
    missing_tokens = query_tokens - album_tokens
    score += int(cfg.get("missing_token", -160)) * len(missing_tokens)
    score += score_title_suffix(game_title, album_name)
    score += quality_score(album_name)
    score += score_album_year(year, platform)
    score += score_platform(album_name, platform)
    for key, value in (SCORING["album"].get("region", {}) or {}).items():
        if re.search(rf"\b{re.escape(normalize(str(key)))}\b", album_norm):
            score += int(value)
    if re.search(r"\b(vol|volume)\.?\s*(ii|2|iii|3|iv|4)\b", album_norm):
        score += int(SCORING["album"].get("vol_penalty", -420))
    return score

def build_search_queries(game_title: str, platform: Optional[str] = None) -> list[str]:
    base = clean_game_title(game_title)
    queries = [base]
    if platform:
        aliases = platform_aliases(platform)
        if aliases:
            queries += [f"{base} {aliases[0]}", f"{aliases[0]} {base}"]
            if len(aliases) > 1:
                queries.append(f"{base} {aliases[1]}")
    # Fault-tolerant alternative for titles saved as "Legend of Zelda, The".
    m = re.match(r"(.+),\s*(The|A|An)$", base, flags=re.I)
    if m:
        queries.append(f"{m.group(2)} {m.group(1)}")
    # Dedupe while preserving order.
    out = []
    seen = set()
    for q in queries:
        q = re.sub(r"\s+", " ", q).strip()
        if q and normalize(q) not in seen:
            seen.add(normalize(q)); out.append(q)
    return out


def parse_album_rows(html: str, game_title: str, platform: Optional[str], source_query: str) -> list[AlbumResult]:
    parser = BeautifulSoup(html, "html.parser")
    albumlist = parser.select_one(".albumList")
    if not albumlist:
        return []
    results: list[AlbumResult] = []
    query_tokens = title_tokens(game_title)
    for index, row in enumerate(albumlist.find_all("tr")):
        if index == 0:
            continue
        anchors = row.find_all("a")
        if len(anchors) < 2:
            continue
        anchor = anchors[1]
        name = anchor.get_text(" ", strip=True)
        href = anchor.get("href") or ""
        ost_id = href.rsplit("/", 1)[-1]
        year_cell = row.select_one("td:last-of-type")
        year = year_cell.get_text(strip=True) if year_cell else ""
        album_text = f"{name} {ost_id.replace('-', ' ')}"
        if platform and is_wrong_platform(album_text, platform):
            continue
        results.append(AlbumResult(name=name, ost_id=ost_id, year=year, score=score_album(game_title, album_text, query_tokens, platform=platform, year=year), source_query=source_query))
    return results


def search_albums(game_title: str, limit: int = 8, strict_album_types: bool = True, platform: Optional[str] = None) -> list[AlbumResult]:
    dedup: dict[str, AlbumResult] = {}
    for query in build_search_queries(game_title, platform):
        url = f"{BASEURL}/search?search={quote_plus(query)}&albumListSize=compact&sort=name"
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        for album in parse_album_rows(r.text, game_title, platform, source_query=query):
            if strict_album_types and not is_allowed_album_type(album.name):
                album.score += int(SCORING["album"].get("not_allowed_penalty", -1700))
            old = dedup.get(album.ost_id)
            if old is None or album.score > old.score:
                dedup[album.ost_id] = album
    return sorted(dedup.values(), key=lambda item: item.score, reverse=True)[:limit]


def parse_duration_seconds(text: str) -> Optional[int]:
    matches = re.findall(r"\b(?:(\d+):)?([0-5]?\d):([0-5]\d)\b", text)
    if not matches:
        return None
    hours, minutes, seconds = matches[-1]
    return (int(hours) * 3600 if hours else 0) + int(minutes) * 60 + int(seconds)


def get_track_choices(soundtrack: Soundtrack) -> list[TrackChoice]:
    choices: list[TrackChoice] = []
    songlist = soundtrack.pageinstance.select_one("#songlist")
    if not songlist:
        return choices
    for idx, row in enumerate(songlist.find_all("tr")):
        anchor = row.find("a")
        if not anchor:
            continue
        href = anchor.get("href") or ""
        title = anchor.get_text(" ", strip=True) or unquote(href.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        page_url = f"{BASEURL}{href}" if href.startswith("/") else href
        duration_seconds = parse_duration_seconds(row.get_text(" ", strip=True))
        choices.append(TrackChoice(title=title, page_url=page_url, score=score_track(title, idx), duration_seconds=duration_seconds))
    return choices


def score_track(track_title: str, index: int) -> int:
    norm = normalize(track_title)
    cfg = SCORING["track"]
    score = max(0, int(cfg.get("base_start", 100)) + index * int(cfg.get("base_index_penalty", -3)))
    for key, value in scoring_pairs("track", "prefer"):
        if normalize(str(key)) in norm:
            score += int(value)
    for key, value in scoring_pairs("track", "penalize"):
        if normalize(str(key)) in norm:
            score += int(value)
    if re.search(r"\b(01|1)\b", norm):
        score += int(cfg.get("track_one_bonus", 25))
    return score

def choose_theme_track(soundtrack: Soundtrack, min_duration_seconds: int = 30) -> Optional[TrackChoice]:
    choices = get_track_choices(soundtrack)
    eligible = [c for c in choices if c.duration_seconds is not None and c.duration_seconds >= min_duration_seconds]
    return sorted(eligible, key=lambda item: item.score, reverse=True)[0] if eligible else None

def get_album_cover_url(soundtrack: Soundtrack) -> str:
    """Return the first album cover URL from a KHInsider soundtrack page."""
    if not getattr(soundtrack, "images", None):
        return ""
    return urljoin(BASEURL, soundtrack.images[0])


def download_album_cover(soundtrack: Soundtrack) -> tuple[bytes, str, str]:
    """Download the album cover from KHInsider. Returns bytes, MIME type and URL."""
    cover_url = get_album_cover_url(soundtrack)
    if not cover_url:
        return b"", "", ""
    response = requests.get(cover_url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    mime_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not mime_type.startswith("image/"):
        suffix = cover_url.rsplit(".", 1)[-1].lower()
        mime_type = "image/png" if suffix == "png" else "image/jpeg"
    return response.content, mime_type, cover_url


def embed_album_cover_if_mp3(audio_path: Path, soundtrack: Soundtrack) -> str:
    """Embed the KHInsider album cover into a downloaded MP3."""
    if audio_path.suffix.lower() != ".mp3":
        return ""
    cover_bytes, mime_type, cover_url = download_album_cover(soundtrack)
    if not cover_bytes:
        print("[COVER] No album cover found on KHInsider.")
        return ""
    embedCoverInMp3(audio_path, cover_bytes, mime_type)
    print(f"[COVER] Embedded KHInsider album cover.")
    return cover_url



def cache_key(game_title: str, platform: Optional[str], min_duration_seconds: int) -> str:
    return f"{scoring_signature()}|{canonical_platform_key(platform) or 'any'}|{min_duration_seconds}|{normalize(clean_game_title(game_title))}"


def load_cache(cache_file: str = DEFAULT_CACHE_FILE) -> dict:
    path = Path(cache_file)
    if not path.exists():
        return {"version": CACHE_VERSION, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != CACHE_VERSION or not isinstance(data.get("entries"), dict):
            return {"version": CACHE_VERSION, "entries": {}}
        return data
    except Exception:
        return {"version": CACHE_VERSION, "entries": {}}


def save_cache(cache: dict, cache_file: str = DEFAULT_CACHE_FILE) -> None:
    Path(cache_file).write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def output_audio_path(game_title: str, output_dir: str, wanted_format: str) -> Path:
    return Path(output_dir) / f"{cleanPath(game_title)}.{wanted_format}"


def existing_audio_file(game_title: str, output_dir: str, wanted_format: str) -> Optional[Path]:
    suffixes = ("mp3", "flac", "m4a", "ogg", "wav")
    wanted = (wanted_format or "mp3").lower()
    if wanted not in {"best", "auto"}:
        preferred = output_audio_path(game_title, output_dir, wanted)
        if preferred.exists():
            return preferred
    # For skip-existing, any audio file with the LaunchBox game title is enough.
    for suffix in suffixes:
        candidate = Path(output_dir) / f"{cleanPath(game_title)}.{suffix}"
        if candidate.exists():
            return candidate
    return None


def resolve_preferred_audio_url(track_page_url: str, soundtrack: Soundtrack, wanted_format: str) -> tuple[str, str]:
    chosen_format = choosePreferredFormat(getattr(soundtrack, "formats", []), wanted_format)
    url = resolveDownloadUrl(track_page_url, chosen_format)
    suffix = url.rsplit(".", 1)[-1].split("?", 1)[0] or chosen_format
    return url, suffix


def download_title_theme(game_title: str, output_dir: str, wanted_format: str = "mp3", dry_run: bool = False, platform: Optional[str] = None, min_duration_seconds: int = 30, cache: Optional[dict] = None, refresh_cache: bool = False, skip_existing: bool = False) -> bool:
    if skip_existing and not dry_run:
        existing = existing_audio_file(game_title, output_dir, wanted_format)
        if existing:
            print(f"[EXISTS] {game_title} -> {existing}")
            return True
    key = cache_key(game_title, platform, min_duration_seconds)
    entry = None if refresh_cache or not cache else cache.get("entries", {}).get(key)
    if entry:
        print(f"[CACHE] {game_title} -> {entry['album_name']} / {entry['track_title']}")
        if dry_run:
            return True
        cached_ost = Soundtrack(entry["album_id"])
        if cached_ost.id is None:
            return False
        url, suffix = resolve_preferred_audio_url(entry["track_page_url"], cached_ost, wanted_format)
        print(f"[QUALITY] selected format: {suffix}")
        audio_path = downloadFileAs(url, output_dir, f"{cleanPath(game_title)}.{suffix}")
        if audio_path.suffix.lower() == ".mp3":
            embed_album_cover_if_mp3(audio_path, cached_ost)
        return True

    albums = search_albums(game_title, platform=platform)
    if not albums:
        platform_note = f" for platform '{platform}'" if platform else ""
        print(f"[SKIP] No matching gamerip/soundtrack album found{platform_note}: {game_title}", file=sys.stderr)
        return False
    album = albums[0]
    print(f"[ALBUM] {game_title} -> {album.name} ({album.ost_id}) year={album.year or '?'} score={album.score} query='{album.source_query}'" + (f" platform={platform}" if platform else ""))
    ost = Soundtrack(album.ost_id)
    if ost.id is None:
        return False
    track = choose_theme_track(ost, min_duration_seconds=min_duration_seconds)
    if not track:
        print(f"[SKIP] No track of at least {min_duration_seconds}s found for: {game_title}", file=sys.stderr)
        return False
    duration_note = f" ({track.duration_seconds}s)" if track.duration_seconds is not None else ""
    print(f"[TRACK] {game_title} -> {track.title}{duration_note} score={track.score}")
    cover_url = get_album_cover_url(ost)
    if cache is not None:
        cache.setdefault("entries", {})[key] = asdict(ThemeCacheEntry(game_title, platform, album.name, album.ost_id, album.year, album.score, track.title, track.page_url, track.score, track.duration_seconds, cover_url))
    if dry_run:
        return True
    url, suffix = resolve_preferred_audio_url(track.page_url, ost, wanted_format)
    print(f"[QUALITY] selected format: {suffix}")
    audio_path = downloadFileAs(url, output_dir, f"{cleanPath(game_title)}.{suffix}")
    embed_album_cover_if_mp3(audio_path, ost)
    return True


def launchbox_platform_xml_path(launchbox_dir: str, platform: str) -> Path:
    return Path(launchbox_dir) / "Data" / "Platforms" / f"{platform}.xml"


def read_launchbox_titles(launchbox_dir: str, platform: str) -> list[str]:
    xml_path = launchbox_platform_xml_path(launchbox_dir, platform)
    if not xml_path.exists():
        raise FileNotFoundError(f"LaunchBox platform XML not found: {xml_path}")
    root = ET.parse(xml_path).getroot()
    titles: list[str] = []
    # LaunchBox platform files store games as <Game><Title>...</Title>...</Game>.
    for game in root.findall(".//Game"):
        title = game.findtext("Title")
        if title and title.strip():
            titles.append(title.strip())
    # Fallback for XML variants where Title nodes are not under Game.
    if not titles:
        for node in root.findall(".//Title"):
            if node.text and node.text.strip():
                titles.append(node.text.strip())
    deduped: list[str] = []
    seen = set()
    for title in titles:
        key = normalize(clean_game_title(title))
        if key and key not in seen:
            seen.add(key)
            deduped.append(title)
    return deduped


def launchbox_music_output_dir(launchbox_dir: str, platform: str) -> str:
    return str(Path(launchbox_dir) / "Music" / platform)


def list_launchbox_platforms(launchbox_dir: str) -> list[str]:
    platforms_dir = Path(launchbox_dir) / "Data" / "Platforms"
    if not platforms_dir.exists():
        raise FileNotFoundError(f"LaunchBox platforms folder not found: {platforms_dir}")
    return sorted(path.stem for path in platforms_dir.glob("*.xml"))


def download_launchbox_one_platform(launchbox_dir: str, platform: str, wanted_format: str = "mp3", dry_run: bool = False, min_duration_seconds: int = 30, refresh_cache: bool = False, cache_file: str = DEFAULT_CACHE_FILE, skip_existing: bool = True) -> tuple[int, int, int, int]:
    titles = read_launchbox_titles(launchbox_dir, platform)
    output_dir = launchbox_music_output_dir(launchbox_dir, platform)
    if not dry_run:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    print(f"\n=== LaunchBox platform: {platform} ===")
    print(f"Source XML: {launchbox_platform_xml_path(launchbox_dir, platform)}")
    print(f"Output: {output_dir}")
    print(f"Titles found: {len(titles)}")
    print(f"Audio format: {wanted_format} ({'prefer FLAC, fallback MP3' if str(wanted_format).lower() in {'best', 'auto'} else 'requested format, fallback MP3 if unavailable'})")
    if skip_existing:
        print("Existing audio files will be skipped.")
    if not titles:
        print(f"No games found in LaunchBox platform XML for '{platform}'.", file=sys.stderr)
        return (0, 0, 0, 0)
    cache = load_cache(cache_file)
    ok = 0; missing: list[str] = []; errors: list[tuple[str, str]] = []
    total = len(titles)
    for idx, title in enumerate(titles, start=1):
        percent = int((idx - 1) / total * 100)
        print(f"\n[{idx}/{total} | {percent}% | ok {ok} | missing {len(missing)} | errors {len(errors)}] {title}")
        try:
            if download_title_theme(title, output_dir, wanted_format, dry_run=dry_run, platform=platform, min_duration_seconds=min_duration_seconds, cache=cache, refresh_cache=refresh_cache, skip_existing=skip_existing):
                ok += 1
            else:
                missing.append(title)
        except Exception as exc:
            print(f"[ERROR] {title}: {exc}", file=sys.stderr)
            errors.append((title, str(exc)))
        done_percent = int(idx / total * 100)
        print(f"[PROGRESS] {idx}/{total} ({done_percent}%) done | ok {ok} | missing {len(missing)} | errors {len(errors)}")
    save_cache(cache, cache_file)
    print(f"\nFinished platform '{platform}'. Successful or already existing: {ok}/{len(titles)}")
    failed_count = len(missing) + len(errors)
    if failed_count:
        print(f"Missing/failed: {failed_count}")
    if missing:
        print("\nNot found:")
        for title in missing:
            print(f"- {title}")
    if errors:
        print("\nErrors:")
        for title, message in errors:
            print(f"- {title}: {message}")
    return (len(titles), ok, len(missing), len(errors))


def download_launchbox_platform(launchbox_dir: str, platform: Optional[str] = None, wanted_format: str = "mp3", dry_run: bool = False, min_duration_seconds: int = 30, refresh_cache: bool = False, cache_file: str = DEFAULT_CACHE_FILE, skip_existing: bool = True, scoring_file: Optional[str] = None) -> None:
    set_scoring_config(scoring_file)
    platforms = [platform] if platform else list_launchbox_platforms(launchbox_dir)
    if not platforms:
        print("No LaunchBox platform XML files found.", file=sys.stderr)
        return
    if platform is None:
        print(f"Processing all LaunchBox platforms: {len(platforms)} found")
    grand_total = grand_ok = grand_missing = grand_errors = 0
    for pidx, platform_name in enumerate(platforms, start=1):
        if len(platforms) > 1:
            print(f"\n######## Platform {pidx}/{len(platforms)}: {platform_name} ########")
        total, ok, missing_count, error_count = download_launchbox_one_platform(launchbox_dir, platform_name, wanted_format, dry_run, min_duration_seconds, refresh_cache, cache_file, skip_existing)
        grand_total += total; grand_ok += ok; grand_missing += missing_count; grand_errors += error_count
    if len(platforms) > 1:
        print(f"\nAll platforms finished. Successful or already existing: {grand_ok}/{grand_total}")
        failed_count = grand_missing + grand_errors
        if failed_count:
            print(f"Missing/failed: {failed_count} (not found {grand_missing}, errors {grand_errors})")
