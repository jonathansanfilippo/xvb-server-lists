#!/usr/bin/env python3
import json
import re
from pathlib import Path
from urllib.request import urlopen, Request

# =========================
# CONFIG
# =========================

SOURCES = [
    "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/national.json",
]

OUT_FILE = "xvb-all.m3u"
LOGO_HOST = "https://channels.zappr.stream/logos"
COUNTRY_SUFFIX = "it"

ONLY_HTTPS = True
INCLUDE_ADULT = False  # metti True se vuoi includerli

CF_API = "https://cloudflare-api.zappr.stream/api?url="
VERCEL_API = "https://vercel-api.zappr.stream/api?url="


# =========================
# UTILS
# =========================

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
    a = ch.get("adult")
    return a is True or isinstance(a, str)


# =========================
# STREAM URL LOGIC
# =========================

def pick_url(channel: dict) -> str | None:
    # Priorità: nativeHLS → url
    url = (channel.get("nativeHLS") or {}).get("url") or channel.get("url")
    if not url:
        return None

    geoblock = channel.get("geoblock")

    # zappr:// fallback
    if url.startswith("zappr://"):
        if isinstance(geoblock, dict) and geoblock.get("url"):
            url = geoblock["url"]
        else:
            return None

    # Proxy API (geoblock può essere bool o dict)
    gb_api = geoblock.get("api") if isinstance(geoblock, dict) else None
    api = channel.get("api") or gb_api

    if api == "cloudflare":
        url = CF_API + url
    elif api == "vercel":
        url = VERCEL_API + url

    # Solo HTTPS
    if ONLY_HTTPS and not url.startswith("https://"):
        return None

    return url


# =========================
# FLATTEN (include hbbtv)
# =========================

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


# =========================
# SORT
# =========================

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


# =========================
# MAIN
# =========================

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
            if not INCLUDE_ADULT and is_adult(ch):
                continue

            url = pick_url(ch)
            if not url:
                continue

            # Dedup URL
            if url in seen_urls:
                continue
            seen_urls.add(url)

            lcn = ch.get("parentLcn") or ch.get("lcn")
            sublcn = ch.get("sublcn")
            display_name = name + (f" (S{sublcn})" if sublcn else "")

            logo = ch.get("logo")
            tvg_logo = f"{LOGO_HOST}/{logo}" if logo else None

            epg = ch.get("epg") or {}
            if isinstance(epg, dict) and epg.get("id"):
                base_id = slugify(str(epg["id"]))
            else:
                base_id = slugify(display_name)

            tvg_id = f"{base_id}.{COUNTRY_SUFFIX}"

            group = "Radio" if ch.get("type") == "audio" or ch.get("radio") else "DTT"

            entries.append({
                "display_name": display_name,
                "url": url,
                "tvg_logo": tvg_logo,
                "tvg_id": tvg_id,
                "group": group,
                "lcn": lcn,
                "raw": ch,
            })

    # Ordinamento per LCN
    entries.sort(key=lambda e: sort_key(e["raw"]))

    # Build M3U
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
    main()
