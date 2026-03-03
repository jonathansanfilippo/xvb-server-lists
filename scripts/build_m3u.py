#!/usr/bin/env python3
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, Iterable, List, Optional, Tuple
from urllib.request import Request, urlopen


# =========================
# CONFIG (hardcoded)
# =========================
SOURCES = [
    "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/national.json",
    # aggiungi altre fonti se vuoi (regional, radio, ecc)
]

EPG_XML_URL = "https://raw.githubusercontent.com/jonathansanfilippo/xvb-epg/refs/heads/main/channels/superguidatv.channels.xml"

# Output ROOT del repo (come nel tuo tree)
OUT_TV = Path("xvb-all.m3u")
OUT_RADIO = Path("xvb-radio-master.m3u")

# Logo: uso Zappr (poi se vuoi li punti ai tuoi loghi/naz)
ZAPPR_LOGO_HOST = "https://channels.zappr.stream/logos"

UA = "xvb-master-bot/1.0"


# =========================
# HELPERS
# =========================
def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_json(url: str) -> Dict[str, Any]:
    return json.loads(fetch_text(url))


def normalize_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)

    # normalizzazioni utili per match con XMLTV
    s = s.replace("tgcom 24", "tgcom24")
    s = s.replace("tv 2000", "tv2000")
    s = s.replace("twenty seven", "twentyseven")
    s = s.replace("rai yo yo", "rai yoyo")
    s = s.replace("rtl 102.5", "rtl102.5")
    s = s.replace("rtl1025", "rtl 102.5")  # aiuta in alcuni casi

    # togli roba extra che a volte cambia
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def slugify(text: str) -> str:
    text = (text or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "channel"


def load_epg_id_map(xml_url: str) -> Dict[str, str]:
    """
    Mappa: normalized display-name -> channel id (xmltv)
    XMLTV tipico:
      <channel id="Rai1.it"><display-name>Rai 1</display-name>...</channel>
    """
    xml = fetch_text(xml_url)
    root = ET.fromstring(xml)

    m: Dict[str, str] = {}
    for ch in root.findall("channel"):
        cid = ch.get("id")
        if not cid:
            continue

        # prendi tutti i display-name
        dns = ch.findall("display-name")
        for dn in dns:
            name = (dn.text or "").strip()
            if not name:
                continue
            m[normalize_name(name)] = cid

    return m


def is_radio_channel(ch: Dict[str, Any]) -> bool:
    """
    Heuristica:
    - se nel JSON c'è type/category che contiene 'radio'
    - oppure il nome contiene 'radio'
    - oppure url sembra audio (aac/mp3/ogg) (non sempre vero, ma aiuta)
    """
    name = (ch.get("name") or "").lower()

    # campi possibili nei vari json
    ctype = str(ch.get("type") or "").lower()
    category = str(ch.get("category") or "").lower()
    tags = " ".join([str(x).lower() for x in (ch.get("tags") or []) if isinstance(x, (str, int))])

    if "radio" in name:
        return True
    if "radio" in ctype or "radio" in category or "radio" in tags:
        return True

    url = pick_url(ch)
    if url:
        if re.search(r"\.(mp3|aac|ogg)(\?|$)", url.lower()):
            return True

    return False


def flatten_channels(data: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for parent in data.get("channels", []):
        if not isinstance(parent, dict):
            continue
        if "categorySeparator" in parent:
            continue

        yield parent

        # includi anche subchannels hbbtv
        for sub in (parent.get("hbbtv") or []):
            if not isinstance(sub, dict):
                continue
            if "categorySeparator" in sub:
                continue
            sub_copy = dict(sub)
            sub_copy["parentLcn"] = parent.get("lcn")
            yield sub_copy


def pick_url(channel: Dict[str, Any]) -> Optional[str]:
    """
    NIENTE API davanti.
    Geoblock ignorato.
    Ma se url è zappr:// allora serve un vero URL (spesso in geoblock.url).
    """
    url = (channel.get("nativeHLS") or {}).get("url") or channel.get("url")
    if not url:
        return None

    # se è zappr://, prova a risolvere con geoblock.url se è un dict
    if isinstance(url, str) and url.startswith("zappr://"):
        geoblock = channel.get("geoblock")
        if isinstance(geoblock, dict) and geoblock.get("url"):
            url = geoblock.get("url")
        else:
            return None

    if not isinstance(url, str):
        return None

    return url.strip() or None


def get_logo(channel: Dict[str, Any]) -> Optional[str]:
    logo = channel.get("logo")
    if isinstance(logo, str) and logo.strip():
        return f"{ZAPPR_LOGO_HOST}/{logo.strip()}"
    return None


def group_title_for(name: str) -> str:
    """
    Ti preparo gruppi comodi per lavorarci dopo.
    """
    n = normalize_name(name)

    # RAI
    if n.startswith("rai "):
        return "RAI"

    # Mediaset
    mediaset_keys = [
        "rete 4", "canale 5", "italia 1", "italia 2", "tgcom24",
        "mediaset", "iris", "la 5", "cine34", "focus", "top crime",
        "twentyseven", "boing", "cartoonito", "radio 105", "r101",
        "virgin radio", "radio montecarlo",
    ]
    if any(k in n for k in mediaset_keys):
        return "MEDIASET"

    # Sky / NBCU
    sky_keys = ["tv8", "cielo", "sky "]
    if any(k in n for k in sky_keys):
        return "SKY"

    # Warner Bros Discovery (in Italia include Nove/Real Time/DMAX ecc)
    wbd_keys = [
        "nove", "real time", "dmax", "hgtv", "food network",
        "giallo", "frisbee", "k2", "warner tv", "motor trend", "discovery",
    ]
    if any(k in n for k in wbd_keys):
        return "WBD"

    # La7 (Cairo)
    if n.startswith("la7"):
        return "LA7"

    # istituzionali
    if "senato" in n or "camera dei deputati" in n:
        return "ISTITUZIONI"

    # default
    return "ALTRI"


def lcn_sort_key(ch: Dict[str, Any]) -> Tuple[int, int, str]:
    """
    Ordine DTT:
    - prima chi ha lcn/parentLcn, in ordine numerico
    - poi sublcn
    - poi nome
    """
    lcn = ch.get("parentLcn") if ch.get("parentLcn") is not None else ch.get("lcn")
    sub = ch.get("sublcn")

    def to_int(x) -> Optional[int]:
        if isinstance(x, bool) or x is None:
            return None
        if isinstance(x, int):
            return x
        if isinstance(x, str) and x.strip().isdigit():
            return int(x.strip())
        return None

    lcn_i = to_int(lcn)
    sub_i = to_int(sub) or 0
    name = (ch.get("name") or "").strip()

    # chi non ha lcn va in fondo
    if lcn_i is None:
        return (10**9, 10**9, normalize_name(name))

    return (lcn_i, sub_i, normalize_name(name))


def format_display_name(ch: Dict[str, Any]) -> str:
    name = (ch.get("name") or "").strip()
    sublcn = ch.get("sublcn")
    if sublcn is not None and str(sublcn).strip() != "":
        return f"{name} (S{sublcn})"
    return name


def format_lcn_prefix(ch: Dict[str, Any]) -> str:
    lcn = ch.get("parentLcn") if ch.get("parentLcn") is not None else ch.get("lcn")
    if lcn is None:
        return ""
    return f"[{lcn}] "


def resolve_tvg_id(epg_map: Dict[str, str], ch: Dict[str, Any]) -> str:
    """
    1) match su display-name (normalizzato) verso XMLTV
    2) fallback su xmltv_id / epg.id se esiste
    3) fallback slug.it
    """
    display = format_display_name(ch)
    key = normalize_name(display)
    if key in epg_map:
        return epg_map[key]

    # prova anche sul name puro
    key2 = normalize_name((ch.get("name") or ""))
    if key2 in epg_map:
        return epg_map[key2]

    # fallback eventuali campi
    for k in ("xmltv_id", "xmltvId", "epg_id", "epgId"):
        v = ch.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    epg = ch.get("epg")
    if isinstance(epg, dict):
        eid = epg.get("id") or epg.get("xmltv")
        if isinstance(eid, str) and eid.strip():
            return eid.strip()

    return f"{slugify(display)}.it"


def build_m3u_lines(channels: List[Dict[str, Any]], epg_map: Dict[str, str], force_group: Optional[str] = None) -> List[str]:
    lines: List[str] = ["#EXTM3U", ""]

    for ch in channels:
        name = (ch.get("name") or "").strip()
        if not name:
            continue

        url = pick_url(ch)
        if not url:
            continue

        display = format_display_name(ch)
        lcn_prefix = format_lcn_prefix(ch)

        tvg_id = resolve_tvg_id(epg_map, ch)
        tvg_logo = get_logo(ch)

        group = force_group if force_group else group_title_for(name)

        attrs = [
            f'tvg-name="{display}"',
            f'tvg-id="{tvg_id}"',
            f'group-title="{group}"',
        ]
        if tvg_logo:
            attrs.insert(1, f'tvg-logo="{tvg_logo}"')

        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{lcn_prefix}{display}')
        lines.append(url)
        lines.append("")

    return lines


# =========================
# MAIN
# =========================
def main():
    epg_map = load_epg_id_map(EPG_XML_URL)

    all_ch: List[Dict[str, Any]] = []
    for src in SOURCES:
        data = fetch_json(src)
        for ch in flatten_channels(data):
            if not isinstance(ch, dict):
                continue
            all_ch.append(ch)

    # separa radio vs tv
    tv_list: List[Dict[str, Any]] = []
    radio_list: List[Dict[str, Any]] = []
    for ch in all_ch:
        if is_radio_channel(ch):
            radio_list.append(ch)
        else:
            tv_list.append(ch)

    # sort DTT: lcn prima, poi gli altri
    tv_list.sort(key=lcn_sort_key)

    # Per radio ordino alfabetico
    radio_list.sort(key=lambda c: normalize_name(c.get("name") or ""))

    # scrivi in ROOT repo
    OUT_TV.write_text("\n".join(build_m3u_lines(tv_list, epg_map)), encoding="utf-8")
    OUT_RADIO.write_text("\n".join(build_m3u_lines(radio_list, epg_map, force_group="RADIO")), encoding="utf-8")

    print(f"{OUT_TV} generato ✅  (canali: {len(tv_list)})")
    print(f"{OUT_RADIO} generato ✅  (radio: {len(radio_list)})")


if __name__ == "__main__":
    main()
