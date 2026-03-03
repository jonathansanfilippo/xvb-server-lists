#!/usr/bin/env python3
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

OUTFILE = Path("xvb-fast-samsung.m3u")
GROUP_TITLE = "FAST • Samsung TV Plus"

# API ufficiale Samsung (IT)
SAMSUNG_API = "https://i.api.samsung.com/v1/smarttv/channels?country=IT"


@dataclass
class Channel:
    name: str
    lcn: int | None
    url: str
    logo: str | None


def http_get_json(url: str):
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    })
    with urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def parse_channels():
    data = http_get_json(SAMSUNG_API)

    out = []

    for ch in data.get("channels", []):
        name = ch.get("name")
        if not name:
            continue

        # Skip DRM
        if ch.get("drm"):
            continue

        lcn = ch.get("number")
        try:
            lcn = int(lcn) if lcn else None
        except:
            lcn = None

        logo = ch.get("logo")

        # stream diretto HLS
        stream = ch.get("stream")
        if not stream:
            continue

        out.append(Channel(
            name=name.strip(),
            lcn=lcn,
            url=stream,
            logo=logo
        ))

    # Ordine: prima con LCN, poi resto
    out.sort(key=lambda x: (x.lcn is None, x.lcn if x.lcn else 999999, x.name.lower()))
    return out


def build_m3u(channels):
    lines = ["#EXTM3U", ""]
    for ch in channels:
        lcn_tag = f"[{ch.lcn}] " if ch.lcn else ""
        attrs = [
            f'tvg-name="{ch.name}"',
            f'tvg-logo="{ch.logo}"' if ch.logo else None,
            f'group-title="{GROUP_TITLE}"',
        ]
        attrs = [a for a in attrs if a]

        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{lcn_tag}{ch.name}')
        lines.append(ch.url)
        lines.append("")

    return "\n".join(lines)


def main():
    channels = parse_channels()
    OUTFILE.write_text(build_m3u(channels), encoding="utf-8")
    print(f"{OUTFILE} generato: {len(channels)} canali ✅")


if __name__ == "__main__":
    main()
