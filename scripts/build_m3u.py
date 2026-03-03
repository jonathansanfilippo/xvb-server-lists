#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen, Request

# =========================
# CONFIG
# =========================

# Sorgenti Zappr (aggiungine quante vuoi)
SOURCES = [
    "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/national.json",
    # esempi:
    # "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/regional/lombardia.json",
]

# EPG XML: tvg-id DEVE essere l'xmltv id di questo file
EPG_XML_URL = "https://raw.githubusercontent.com/jonathansanfilippo/xvb-epg/refs/heads/main/channels/superguidatv.channels.xml"

# Output nella ROOT del repo (come la tua tree)
OUT_TV = Path("xvb-all.m3u")
OUT_RADIO = Path("xvb-radio-master.m3u")

# Logos Zappr (optimized): per PNG/WEBP in JSON non c’è estensione -> qui usiamo WEBP
LOGO_BASE = "https://channels.zappr.stream/logos/it/optimized"

# Ordine “pignolo” (prima questi, ESATTAMENTE in quest’ordine)
CANALI_ORDER = [
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
    "Senato TV", "Camera dei Deputati Ⓢ"
]

# Override mirati (quando nome Zappr ≠ nome EPG / o vuoi forzare)
# chiave = nome canale (come lo vedi nella playlist), valore = xmltv id
# (lascio vuoto: riempi se vedi mismatch)
TVGID_OVERRIDES = {
    # "LA7": "La7.it",
}

UA = "xvb-b-bot/2.0"

# =========================
# HELPERS
# =========================

def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", errors="replace")

def fetch_json(url: str) -> dict:
    return json.loads(fetch_text(url))

def normalize_name(s: str) -> str:
    s = s.strip()
    s = s.replace("Ⓢ", "s")
    s = s.replace("&", " and ")
    s = s.replace("’", "'").replace("`", "'")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    # togli punteggiatura “aggressiva”, ma tieni numeri/lettere
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def parse_epg_map(xml_text: str) -> dict:
    """
    Ritorna: normalized_display_name -> xmltv_id (attributo id= del tag <channel>)
    """
    root = ET.fromstring(xml_text)
    m = {}
    for ch in root.findall(".//channel"):
        cid = ch.get("id")
        if not cid:
            continue
        # può avere più display-name
        for dn in ch.findall("display-name"):
            if dn.text:
                m[normalize_name(dn.text)] = cid
    return m

def best_tvg_id(display_name: str, epg_map: dict) -> str | None:
    if display_name in TVGID_OVERRIDES:
        return TVGID_OVERRIDES[display_name]

    key = normalize_name(display_name)
    if key in epg_map:
        return epg_map[key]

    # tentativi “furbi”
    # 1) togli "tv" finale
    key2 = normalize_name(re.sub(r"\btv\b", "", display_name, flags=re.I))
    if key2 in epg_map:
        return epg_map[key2]

    # 2) togli "visual radio" ecc.
    key3 = normalize_name(re.sub(r"\bvisual\b|\bradio\b", "", display_name, flags=re.I))
    if key3 in epg_map:
        return epg_map[key3]

    return None

def logo_url(logo_field: str | None) -> str | None:
    if not logo_field:
        return None
    # se è svg dichiarato
    if logo_field.endswith(".svg"):
        return f"{LOGO_BASE}/{logo_field}"
    # altrimenti Zappr richiede NO estensione nel json -> usiamo webp (optimized)
    return f"{LOGO_BASE}/{logo_field}.webp"

def is_radio_channel(ch: dict) -> bool:
    # schema: radio: true | "video" | false
    radio = ch.get("radio")
    if radio is True or radio == "video":
        return True
    # oppure type audio
    if (ch.get("type") or "").lower() == "audio":
        return True
    return False

def pick_stream_url(ch: dict) -> str | None:
    # Priorità: nativeHLS.url → url (NO proxy API davanti)
    native = ch.get("nativeHLS") or {}
    if isinstance(native, dict) and native.get("url"):
        url = native.get("url")
    else:
        url = ch.get("url")

    if not url:
        return None

    # zappr:// non è stream: prova a usare geoblock.url se c'è (solo se è dict)
    if isinstance(url, str) and url.startswith("zappr://"):
        geob = ch.get("geoblock")
        if isinstance(geob, dict) and geob.get("url"):
            url = geob["url"]
        else:
            return None

    return url

def group_title_for(name: str, radio: bool) -> str:
    if radio:
        return "Radio"

    n = normalize_name(name)

    if n.startswith("rai " ) or n.startswith("raiplay") or n.startswith("rai"):
        return "RAI"
    if "mediaset" in n or n.startswith("rete ") or n.startswith("canale ") or n.startswith("italia ") or "tgcom" in n or "cine34" in n:
        return "Mediaset"
    if n.startswith("la7"):
        return "La7"
    if n.startswith("sky") or n.startswith("tv8") or "cielo" in n:
        return "Sky"
    if "dmax" in n or "hgtv" in n or "realtime" in n or "food network" in n or "warner" in n or "discovery" in n or "giallo" in n or "frisbee" in n or "k2" in n:
        return "Warner-Discovery"
    return "Altri"

