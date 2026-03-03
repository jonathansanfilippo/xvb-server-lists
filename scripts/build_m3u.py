#!/usr/bin/env python3
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
