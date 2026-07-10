import sys
from .args import get_arguments
from .soundtrack import Soundtrack
from .downloader import preDownloadMusic, download, DLParseException
from .search import search, SearchParsingError, SearchNoResults
from .themefinder import download_launchbox_platform

class FormatNotAvailable(Exception):
    """Raised when the requested format is not available on KHInsider."""
    def __init__(self, soundtrack, wanted_format, *args):
        super().__init__(*args)
        self.message = f"Format {wanted_format} isn't available on {soundtrack.name}. Options: {', '.join(soundtrack.formats)}"
    def __str__(self):
        return self.message

def download_manager(soundtrack_id, wanted_format, out_dir, get_images):
    if (not get_images and wanted_format == "nomusic"):
        print("Nothing to download: both music and images are disabled", file=sys.stderr)
        return 'err'

    ost = Soundtrack(soundtrack_id)

    if ost.id == None:
        return 'err'

    filelist = []

    print(f"Downloading '{ost.name}'...")

    if wanted_format != "nomusic":
        if wanted_format not in ost.formats:
            raise FormatNotAvailable(ost, wanted_format)

        filelist = preDownloadMusic(ost, wanted_format)

    output_dir = out_dir if out_dir else ost.name
    if get_images:
        filelist += ost.images

    download(filelist, output_dir)
    print(f"Downloaded '{ost.name}' to '{output_dir}'")
    return 'ok'

def CLI():
    command, data = get_arguments()
    match command:
        case "download":
            # The data tuple consists of: (soundtrack_id, wanted_format, out_dir, get_images)
            try:
                status = download_manager(*data)
                if status == "err":
                    exit(1)
            except FormatNotAvailable as e:
                print(e, file=sys.stderr)
                exit(1)
            except DLParseException:
                print("An error occurred!\nPlease leave an issue at https://github.com/qwerinope/khidl/issues", file=sys.stderr)
                exit(1)

        case "batch":
            # The data array contains tuples that consist of: (soundtrack_id, wanted_format, out_dir, get_images)
            print(f"Successfully parsed configuration.\nDownloading {len(data)} soundtracks.")

            for ost in data:
                try:
                    status = download_manager(*ost)
                    if status == "err":
                        continue
                except FormatNotAvailable as e:
                    print(e)
                    continue
                except DLParseException:
                    print("An error occurred!\nPlease leave an issue at https://github.com/qwerinope/khidl/issues", file=sys.stderr)
                    continue

        case "search":
            # Data is a URL to the search page on KHInsider
            try:
                search(data)
            except SearchParsingError:
                print("An error occurred!\nPlease leave an issue at https://github.com/qwerinope/khidl/issues", file=sys.stderr)
                exit(1)
            except SearchNoResults:
                print("No soundtracks matched the request.", file=sys.stderr)
                exit(1)

        case "launchbox":
            # Data tuple: (launchbox_dir, platform, wanted_format, dry_run, min_duration_seconds, refresh_cache, cache_file, skip_existing)
            try:
                download_launchbox_platform(*data)
            except DLParseException:
                print("An error occurred while resolving a download link.", file=sys.stderr)
                exit(1)



if __name__ == "__main__":
    CLI()
