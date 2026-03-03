#!/usr/bin/env python3
import json
import re
from urllib.request import urlopen, Request
from pathlib import Path

# ================= CONFIG =================

SOURCES = [
    "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/national.json",
]

LOGO_HOST = "https://channels.zappr.stream/logos"
COUNTRY_SUFFIX = "it"
GROUP_TITLE = "Nazionali"

canali = [
    "Rai 1", "Rai 2", "Rai 3", "Rete 4", "Canale 5", "Italia 1",
    "La7", "TV8", "Nove", "20 Mediaset", "Rai 4", "Iris",
    "Rai 5", "Rai Movie", "Rai Premium", "Cielo", "Twentyseven",
    "TV 2000", "La7 Cinema", "La 5", "Real Time", "QVC",
    "Food Network", "Cine34", "Focus", "RTL 102.5", "Discovery",
    "Giallo", "Top Crime", "Boing", "K2", "Rai Gulp", "Rai YoYo",
    "Frisbee", "Cartoonito", "Super!", "Rai News 24", "Italia 2",
    "Sky TG24", "TGCOM 24", "DMAX", "Rai Storia", "Mediaset Extra",
    "HGTV", "Rai Scuola", "Rai Sport", "Discovery Turbo", "il61",
    "Donna TV", "SuperTennis", "Deejay TV", "RadioItaliaTV",
    "Radio KISS KISS TV", "Rai Radio 2 Visual Radio", "RTL 102.5 Traffic",
    "Rai 4K", "Rai Radio 2 Visual Radio", "Alma TV", "Travel TV",
    "Radio 105 TV", "R101 TV", "Travel TV", "MAN-GA",
    "Radio24-IlSole24OreTV", "BeJoy.Kids", "Gambero Rosso",
    "RadioFreccia", "RDS Social TV", "Radio ZETA",
    "Radio TV Serie A con RDS", "Sportitalia SOLOCALCIO",
    "BIKE Channel", "Radio Montecarlo TV", "Virgin Radio TV",
    "Senato TV", "Camera dei Deputati"
]

# =========================================


def slugify(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "channel"


def fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "xvb-b-bot/1.0"})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def to_int(v):
    if v is None:
        return None
    try:
        return int(float(str(v)))
    except:
        return None


def pick_url(channel: dict):
    url = (channel.get("nativeHLS") or {}).get("url") or channel.get("url")
    if not url:
        return None

    if url.startswith("zappr://"):
        geoblock = channel.get("geoblock")
        if isinstance(geoblock, dict) and geoblock.get("url"):
            return geoblock["url"]
        return None

    return url


def flatten_channels(data: dict):
    for parent in data.get("channels", []):
        if not isinstance(parent, dict):
            continue
        if "categorySeparator" in parent:
            continue

        yield parent

        for sub in (parent.get("hbbtv") or []):
            if not isinstance(sub, dict):
                continue
            if "categorySeparator" in sub:
                continue
            sub_copy = dict(sub)
            sub_copy["parentLcn"] = parent.get("lcn")
            yield sub_copy


# ================= BUILD =================

def main():
    all_channels = []

    for source in SOURCES:
        data = fetch_json(source)
        for ch in flatten_channels(data):
            all_channels.append(ch)

    # mappa nome → canale
    channel_map = {}
    for ch in all_channels:
        name = ch.get("name")
        if name:
            channel_map[name.strip()] = ch

    lines = ["#EXTM3U", ""]

    used = set()

    # PRIMA: quelli nel tuo array, nel TUO ordine
    for nome in canali:
        ch = channel_map.get(nome)
        if not ch:
            continue

        stream_url = pick_url(ch)
        if not stream_url:
            continue

        used.add(nome)

        lcn = to_int(ch.get("parentLcn") or ch.get("lcn"))
        logo = ch.get("logo")
        tvg_logo = f"{LOGO_HOST}/{logo}" if logo else None

        tvg_id = f"{slugify(nome)}.{COUNTRY_SUFFIX}"
        lcn_tag = f"[{lcn}] " if lcn else ""

        attrs = [
            f'tvg-id="{tvg_id}"',
            f'tvg-name="{nome}"',
            f'group-title="{GROUP_TITLE}"'
        ]

        if tvg_logo:
            attrs.insert(2, f'tvg-logo="{tvg_logo}"')

        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{lcn_tag}{nome}')
        lines.append(stream_url)
        lines.append("")

    # POI: tutto il resto ordinato per LCN
    rest = [c for c in all_channels if c.get("name") not in used]

    rest.sort(key=lambda x: (to_int(x.get("lcn")) or 9999))

    for ch in rest:
        name = ch.get("name")
        if not name:
            continue

        stream_url = pick_url(ch)
        if not stream_url:
            continue

        lcn = to_int(ch.get("parentLcn") or ch.get("lcn"))
        logo = ch.get("logo")
        tvg_logo = f"{LOGO_HOST}/{logo}" if logo else None

        tvg_id = f"{slugify(name)}.{COUNTRY_SUFFIX}"
        lcn_tag = f"[{lcn}] " if lcn else ""

        attrs = [
            f'tvg-id="{tvg_id}"',
            f'tvg-name="{name}"',
            f'group-title="{GROUP_TITLE}"'
        ]

        if tvg_logo:
            attrs.insert(2, f'tvg-logo="{tvg_logo}"')

        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{lcn_tag}{name}')
        lines.append(stream_url)
        lines.append("")

    Path("xvb-all.m3u").write_text("\n".join(lines), encoding="utf-8")
    print("xvb-all.m3u generato correttamente")


if __name__ == "__main__":
    main()
