#!/usr/bin/env python3
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen, Request
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# =======================
# CONFIG
# =======================

SOURCES = [
    "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/national.json",
    # aggiungi altre sorgenti Zappr qui:
    # "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/regional/lombardia.json",
]

# XMLTV: qui prendo gli id canale per tvg-id
EPG_CHANNELS_XML = "https://raw.githubusercontent.com/jonathansanfilippo/xvb-epg/refs/heads/main/channels/superguidatv.channels.xml"

LOGO_HOST = "https://channels.zappr.stream/logos"

OUTPUT_FILE = "xvb-all.m3u"
GROUP_DTT = "DTT"
GROUP_OTHER = "Altri"
COUNTRY_SUFFIX = "it"

UA = "xvb-all-bot/1.0"


# =======================
# Utils
# =======================

def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_json(url: str) -> dict:
    return json.loads(fetch_text(url))


def normalize_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = s.replace("\u00a0", " ")
    s = s.replace("’", "'")
    s = re.sub(r"\s+", " ", s)
    return s


def slugify(text: str) -> str:
    text = (text or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "channel"


def is_http_url(u: str) -> bool:
    return isinstance(u, str) and (u.startswith("http://") or u.startswith("https://"))


def build_logo_url(logo: Optional[str]) -> Optional[str]:
    if not logo:
        return None
    return f"{LOGO_HOST}/{logo}"


# =======================
# XMLTV mapping: display-name -> channel id
# =======================

def load_xmltv_id_map(url: str) -> Dict[str, str]:
    """
    Legge un XMLTV e crea mappa:
      normalized display-name -> channel_id (attributo id su <channel>)
    Se non riesce a parsare, ritorna {} e si va di fallback.
    """
    try:
        raw = fetch_text(url).strip()
        root = ET.fromstring(raw)

        out: Dict[str, str] = {}
        for ch in root.findall("channel"):
            cid = ch.get("id")
            if not cid:
                continue
            for dn in ch.findall("display-name"):
                name = (dn.text or "").strip()
                if not name:
                    continue
                out.setdefault(normalize_name(name), cid)
        return out
    except Exception:
        return {}


def tvg_id_for(display_name: str, xmltv_map: Dict[str, str]) -> str:
    key = normalize_name(display_name)
    if key in xmltv_map:
        return xmltv_map[key]
    # fallback “sicuro”
    return f"{slugify(display_name)}.{COUNTRY_SUFFIX}"


# =======================
# Zappr parsing
# =======================

def pick_url(ch: Dict[str, Any]) -> Optional[str]:
    """
    Priorità: nativeHLS.url -> url
    Gestione zappr:// : usa geoblock.url SOLO se geoblock è dict.
    NON usa proxy API (cloudflare/vercel) come richiesto.
    """
    url = None
    nhls = ch.get("nativeHLS")
    if isinstance(nhls, dict) and nhls.get("url"):
        url = nhls["url"]
    else:
        url = ch.get("url")

    if not isinstance(url, str) or not url:
        return None

    if url.startswith("zappr://"):
        geob = ch.get("geoblock")
        if isinstance(geob, dict) and geob.get("url"):
            url = geob["url"]
        else:
            return None

    if not is_http_url(url):
        return None

    return url


def flatten_channels(data: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """
    Yields:
      - parent channel
      - subchannels in hbbtv[] with parentLcn
    Skippa solo categorySeparator (non è un canale).
    """
    for parent in data.get("channels", []):
        if not isinstance(parent, dict):
            continue
        if "categorySeparator" in parent:
            continue

        yield parent

        subs = parent.get("hbbtv") or []
        if isinstance(subs, list):
            for sub in subs:
                if not isinstance(sub, dict):
                    continue
                if "categorySeparator" in sub:
                    continue
                sub_copy = dict(sub)
                sub_copy["parentLcn"] = parent.get("lcn")
                yield sub_copy


def lcn_value(ch: Dict[str, Any]) -> Optional[int]:
    """
    Ritorna LCN (parentLcn se sub, altrimenti lcn) se numerico.
    """
    lcn = ch.get("parentLcn") if ch.get("parentLcn") is not None else ch.get("lcn")
    if isinstance(lcn, int):
        return lcn
    # se arriva come stringa numerica
    try:
        return int(lcn)
    except Exception:
        return None


def sublcn_value(ch: Dict[str, Any]) -> int:
    sub = ch.get("sublcn")
    if isinstance(sub, int):
        return sub
    try:
        return int(sub)
    except Exception:
        return 0


def sort_key(ch: Dict[str, Any]) -> Tuple[int, int, int, str]:
    """
    Ordine:
      1) canali con LCN (bucket 0) -> lcn -> sublcn -> name
      2) canali senza LCN (bucket 1) -> name
    """
    name = (ch.get("name") or "").lower()
    lcn = lcn_value(ch)
    if lcn is None:
        return (1, 999999, 0, name)
    return (0, lcn, sublcn_value(ch), name)


# =======================
# Build playlist
# =======================

def main() -> None:
    xmltv_map = load_xmltv_id_map(EPG_CHANNELS_XML)

    entries: List[Dict[str, Any]] = []
    for src in SOURCES:
        data = fetch_json(src)
        entries.extend(list(flatten_channels(data)))

    # ordina per DTT originale + “altri in fondo”
    entries.sort(key=sort_key)

    lines: List[str] = ["#EXTM3U", ""]
    seen_urls: Set[str] = set()

    for ch in entries:
        name = ch.get("name")
        if not isinstance(name, str) or not name.strip():
            continue

        stream_url = pick_url(ch)
        if not stream_url:
            continue

        # dedup per url
        if stream_url in seen_urls:
            continue
        seen_urls.add(stream_url)

        logo = build_logo_url(ch.get("logo"))

        lcn = lcn_value(ch)
        sublcn = ch.get("sublcn")

        display_name = name.strip()
        if sublcn is not None:
            # visuale chiaro per subcanali
            try:
                display_name = f"{display_name} (S{int(sublcn)})"
            except Exception:
                display_name = f"{display_name} (S{sublcn})"

        tvg_id = tvg_id_for(name.strip(), xmltv_map)

        group = GROUP_DTT if lcn is not None else GROUP_OTHER
        lcn_tag = f"[{lcn}] " if lcn is not None else ""

        attrs = [
            f'tvg-id="{tvg_id}"',
            f'tvg-name="{display_name}"',
            f'group-title="{group}"',
        ]
        if logo:
            attrs.insert(2, f'tvg-logo="{logo}"')

        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{lcn_tag}{display_name}')
        lines.append(stream_url)
        lines.append("")

    Path(OUTPUT_FILE).write_text("\n".join(lines), encoding="utf-8")
    print(f"{OUTPUT_FILE} generato ✅  (canali: {len(seen_urls)})")


if __name__ == "__main__":
    main()
