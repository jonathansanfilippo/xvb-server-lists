#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.request import Request, urlopen

# =========================
# CONFIG (DIRETTA IN CODICE)
# =========================

# Sorgenti Zappr (aggiungine quante vuoi: nazionali + regionali + ecc.)
SOURCES_TV = [
    "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/national.json",
    # esempi:
    # "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/regional/lombardia.json",
]

# Tuo mapping tvg-id (XMLTV)
EPG_XML_URL = "https://raw.githubusercontent.com/jonathansanfilippo/xvb-epg/refs/heads/main/channels/superguidatv.channels.xml"

# Output (in ROOT repo)
OUT_TV = Path("xvb-all.m3u")
OUT_RADIO = Path("xvb-radio-master.m3u")

COUNTRY = "it"

# Logo Zappr (repo logos)
# - se logo = "rai1" -> useremo WEBP optimized
# - se logo = "qualcosa.svg" -> useremo SVG optimized
ZAPPR_LOGO_BASE = f"https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/logos/{COUNTRY}/optimized"

# Se vuoi includere canali marcati "disabled": "not-working", metti False
SKIP_DISABLED = True


# =========================
# UTILS
# =========================

def _http_get(url: str, timeout: int = 30) -> bytes:
    req = Request(url, headers={"User-Agent": "xvb-master-bot/1.0"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()

def fetch_json(url: str) -> Dict[str, Any]:
    return json.loads(_http_get(url).decode("utf-8", errors="replace"))

def fetch_xml(url: str) -> ET.Element:
    raw = _http_get(url).decode("utf-8", errors="replace")
    return ET.fromstring(raw)

def norm_key(s: str) -> str:
    s = s.lower().strip()
    s = s.replace("&", " and ")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

def slugify(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text or "channel"

def build_logo_url(logo_value: Optional[str]) -> Optional[str]:
    if not logo_value:
        return None
    # schema: se SVG -> include ".svg", altrimenti NO estensione
    if logo_value.endswith(".svg"):
        return f"{ZAPPR_LOGO_BASE}/{logo_value}"
    return f"{ZAPPR_LOGO_BASE}/{logo_value}.webp"

def is_disabled(ch: Dict[str, Any]) -> bool:
    return bool(ch.get("disabled"))

def is_radio_audio(ch: Dict[str, Any]) -> bool:
    # radio: true => radio senza video
    # type: audio => radio
    radio = ch.get("radio")
    typ = ch.get("type")
    return (radio is True) or (typ == "audio")

def is_visual_radio(ch: Dict[str, Any]) -> bool:
    # radio: "video" => visual radio (teniamola nella TV)
    return ch.get("radio") == "video"

def pick_stream_url(ch: Dict[str, Any]) -> Optional[str]:
    """
    IMPORTANTISSIMO PER TE:
    - NON usiamo MAI api (cloudflare/vercel)
    - NON usiamo geoblock (né object né bool)
    - prendiamo SEMPRE e SOLO:
        nativeHLS.url (se presente) ALTRIMENTI url
    """
    native = ch.get("nativeHLS") or {}
    if isinstance(native, dict):
        u = native.get("url")
        if isinstance(u, str) and u.strip():
            return u.strip()

    u = ch.get("url")
    if isinstance(u, str) and u.strip():
        return u.strip()

    return None

def iter_channels_with_hbbtv(data: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """
    Ritorna canali principali + subcanali hbbtv (se presenti).
    Salta eventuali categorySeparator.
    """
    for parent in data.get("channels", []) or []:
        if not isinstance(parent, dict):
            continue
        if "categorySeparator" in parent:
            continue

        yield parent

        hbb = parent.get("hbbtv") or []
        if isinstance(hbb, list):
            for sub in hbb:
                if not isinstance(sub, dict):
                    continue
                if "categorySeparator" in sub:
                    continue
                sub_copy = dict(sub)
                sub_copy["parentLcn"] = parent.get("lcn")
                yield sub_copy

def safe_num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


# =========================
# TVG-ID MAPPING (dal tuo XML)
# =========================

def load_epg_mapping(root: ET.Element) -> Dict[str, str]:
    """
    Crea un mapping: chiave normalizzata del display-name -> xmltv channel id
    Esempio:
      "rai1" -> "Rai1.it"
      "canale5" -> "Canale5.it"
    """
    m: Dict[str, str] = {}

    # L'XMLTV tipico è: <tv><channel id="..."><display-name>...</display-name>...</channel>...</tv>
    for ch in root.findall(".//channel"):
        cid = ch.get("id")
        if not cid:
            continue

        # prendiamo TUTTI i display-name e creiamo più alias
        for dn in ch.findall("./display-name"):
            if dn.text and dn.text.strip():
                k = norm_key(dn.text)
                if k:
                    m[k] = cid

        # alias anche dal solo id (utile se il nome coincide)
        m[norm_key(cid)] = cid

    return m

def resolve_tvg_id(name: str, epg_map: Dict[str, str]) -> str:
    """
    Prova:
    - match per nome normalizzato
    - match per nome senza spazi/punti
    - fallback: slug + .it
    """
    k = norm_key(name)
    if k in epg_map:
        return epg_map[k]

    # fallback “aggressivo”: togliamo cose tipo "HD", "UHD", ecc.
    cleaned = re.sub(r"\b(uhd|4k|hd)\b", "", name, flags=re.IGNORECASE).strip()
    k2 = norm_key(cleaned)
    if k2 in epg_map:
        return epg_map[k2]

    return f"{slugify(name)}.{COUNTRY}"


# =========================
# GROUP-TITLE (provider)
# =========================

def group_title_for(name: str) -> str:
    n = name.lower()

    # RAI
    if n.startswith("rai ") or n.startswith("rai"):
        return "RAI"

    # MEDIASET
    mediaset_keys = ["rete 4", "canale 5", "italia 1", "italia 2", "tgcom", "mediaset", "iris", "la 5", "cine34", "focus", "top crime", "boing", "cartoonito", "twentyseven", "20 mediaset"]
    if any(k in n for k in mediaset_keys):
        return "Mediaset"

    # WBD / Discovery
    wbd_keys = ["nove", "realtime", "real time", "dmax", "hgtv", "food network", "giallo", "frisbee", "k2", "warner tv", "motor trend", "discovery"]
    if any(k in n for k in wbd_keys):
        return "Warner Bros. Discovery"

    # SKY
    sky_keys = ["tv8", "cielo", "sky tg24", "skytg24", "sky"]
    if any(k in n for k in sky_keys):
        return "Sky"

    # LA7
    if n.startswith("la7") or "la7" in n:
        return "La7"

    # ISTITUZIONI
    inst = ["senato", "camera dei deputati", "camera2", "parlamento"]
    if any(k in n for k in inst):
        return "Istituzioni"

    # RADIO/TV musicali varie (visual radio rimane TV ma raggruppata)
    if "radio" in n or "rtl" in n or "rds" in n:
        return "Radio/Visual"

    return "Altri"


# =========================
# MODEL
# =========================

@dataclass
class Entry:
    name: str
    url: str
    logo: Optional[str]
    tvg_id: str
    group: str
    lcn: Optional[float]
    sublcn: Optional[float]
    is_radio_audio: bool

def sort_key(e: Entry) -> Tuple[int, float, float, str]:
    # DTT prima: quelli con lcn (0) poi senza (1)
    has_lcn = 0 if e.lcn is not None else 1
    lcn_val = e.lcn if e.lcn is not None else 99999.0
    sub_val = e.sublcn if e.sublcn is not None else 0.0
    return (has_lcn, lcn_val, sub_val, e.name.lower())


# =========================
# BUILD
# =========================

def render_m3u(entries: List[Entry], header: str = "#EXTM3U") -> str:
    lines: List[str] = [header, ""]
    for e in entries:
        # display con [LCN] se c'è
        lcn_tag = f"[{int(e.lcn)}] " if e.lcn is not None else ""
        display = f"{lcn_tag}{e.name}"

        attrs = [
            f'tvg-name="{e.name}"',
            f'tvg-id="{e.tvg_id}"',
            f'group-title="{e.group}"',
        ]
        if e.logo:
            attrs.insert(1, f'tvg-logo="{e.logo}"')

        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{display}')
        lines.append(e.url)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

def main() -> int:
    # 1) carica mapping EPG
    try:
        epg_root = fetch_xml(EPG_XML_URL)
        epg_map = load_epg_mapping(epg_root)
    except Exception as ex:
        print(f"[WARN] Non riesco a leggere EPG XML ({EPG_XML_URL}): {ex}", file=sys.stderr)
        epg_map = {}

    tv_entries: List[Entry] = []
    radio_entries: List[Entry] = []

    # 2) fetch e flatten
    for src in SOURCES_TV:
        try:
            data = fetch_json(src)
        except Exception as ex:
            print(f"[WARN] Errore fetch JSON: {src} -> {ex}", file=sys.stderr)
            continue

        for ch in iter_channels_with_hbbtv(data):
            if SKIP_DISABLED and is_disabled(ch):
                continue

            name = ch.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            name = name.strip()

            url = pick_stream_url(ch)
            if not url:
                continue

            # radio split
            radio_audio = is_radio_audio(ch)
            if radio_audio:
                group = "Radio"
            else:
                group = group_title_for(name)

            logo_url = build_logo_url(ch.get("logo"))
            tvg_id = resolve_tvg_id(name, epg_map)

            lcn = safe_num(ch.get("parentLcn") if "parentLcn" in ch else ch.get("lcn"))
            sublcn = safe_num(ch.get("sublcn"))

            entry = Entry(
                name=name,
                url=url,
                logo=logo_url,
                tvg_id=tvg_id,
                group=group,
                lcn=lcn,
                sublcn=sublcn,
                is_radio_audio=radio_audio,
            )

            # Visual radio (radio="video") -> TV list, non radio audio
            if radio_audio:
                radio_entries.append(entry)
            else:
                tv_entries.append(entry)

    # 3) ordina
    tv_entries.sort(key=sort_key)
    radio_entries.sort(key=lambda e: (e.name.lower(), e.url))

    # 4) scrivi in ROOT repo
    OUT_TV.write_text(render_m3u(tv_entries), encoding="utf-8")
    OUT_RADIO.write_text(render_m3u(radio_entries), encoding="utf-8")

    print(f"OK ✅ {OUT_TV} generato (canali: {len(tv_entries)})")
    print(f"OK ✅ {OUT_RADIO} generato (radio: {len(radio_entries)})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
