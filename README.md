# KHIDL LaunchBox Music Downloader

> This project is not affiliated with KHInsider or LaunchBox.

This fork extends `khidl` with LaunchBox support. It can read LaunchBox platform XML files, find one representative soundtrack theme per game on KHInsider, and save the audio directly into the matching LaunchBox music folder.

## Features

- Download a full KHInsider album by ID or URL.
- Search KHInsider from the command line.
- Batch-download albums from `soundtracks.json`.
- Read LaunchBox games from `Data/Platforms/<Platform>.xml`.
- Use the game title from `<Title>...</Title>`.
- Save music to `LaunchBox/Music/<Platform>/`.
- Skip existing audio files by default in LaunchBox mode.
- Process one platform or all LaunchBox platform XML files.
- Select one representative theme track per game.
- Prefer Gamerips, official soundtracks, original soundtracks, OSTs, and Sound Track CDs.
- Penalize remixes, piano albums, orchestral albums, fan albums, bonus tracks, lost tracks, beta/prototype albums, and wrong-platform matches.
- Score album title similarity, platform, release year, album quality, and track quality.
- Prefer tracks such as Main Theme, Title Theme, Opening, Intro, Menu, Title Screen, Overworld, and World Map.
- Skip tracks shorter than the configured minimum duration. The default is 30 seconds.
- Prefer FLAC with `--format best`, falling back to MP3 when FLAC is unavailable.
- Embed KHInsider album cover art into downloaded MP3 files.
- Cache album and track matches in `.khidl-theme-cache.json`.
- Allow custom scoring through `scoring.yaml`.
- Show clearer progress while processing large LaunchBox libraries.

## Requirements

Before installing, make sure you have:

- Python 3.10 or newer
- pip
- LaunchBox installed
- LaunchBox platform XML files in `LaunchBox/Data/Platforms/`
- An active internet connection

On Windows, verify Python with:

    python --version
    pip --version
    
## Install locally

From the extracted project folder:

```powershell
pip install .
```

Check that the command is available:

```powershell
khidl --help
```

If Windows cannot find `khidl`, use:

```powershell
python -m khidl.app --help
```

## LaunchBox mode

### One platform

```powershell
khidl launchbox "C:\Users\YourName\LaunchBox" --platform "Nintendo 64" --format best
```

This reads:

```text
C:\Users\YourName\LaunchBox\Data\Platforms\Platform.xml
```

and writes audio files to:

```text
C:\Users\YourName\LaunchBox\Music\Platform\
```

### All platforms

Omit `--platform` to process every XML file in `Data\Platforms`:

```powershell
khidl launchbox "C:\Users\YourName\LaunchBox" --format best
```

### Test run without downloading

```powershell
khidl launchbox "C:\Users\YourName\LaunchBox" --platform "Nintendo 64" --format best --dry-run
```

### MP3 only

```powershell
khidl launchbox "C:\Users\YourName\LaunchBox" --platform "Nintendo 64" --format mp3
```

### FLAC only

```powershell
khidl launchbox "C:\Users\YourName\LaunchBox" --platform "Nintendo 64" --format flac
```

### Best available quality

`best` prefers FLAC and falls back to MP3:

```powershell
khidl launchbox "C:\Users\YourName\LaunchBox" --platform "Nintendo 64" --format best
```

### Refresh the cache

Use this after changing `scoring.yaml` or when you want the tool to search again:

```powershell
khidl launchbox "C:\Users\YourName\LaunchBox" --platform "Nintendo 64" --format best --refresh-cache
```

### Download again even if audio already exists

LaunchBox mode skips existing audio files by default. To force a new download:

```powershell
khidl launchbox "C:\Users\YourName\LaunchBox" --platform "Nintendo 64" --format best --no-skip-existing
```

## Custom scoring

The default scoring behavior is stored in `scoring.yaml`. You can edit it to change which album and track names are preferred or penalized.

Example:

```yaml
album:
  prefer:
    gamerip: 2450
    official soundtrack: 1200
    sound track cd: 1350
  penalize:
    remix: -950
    lost tracks: -1400

track:
  prefer:
    main theme: 520
    title theme: 500
  penalize:
    battle: -260
    boss: -260
```

Run with a custom scoring file:

```powershell
khidl launchbox "C:\Users\YourName\LaunchBox" --platform "Nintendo 64" --format best --scoring-file scoring.yaml --refresh-cache
```

## Original khidl commands

Download one album:

```powershell
khidl download super-mario-64-soundtrack --format mp3
```

Search KHInsider:

```powershell
khidl search super mario 64
```

Create a batch config:

```powershell
khidl batch --init
```

## Repository structure

```text
khidl/
  app.py          # CLI dispatcher
  args.py         # argument parsing
  downloader.py   # download helpers and MP3 cover embedding
  search.py       # KHInsider search command
  soundtrack.py   # KHInsider album parser
  themefinder.py  # LaunchBox theme selection logic
scoring.yaml      # default scoring configuration
pyproject.toml    # Python package metadata
requirements.txt  # runtime dependencies
README.md
LICENSE
```
