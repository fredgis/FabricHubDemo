"""Expand real film metadata from Wikidata CC0 and verify any reused Commons artwork."""
import argparse
import html
import json
import re
import time
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen


def text(value):
    return html.unescape(re.sub(r"<[^>]*>", "", value or "")).strip()


def artwork_metadata(titles):
    query = urlencode({
        "action": "query", "format": "json", "titles": "|".join(titles),
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 900,
    })
    request = Request("https://commons.wikimedia.org/w/api.php?" + query,
                      headers={"User-Agent": "MSFlix-Fabric-Roadshow/1.0"})
    with urlopen(request, timeout=90) as response:
        document = json.load(response)
    result = {}
    for page in document.get("query", {}).get("pages", {}).values():
        info = page.get("imageinfo", [])
        if not info:
            continue
        item = info[0]
        metadata = item.get("extmetadata", {})
        license_name = text(metadata.get("LicenseShortName", {}).get("value"))
        if not (license_name.startswith("CC BY") or license_name in ("Public domain", "CC0")):
            continue
        if "ND" in license_name or "NC" in license_name:
            continue
        result[page["title"]] = {
            "image_url": item.get("thumburl") or item["url"],
            "artwork_license": license_name,
            "artwork_license_url": metadata.get("LicenseUrl", {}).get("value"),
            "artwork_author": text(metadata.get("Artist", {}).get("value")),
            "artwork_source_url": item.get("descriptionurl"),
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        raise ValueError("Catalog expansion must be bounded to at most 1000 sourced films.")
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root / ".state" / "wikidata-films.json").read_text(encoding="utf-8-sig"))
    grouped = {}
    for row in rows:
        grouped.setdefault(row["film"]["value"], []).append(row)
    selected = []
    for uri, group in sorted(grouped.items()):
        labelled = next((r for r in group if not r["filmLabel"]["value"].startswith("Q")), None)
        if not labelled:
            continue
        qid = uri.rsplit("/", 1)[1]
        duration = int(Decimal(labelled["duration"]["value"]) * 60)
        if duration <= 0:
            continue
        image = next((r.get("image", {}).get("value") for r in group if r.get("image")), None)
        release = min(r["release"]["value"] for r in group)[:10]
        selected.append({
            "content_key": "MSF-WD-" + qid,
            "title": labelled["filmLabel"]["value"],
            "release_date": release,
            "duration_seconds": duration,
            "genre": "Non renseigne",
            "content_type": "MOVIE",
            "source_url": "https://www.wikidata.org/wiki/" + qid,
            "metadata_license": "CC0",
            "metadata_date_precision": "source-not-qualified",
            "license": "CC0 metadata; no distribution-rights claim",
            "attribution": f"Film metadata: Wikidata {qid}, CC0.",
            "image_url": "/catalog-unavailable.svg",
            "artwork_available": False,
            "is_active": True,
            "_commons_title": "File:" + unquote(image.rsplit("/", 1)[1]) if image else None,
        })
        if len(selected) >= args.limit:
            break
    wanted = sorted({r["_commons_title"] for r in selected if r["_commons_title"]})
    art = {}
    for offset in range(0, len(wanted), 40):
        art.update(artwork_metadata(wanted[offset:offset + 40]))
        time.sleep(0.5)
    for film in selected:
        title = film.pop("_commons_title")
        if title in art:
            film.update(art[title])
            film["artwork_available"] = True
            film["license"] = "CC0 metadata / " + film["artwork_license"] + " artwork"
            film["attribution"] += " Artwork: " + film["artwork_author"] + ", " + film["artwork_license"] + "."
    existing = json.loads((root / "data" / "catalog.json").read_text(encoding="utf-8-sig"))
    existing = [r for r in existing if not r["content_key"].startswith("MSF-WD-")]
    combined = existing + selected
    (root / "data" / "catalog.json").write_text(json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "data" / "catalog.volume.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "total_real_films": len(combined), "additional_real_films": len(selected),
        "licensed_artwork": sum(r["artwork_available"] for r in selected),
        "missing_artwork_explicit": sum(not r["artwork_available"] for r in selected),
    }))


if __name__ == "__main__":
    main()
