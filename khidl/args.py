import argparse
import json
import sys
from pathlib import Path

import requests
from jsonschema import validate, ValidationError

EXAMPLECONFIG = {
    "$schema": "https://raw.githubusercontent.com/qwerinope/khidl/refs/heads/main/schema.json",
    "defaultFormat": "mp3",
    "soundtracks": [
        {
            "soundtrack": "katamari-damacy-reroll-ps4-switch-windows-xbox-one-gamerip-2018",
            "format": "mp3",
            "output": "Katamari Damacy",
        },
        {
            "soundtrack": "https://downloads.khinsider.com/game-soundtracks/album/plants-vs.-zombies",
            "format": "flac",
            "images": False
        },
        "super-mario-64-soundtrack"
    ]
}

def get_arguments():
    # This function passes execution over to a helper function that parses all arguments.
    # It returns two values: a command name and the parsed command data.
    parser = argparse.ArgumentParser(description="Download videogame soundtracks from downloads.khinsider.com")
    subparser = parser.add_subparsers(dest="command", required=True)

    downloadcmd = subparser.add_parser('download', help="download a specific soundtrack")
    downloadcmd.set_defaults(func=parse_download_args)
    downloadcmd.add_argument("request", help="the soundtrack name or url the user wishes to download", nargs=1, type=str)
    downloadcmd.add_argument("output", help="store the resulting music in a specified directory", default=None, nargs='?', type=str)
    downloadcmd.add_argument("-f", "--format", help="the requested audio format, usually 'mp3', 'flac' or 'm4a'. 'nomusic' to download no music", type=str, default='mp3', nargs='?')
    downloadcmd.add_argument("--no-images", help="don't download the images on the specific soundtrack", action='store_true', default=False)

    jsoncmd = subparser.add_parser('batch', help="download multiple pre-defined soundtracks", description="download multiple soundtracks specified in a configuration file")
    jsoncmd.set_defaults(func=parse_batch_args)
    jsoncmd.add_argument('-i', '--init', help="create a default configuration for batch downloading", action='store_true', default=False)
    jsoncmd.add_argument('-f', '--force', help="ignore the json schema and try to parse the JSON anyway", action='store_true', default=False)

    searchcmd = subparser.add_parser('search', help="search KHInsider for soundtracks", description="use the search function on KHInsider and list all found soundtracks")
    searchcmd.set_defaults(func=parse_search_args)
    searchcmd.add_argument('query', help="search query", nargs='+', type=str)
    searchcmd.add_argument('--song', help="search for soundtracks containing a specific song", action='store_true', default=False)

    launchboxcmd = subparser.add_parser('launchbox', help="read one LaunchBox platform XML and download one theme per game")
    launchboxcmd.set_defaults(func=parse_launchbox_args)
    launchboxcmd.add_argument('launchbox_dir', help="LaunchBox root folder, e.g. C:\\Users\\You\\LaunchBox", type=str)
    launchboxcmd.add_argument('--platform', required=False, default=None, help="platform XML name, e.g. 'Nintendo 64'. If omitted, all XML files in Data\\Platforms are processed.", type=str)
    launchboxcmd.add_argument('-f', '--format', help="requested audio format, usually mp3 or flac. Use 'best' to prefer FLAC and fall back to MP3", type=str, default='mp3')
    launchboxcmd.add_argument('--dry-run', help="show the selected album and track without downloading", action='store_true', default=False)
    launchboxcmd.add_argument('--min-duration', help="minimum track length in seconds. Default: 30", type=int, default=30)
    launchboxcmd.add_argument('--refresh-cache', help="ignore cached album/track matches and search again", action='store_true', default=False)
    launchboxcmd.add_argument('--cache-file', help="cache file for theme matches. Default: .khidl-theme-cache.json", type=str, default='.khidl-theme-cache.json')
    launchboxcmd.add_argument('--no-skip-existing', help="download again even when the output MP3 already exists", action='store_true', default=False)
    launchboxcmd.add_argument('--scoring-file', help="YAML file with custom album/track scoring rules. Default: scoring.yaml if present", type=str, default=None)

    args = parser.parse_args()
    return args.func(args)

def parse_download_args(args):
    if 'downloads.khinsider.com' in  args.request[0]:
        ostid = args.request[0].rsplit(str('/'), 1)[-1]
    else:
        ostid = args.request[0]

    return "download" , (ostid, args.format, args.output, not args.no_images)  # True means album images should be downloaded.

def parse_batch_args(args):
    cfgfile = Path('soundtracks.json')
    if args.init:
        cfgfile.write_text(json.dumps(EXAMPLECONFIG, indent=4))
        print(f"Written default config to '{cfgfile}'")
        exit(0)

    if not cfgfile.exists():
        print(f"There is no configuration at '{cfgfile}'.\nPlease create a config using the '--init' argument, then modify it.", file=sys.stderr)
        exit(1)

    try:
        cfg = json.loads(cfgfile.read_text())
    except json.JSONDecodeError:
        print(f"The '{cfgfile}' file has a JSON syntax error.", file=sys.stderr)
        exit(1)

    if not args.force:
        r = requests.get("https://raw.githubusercontent.com/qwerinope/khidl/refs/heads/main/schema.json")
        schema = json.loads(r.text)

        try:
            validate(instance=cfg, schema=schema)
        except ValidationError:
            print(f"The '{cfgfile}' is incorrectly written. Make sure you comply with the JSON schema provided.", file=sys.stderr)
            exit(1)

    batchobj = []
    for item in cfg['soundtracks']:

        soundtrack = item if isinstance(item, str) else item["soundtrack"]
        if 'downloads.khinsider.com' in soundtrack:
            soundtrack = soundtrack.rsplit(str('/'), 1)[-1]

        if isinstance(item, dict):
            batchobj.append((
                soundtrack,
                item.get("format", cfg.get("defaultFormat", "mp3")),
                item.get("output", None),
                item.get("images", True)
            ))

        elif isinstance(item, str):  # Handle shorthand entries that only contain the soundtrack ID.
            batchobj.append((
                soundtrack,
                cfg.get("defaultFormat", "mp3"),
                None,
                True
            ))

    return "batch", batchobj

def parse_search_args(args):
    finalquery = f"https://downloads.khinsider.com/search?search={' '.join(args.query)}&albumListSize=compact&type={'song' if args.song else ''}&sort=name"

    return "search", finalquery



def parse_launchbox_args(args):
    return "launchbox", (args.launchbox_dir, args.platform, args.format, args.dry_run, args.min_duration, args.refresh_cache, args.cache_file, not args.no_skip_existing, args.scoring_file)
