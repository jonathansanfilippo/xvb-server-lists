#!/usr/bin/env python3
import json
import re
import time
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Set

# === CONFIG DIRETTA ===
SOURCES = [
    "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/national.json",
    # aggiungi altri json se vuoi:
    # "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/regional/lombardia.json",
]

OUT_FILE = "xvb-all.m3u"

LOGO_HOST = "https://channels.zappr.stream/logos"
GROUP_TITLE = "DTT"
COUNTRY_SUFFIX = "it"

CF_API = "https://cloudflare-api.zappr.stream/api?url="
VERCEL_API = "https://vercel-api.zappr.stream/api?url="

# Tipi che non sono stream "diretti" (se un giorno li vuoi, togli dalla lista)
SKIP_TYPES = {"iframe", "popup"}  # aggiungi "youtube","twitch" se non li gestisci

# Test network: evita di far esplodere Actions
REQUEST_TIMEOUT = 20
RANGE_BYTES = "bytes=0-4095"
SLEEP_BETWEEN_REQUESTS = 0.0  # es: 0.03 se temi rate-limit

# adult/ondemand: default pignolo (li escludiamo)
EXCLUDE_ADULT = True           # True = scarta adult True e adult "night"
EXCLUDE_ONDEMAND = False       # metti True se vuoi scartare ondemand


def slugify(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "channel"


def fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "xvb-all-bot/1.0"})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def pick_url(channel: Dict[str, Any]) -> Optional[str]:
    # Priorità: nativeHLS → url
    url = (channel.get("nativeHLS") or {}).get("url") or channel.get("url")
    if not url:
        return None

    # zappr:// fallback: usa geoblock.url se presente
    if isinstance(url, str) and url.startswith("zappr://"):
        geoblock = channel.get("geoblock")
        if isinstance(geoblock, dict) and geoblock.get("url"):
            url = geoblock["url"]
        else:
            return None

    # Proxy API (api può stare sul canale o su geoblock dict)
    api = channel.get("api")
    geoblock = channel.get("geoblock")
    if not api and isinstance(geoblock, dict):
        api = geoblock.get("api")

    if api == "cloudflare":
        url = CF_API + url
    elif api == "vercel":
        url = VERCEL_API + url

    return url


def detect_kind(url: str) -> str:
    u = url.lower()
    if ".m3u8" in u:
        return "m3u8"
    if ".mpd" in u:
        return "mpd"
    if u.endswith(".mp3") or u.endswith(".aac") or u.endswith(".ogg") or "icecast" in u:
        return "audio"
    return "other"


def quick_check(url: str) -> bool:
    """
    Controllo leggero: scarica pochi KB e valida firma manifest (m3u8/mpd).
    """
    try:
        req = Request(
            url,
            headers={
                "User-Agent": "xvb-all-bot/1.0",
                "Range": RANGE_BYTES,
            },
        )
        with urlopen(req, timeout=REQUEST_TIMEOUT) as r:
            code = getattr(r, "status", 200)
            if code not in (200, 206):
                return False
            data = r.read(4096).decode("utf-8", errors="ignore")

        kind = detect_kind(url)
        if kind == "m3u8":
            return "#EXTM3U" in data
        if kind == "mpd":
            return "<MPD" in data or "<mpd" in data
        return True

    except (HTTPError, URLError, TimeoutError):
        return False
    except Exception:
        return False


def is_skippable(channel: Dict[str, Any]) -> bool:
    t = (channel.get("type") or "").lower()
    if t in SKIP_TYPES:
        return True

    if EXCLUDE_ONDEMAND and channel.get("ondemand") is True:
        return True

    if EXCLUDE_ADULT:
        if channel.get("adult") is True:
            return True
        if channel.get("adult") == "night":
            return True

    return False


def collect_entries(sources: List[str]) -> List[Dict[str, Any]]:
    """
    Appiattisce canali + hbbtv mantenendo LCN originale:
    - padre: key (lcn, 0)
    - sub:   key (parentLcn, sublcn)
    """
    entries: List[Dict[str, Any]] = []

    for src in sources:
        data = fetch_json(src)
        for parent in data.get("channels", []):
            if not isinstance(parent, dict):
                continue
            if "categorySeparator" in parent:
                continue

            entries.append(parent)

            for sub in (parent.get("hbbtv") or []):
                if not isinstance(sub, dict):
                    continue
                if "categorySeparator" in sub:
                    continue
                sub_copy = dict(sub)
                sub_copy["parentLcn"] = parent.get("lcn")
                entries.append(sub_copy)

    return entries


def sort_key(ch: Dict[str, Any]) -> Tuple[int, int, str]:
    """
    Ordina per LCN "DTT originale":
    - usa parentLcn se sub
    - altrimenti lcn
    - sublcn dopo il padre
    """
    lcn = ch.get("parentLcn") if ch.get("parentLcn") is not None else ch.get("lcn")
    try:
        lcn_int = int(lcn)
    except Exception:
        lcn_int = 999999

    sub = ch.get("sublcn")
    try:
        sub_int = int(sub) if sub is not None else 0
    except Exception:
        sub_int = 0

    name = (ch.get("name") or "").lower()
    return (lcn_int, sub_int, name)


def main() -> None:
    lines = ["#EXTM3U", ""]
    seen_urls: Set[str] = set()

    raw_entries = collect_entries(SOURCES)
    raw_entries.sort(key=sort_key)

    ok = 0
    bad = 0

    for ch in raw_entries:
        name = ch.get("name")
        if not name:
            continue

        if is_skippable(ch):
            continue

        stream_url = pick_url(ch)
        if not stream_url:
            continue

        if stream_url in seen_urls:
            continue

        # test reale: se non passa, fuori
        if not quick_check(stream_url):
            bad += 1
            continue

        if SLEEP_BETWEEN_REQUESTS:
            time.sleep(SLEEP_BETWEEN_REQUESTS)

        seen_urls.add(stream_url)
        ok += 1

        logo = ch.get("logo")
        tvg_logo = f"{LOGO_HOST}/{logo}" if logo else None

        lcn = ch.get("parentLcn") if ch.get("parentLcn") is not None else ch.get("lcn")
        sublcn = ch.get("sublcn")

        display_name = name + (f" (S{sublcn})" if sublcn else "")
        tvg_id = f"{slugify(display_name)}.{COUNTRY_SUFFIX}"

        lcn_tag = f"[{lcn}] " if lcn is not None else ""

        attrs = [
            f'tvg-id="{tvg_id}"',
            f'tvg-name="{display_name}"',
            f'group-title="{GROUP_TITLE}"',
        ]
        if tvg_logo:
            attrs.insert(2, f'tvg-logo="{tvg_logo}"')

        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{lcn_tag}{display_name}')
        lines.append(stream_url)
        lines.append("")

    Path(OUT_FILE).write_text("\n".join(lines), encoding="utf-8")
    print(f"{OUT_FILE} generato ✅ (OK: {ok} | KO: {bad} | Tot sorgenti: {len(SOURCES)})")


if __name__ == "__main__":
    main()
