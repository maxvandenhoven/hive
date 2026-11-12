"""Download the CC0 surfaces and room lighting of the Blender renderer from Poly Haven.

The assets are listed in `blender/assets.toml` and saved in `blender/.cache/`:
`surfaces/<id>/{diffuse,roughness,normal}.jpg` and `hdris/<id>.hdr`. Files that exist and
match their checksum are skipped, so the script can be rerun after adding assets.
"""

import argparse
import hashlib
import json
import logging
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

POLYHAVEN_FILES_URL = "https://api.polyhaven.com/files/{asset_id}"
"""The Poly Haven endpoint listing the download URLs and checksums of an asset."""

POLYHAVEN_USER_AGENT = "hive-render-assets/1.0"
"""The user agent of the requests, which Poly Haven asks API clients to set."""

SURFACE_MAPS = {"Diffuse": "diffuse", "Rough": "roughness", "nor_gl": "normal"}
"""The Poly Haven texture maps a surface needs, and their local file names."""


def fetch_json(url: str) -> Any:
    """Download and parse a JSON document.

    Args:
        url: The URL.

    Returns:
        The parsed document.
    """
    request = urllib.request.Request(url, headers={"User-Agent": POLYHAVEN_USER_AGENT})

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def download(url: str, md5: str, path: Path) -> bool:
    """Download a file unless it already exists with the expected checksum.

    Args:
        url: The URL of the file.
        md5: The expected MD5 checksum as hex digits.
        path: Where to save the file.

    Returns:
        Whether the file was downloaded.

    Raises:
        ValueError: If the downloaded file does not match the checksum.
    """
    if path.exists() and hashlib.md5(path.read_bytes()).hexdigest() == md5:
        return False

    request = urllib.request.Request(url, headers={"User-Agent": POLYHAVEN_USER_AGENT})

    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()

    if hashlib.md5(data).hexdigest() != md5:
        msg = f"The download of `{url}` does not match its checksum."
        raise ValueError(msg)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    return True


def fetch_assets(manifest: Path, cache: Path) -> int:
    """Download every asset of the manifest that is missing from the cache.

    Args:
        manifest: The `assets.toml` file.
        cache: The cache directory.

    Returns:
        The number of downloaded files.
    """
    config = tomllib.loads(manifest.read_text())
    downloaded = 0

    for kind, asset_ids in config["surfaces"].items():
        for asset_id in asset_ids:
            files = fetch_json(POLYHAVEN_FILES_URL.format(asset_id=asset_id))

            for map_name, file_name in SURFACE_MAPS.items():
                entry = files[map_name][config["resolution"]]["jpg"]
                path = cache / "surfaces" / asset_id / f"{file_name}.jpg"
                downloaded += download(url=entry["url"], md5=entry["md5"], path=path)

            logger.info("Surface `%s` (%s) is ready.", asset_id, kind)

    for asset_id in config["hdris"]:
        files = fetch_json(POLYHAVEN_FILES_URL.format(asset_id=asset_id))
        entry = files["hdri"][config["hdri_resolution"]]["hdr"]
        path = cache / "hdris" / f"{asset_id}.hdr"
        downloaded += download(url=entry["url"], md5=entry["md5"], path=path)
        logger.info("Environment `%s` is ready.", asset_id)

    return downloaded


def main() -> None:
    """Parse the command line and download the assets."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    root = Path(__file__).resolve().parents[1] / "blender"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=root / "assets.toml")
    parser.add_argument("--cache", type=Path, default=root / ".cache")
    args = parser.parse_args()
    downloaded = fetch_assets(manifest=args.manifest, cache=args.cache)
    logger.info("Downloaded %d files into `%s`.", downloaded, args.cache)


if __name__ == "__main__":
    main()
