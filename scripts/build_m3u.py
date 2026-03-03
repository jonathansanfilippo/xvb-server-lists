#!/usr/bin/env python3
import json
import re
from pathlib import Path
from urllib.request import urlopen, Request

# === CONFIG DIRETTA ===
SOURCES = [
    "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/national.json",
]

OUT_FILE = "xvb-all.m3u"
LOGO_HOST = "https://channels.zappr.stream/logos"
COUNTRY_SUFFIX = "it"

# Filtri
ONLY_HTTPS = True
INCLUDE_ADULT = False  # <-- se vuoi includerli: metti True

CF_API = "https://cloudflare-api.zappr.stream/api?url="
VERCEL_API = "https://vercel-api.zappr.stream/api?url="


def slugify(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "channel"


def fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "xvb-all-bot/1.0"})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def is_adult(ch: dict) -> bool:
    # adult può essere True oppure "night"
    a = ch.get("adult")
    return a is True or isinstance(a, str)


def pick_url(channel: dict) -> str | None:
    # Priorità: nativeHLS → url
    url = (channel.get("nativeHLS") or {}).get("url") or channel.get("url")
    if not url:
        return None

    # zappr:// fallback su geoblock.url
    if url.startswith("zappr://"):
        gb = channel.get("geoblock")
        if isinstance(gb, dict) and gb.get("url"):
            url = gb["url"]
        else:
            return None

    # Proxy API
    gb = channel.get("geoblock")
    gb_api = gb.get("api") if isinstance(gb, dict) else None
    api = channel.get("api") or gb_api
    if api == "cloudflare":
        url = CF_API + url
    elif api == "vercel":
        url = VERCEL_API + url

    # Filtro HTTPS (dopo eventuale proxy: i proxy sono https)
    if ONLY_HTTPS and not url.startswith("https://"):
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


def group_title(ch: dict) -> str:
    if ch.get("type") == "audio" or ch.get("radio") is True:
        return "Radio"
    # puoi cambiare in "Nazionali/Regionali" se aggiungi più sorgenti
    return "DTT"


def stable_tvg_id(ch: dict, display_name: str) -> str:
    epg = ch.get("epg") or {}
    if isinstance(epg, dict) and epg.get("id"):
        base = slugify(str(epg["id"]))
    else:
        base = slugify(display_name)
    return f"{base}.{COUNTRY_SUFFIX}"


def sort_key(ch: dict):
    lcn = ch.get("parentLcn")
    if lcn is None:
        lcn = ch.get("lcn")
    try:
        lcn_num = int(lcn)
    except Exception:
        lcn_num = 99999

    sublcn = ch.get("sublcn")
    try:
        sub_num = int(sublcn) if sublcn is not None else 0
    except Exception:
        sub_num = 0

    name = (ch.get("name") or "").lower()
    return (lcn_num, sub_num, name)


def main():
    entries = []
    seen_urls = set()

    for source in SOURCES:
        data = fetch_json(source)

        for ch in flatten_channels(data):
            name = ch.get("name")
            if not name:
                continue

            # Adult filter
            if (not INCLUDE_ADULT) and is_adult(ch):
                continue

            url = pick_url(ch)
            if not url:
                continue

            # dedup per URL
            if url in seen_urls:
                continue
            seen_urls.add(url)

            lcn = ch.get("parentLcn") or ch.get("lcn")
            sublcn = ch.get("sublcn")
            display_name = name + (f" (S{sublcn})" if sublcn else "")

            logo = ch.get("logo")
            tvg_logo = f"{LOGO_HOST}/{logo}" if logo else None

            entries.append({
                "display_name": display_name,
                "url": url,
                "tvg_logo": tvg_logo,
                "tvg_id": stable_tvg_id(ch, display_name),
                "group": group_title(ch),
                "lcn": lcn,
                "raw": ch,
            })

    entries.sort(key=lambda e: sort_key(e["raw"]))

    lines = ["#EXTM3U", ""]
    for e in entries:
        lcn_tag = f'[{e["lcn"]}] ' if e["lcn"] is not None else ""

        attrs = [
            f'tvg-id="{e["tvg_id"]}"',
            f'tvg-name="{e["display_name"]}"',
            f'group-title="{e["group"]}"',
        ]
        if e["tvg_logo"]:
            attrs.insert(2, f'tvg-logo="{e["tvg_logo"]}"')

        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{lcn_tag}{e["display_name"]}')
        lines.append(e["url"])
        lines.append("")

    Path(OUT_FILE).write_text("\n".join(lines), encoding="utf-8")
    print(f"{OUT_FILE} generato ✅  (canali: {len(entries)})")