def extinf_line(name: str, tvg_id: str | None, tvg_logo: str | None, group_title: str, lcn: int | None) -> str:
    attrs = [f'tvg-name="{name}"', f'group-title="{group_title}"']
    if tvg_logo:
        attrs.insert(1, f'tvg-logo="{tvg_logo}"')
    if tvg_id:
        # tvg-id = xmltv id (come vuoi tu)
        attrs.insert(0, f'tvg-id="{tvg_id}"')

    prefix = f"[{lcn}] " if isinstance(lcn, int) else ""
    return f'#EXTINF:-1 {" ".join(attrs)},{prefix}{name}'

def lcn_int(v) -> int | None:
    try:
        if v is None:
            return None
        # in json è "number" => può arrivare come int/float
        x = int(v)
        return x
    except Exception:
        return None

def order_key(name: str, lcn: int | None) -> tuple:
    """
    Prima: se name è nella CANALI_ORDER -> (0, index, lcn_sort, name)
    Poi: se ha LCN -> (1, 999999, lcn, name)
    Infine: no LCN -> (2, 999999, 999999, name)
    """
    try:
        idx = CANALI_ORDER.index(name)
        return (0, idx, lcn if lcn is not None else 999999, normalize_name(name))
    except ValueError:
        pass

    if lcn is not None:
        return (1, 999999, lcn, normalize_name(name))
    return (2, 999999, 999999, normalize_name(name))

def flatten_channels(data: dict):
    """
    include anche sub-canali hbbtv (se presenti).
    """
    for parent in data.get("channels", []) or []:
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

def build_entries(epg_map: dict):
    tv_entries = []
    radio_entries = []

    for source in SOURCES:
        data = fetch_json(source)

        for ch in flatten_channels(data):
            name = ch.get("name")
            if not name:
                continue

            url = pick_stream_url(ch)
            if not url:
                continue

            lcn = lcn_int(ch.get("parentLcn") or ch.get("lcn"))

            radio = is_radio_channel(ch)
            group = group_title_for(name, radio)

            tvg_logo = logo_url(ch.get("logo"))
            tvg_id = best_tvg_id(name, epg_map)

            license_type = (ch.get("license") or "").lower().strip()
            license_details = (ch.get("licensedetails") or "").strip()

            entry = {
                "name": name,
                "url": url,
                "lcn": lcn,
                "group": group,
                "tvg_logo": tvg_logo,
                "tvg_id": tvg_id,
                "license": license_type,
                "licensedetails": license_details,
                "type": (ch.get("type") or "").lower().strip(),
            }

            if radio:
                radio_entries.append(entry)
            else:
                tv_entries.append(entry)

    # sort
    tv_entries.sort(key=lambda e: order_key(e["name"], e["lcn"]))
    radio_entries.sort(key=lambda e: (normalize_name(e["name"])))

    return tv_entries, radio_entries

def write_m3u(path: Path, entries: list[dict]):
    lines = ["#EXTM3U", ""]

    for e in entries:
        lines.append(extinf_line(
            name=e["name"],
            tvg_id=e["tvg_id"],
            tvg_logo=e["tvg_logo"],
            group_title=e["group"],
            lcn=e["lcn"],
        ))

        # ClearKey (DASH) -> scrivi KODIPROP prima dell'url
        if e["license"] == "clearkey" and e["licensedetails"]:
            # per sicurezza: solo se sembra "kid:key"
            if ":" in e["licensedetails"] and re.fullmatch(r"[0-9a-fA-F]+:[0-9a-fA-F]+", e["licensedetails"]):
                lines.append("#KODIPROP:inputstream.adaptive.manifest_type=mpd")
                lines.append("#KODIPROP:inputstream.adaptive.license_type=org.w3.clearkey")
                lines.append(f"#KODIPROP:inputstream.adaptive.license_key={e['licensedetails']}")

        lines.append(e["url"])
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")

def main():
    # EPG map
    epg_xml = fetch_text(EPG_XML_URL)
    epg_map = parse_epg_map(epg_xml)

    tv_entries, radio_entries = build_entries(epg_map)

    write_m3u(OUT_TV, tv_entries)
    write_m3u(OUT_RADIO, radio_entries)

    print(f"{OUT_TV} generato ✅  (tv: {len(tv_entries)})")
    print(f"{OUT_RADIO} generato ✅  (radio: {len(radio_entries)})")

if __name__ == "__main__":
    main()