if __name__ == "__main__":
    main()#!/usr/bin/env python3
import json
import re
from urllib.request import urlopen, Request
from pathlib import Path

# === CONFIG DIRETTA ===
SOURCES = [
    "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/national.json",
    # puoi aggiungere altre regioni qui:
    # "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/regional/lombardia.json",
]

LOGO_HOST = "https://channels.zappr.stream/logos"
GROUP_TITLE = "DTT"
COUNTRY_SUFFIX = "it"

CF_API = "https://cloudflare-api.zappr.stream/api?url="
VERCEL_API = "https://vercel-api.zappr.stream/api?url="


# === FUNZIONI ===

def slugify(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "channel"


def fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "xvb-b-bot/1.0"})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def pick_url(channel: dict) -> str | None:
    # Priorità: nativeHLS → url
    url = (channel.get("nativeHLS") or {}).get("url") or channel.get("url")
    if not url:
        return None

    # zappr:// fallback
    if url.startswith("zappr://"):
        geoblock = channel.get("geoblock")
        if isinstance(geoblock, dict) and geoblock.get("url"):
            url = geoblock["url"]
        else:
            return None

    # Proxy API
    api = channel.get("api") or (channel.get("geoblock") or {}).get("api")
    if api == "cloudflare":
        url = CF_API + url
    elif api == "vercel":
        url = VERCEL_API + url

    return url


def flatten_channels(data: dict):
    for parent in data.get("channels", []):
        if not isinstance(parent, dict):
            continue
        if "categorySeparator" in parent:
            continue

        yield parent

        # include hbbtv subchannels
        for sub in (parent.get("hbbtv") or []):
            if not isinstance(sub, dict):
                continue
            if "categorySeparator" in sub:
                continue
            sub_copy = dict(sub)
            sub_copy["parentLcn"] = parent.get("lcn")
            yield sub_copy


# === BUILD PLAYLIST ===

def main():
    lines = ["#EXTM3U", ""]

    for source in SOURCES:
        data = fetch_json(source)

        for ch in flatten_channels(data):
            name = ch.get("name")
            if not name:
                continue

            stream_url = pick_url(ch)
            if not stream_url:
                continue

            logo = ch.get("logo")
            tvg_logo = f"{LOGO_HOST}/{logo}" if logo else None

            lcn = ch.get("parentLcn") or ch.get("lcn")
            sublcn = ch.get("sublcn")

            display_name = name + (f" (S{sublcn})" if sublcn else "")
            tvg_id = f"{slugify(display_name)}.{COUNTRY_SUFFIX}"

            lcn_tag = f"[{lcn}] " if lcn is not None else ""

            attrs = [
                f'tvg-id="{tvg_id}"',
                f'tvg-name="{display_name}"',
                f'group-title="{GROUP_TITLE}"'
            ]

            if tvg_logo:
                attrs.insert(2, f'tvg-logo="{tvg_logo}"')

            lines.append(f'#EXTINF:-1 {" ".join(attrs)},{lcn_tag}{display_name}')
            lines.append(stream_url)
            lines.append("")

    Path("xvb-b.m3u").write_text("\n".join(lines), encoding="utf-8")
    print("xvb-b.m3u generato correttamente ✅")


if __name__ == "__main__":
    main()
