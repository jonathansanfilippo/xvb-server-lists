#!/usr/bin/env python3
import json
import re
import xml.etree.ElementTree as ET
from urllib.request import urlopen, Request
from pathlib import Path
from typing import Dict, Any, Iterable, List, Tuple, Optional

# =========================
# CONFIG
# =========================
SOURCES = [
    "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/national.json",
    # aggiungi altre fonti se vuoi:
    # "https://raw.githubusercontent.com/ZapprTV/channels/refs/heads/main/it/dtt/regional/lombardia.json",
]

LOGO_HOST = "https://channels.zappr.stream/logos"

OUT_TV = "xvb-master.m3u"
OUT_RADIO = "xvb-radio-master.m3u"

COUNTRY_SUFFIX = "it"
UA = "xvb-master-bot/1.0"

# mapping EPG (tvg-id) dalla tua repo
EPG_MAP_URL = "https://raw.githubusercontent.com/jonathansanfilippo/xvb-epg/refs/heads/main/channels/superguidatv.channels.xml"


# =========================
# UTILS
# =========================
def slugify(text: str) -> str:
    text = (text or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "channel"


def normalize_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_json(url: str) -> Dict[str, Any]:
    return json.loads(fetch_text(url))


def is_http_url(u: str) -> bool:
    return isinstance(u, str) and (u.startswith("http://") or u.startswith("https://"))


def build_logo_url(logo_value: Optional[str]) -> Optional[str]:
    if not logo_value:
        return None
    return f"{LOGO_HOST}/{logo_value}"


# =========================
# EPG MAP (xmltv)
# =========================
def load_xmltv_id_map(url: str) -> Dict[str, str]:
    """
    Prova a costruire {normalized_display_name: xmltv_channel_id}
    da un XMLTV tipo:
      <channel id="Rai1.it"><display-name>Rai 1</display-name>...
    """
    txt = fetch_text(url).strip()
    if "<channel" not in txt or "display-name" not in txt:
        return {}

    try:
        root = ET.fromstring(txt)
    except Exception:
        return {}

    m: Dict[str, str] = {}
    for ch in root.findall(".//channel"):
        cid = ch.get("id")
        if not cid:
            continue
        for dn in ch.findall("./display-name"):
            if dn.text:
                key = normalize_name(dn.text)
                if key and key not in m:
                    m[key] = cid
    return m


def tvg_id_for_channel(display_name: str, ch: Dict[str, Any], epg_map: Dict[str, str]) -> str:
    # 1) tuo xmltv map (match su nome)
    k = normalize_name(display_name)
    if k in epg_map:
        return epg_map[k]

    # 2) epg.id del JSON (se presente)
    epg = ch.get("epg") or {}
    if isinstance(epg, dict) and epg.get("id"):
        eid = str(epg["id"]).strip()
        if eid.isdigit():
            return eid
        return f"{eid}.{COUNTRY_SUFFIX}"

    # 3) fallback slug
    return f"{slugify(display_name)}.{COUNTRY_SUFFIX}"


# =========================
# CHANNEL FLATTEN / URL PICK
# =========================
def flatten_channels(data: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """
    include anche subcanali hbbtv
    salta categorySeparator
    """
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


def pick_stream_url(ch: Dict[str, Any]) -> Optional[str]:
    """
    Priorità: nativeHLS.url -> url
    Risolve zappr:// usando geoblock.url (se disponibile)
    NON mette nessuna API davanti (richiesta tua)
    """
    url = (ch.get("nativeHLS") or {}).get("url") or ch.get("url")
    if not url or not isinstance(url, str):
        return None

    if url.startswith("zappr://"):
        gb = ch.get("geoblock")
        if isinstance(gb, dict) and is_http_url(gb.get("url")):
            url = gb["url"]
        else:
            return None

    if not is_http_url(url):
        return None

    return url


# =========================
# CLASSIFY TV vs RADIO + GROUPS
# =========================
AUDIO_HINTS = (
    "icecast",
    ".mp3",
    ".aac",
    ".ogg",
    "stream.mp3",
    "stream.aac",
)

def is_radio_audio(ch: Dict[str, Any], url: str) -> bool:
    """
    Radio “vera” (solo audio).
    Se è una visual radio (video/hls/mpd) resta in TV.
    """
    ctype = (ch.get("type") or "").lower()

    # se esplicito audio => radio
    if ctype == "audio":
        return True

    # alcuni hanno flag radio: true ma restano stream video (visual radio) -> NON basta
    # guardiamo l'URL per capire se è audio
    u = url.lower()
    if any(h in u for h in AUDIO_HINTS):
        return True

    return False


# set veloci per Mediaset / WBD quando il nome è ambiguo
MEDIASET_NAMES = {
    "rete 4", "canale 5", "italia 1", "20 mediaset", "iris", "cine34", "focus",
    "top crime", "boing", "cartoonito", "tgcom 24", "tgcom24", "mediaset extra",
    "italia 2", "la 5", "la5", "twentyseven"
}

WBD_NAMES = {
    "nove", "real time", "dmax", "hgtv", "discovery", "giallo", "k2", "frisbee",
    "food network", "warner tv", "motor trend", "discovery turbo"
}

SKY_NAMES = {"tv8", "cielo", "sky tg24", "skytg24"}

def group_title_tv(ch: Dict[str, Any], url: str) -> str:
    name = normalize_name(ch.get("name") or "")
    u = (url or "").lower()

    epg = ch.get("epg") or {}
    epg_source = (epg.get("source") if isinstance(epg, dict) else "") or ""
    epg_source = str(epg_source).lower()

    manual = ch.get("manualRestart") or {}
    mr_source = (manual.get("source") if isinstance(manual, dict) else "") or ""
    mr_source = str(mr_source).lower()

    # RAI
    if name.startswith("rai ") or " raiplay" in epg_source or epg_source in {"raiplay", "raiplaysound"}:
        return "RAI"

    # Mediaset
    if "mediaset.net" in u or mr_source == "mediaset" or name in MEDIASET_NAMES:
        return "Mediaset"

    # Sky
    if "skycdn" in u or name in SKY_NAMES or (isinstance(ch.get("url"), str) and ch["url"].startswith("zappr://sky/")):
        return "Sky"

    # LA7
    if name.startswith("la7") or "la7" in name or "cloudfront.net/la7" in u or mr_source == "la7":
        return "LA7"

    # WBD / Discovery
    if mr_source == "wbd" or name in WBD_NAMES:
        return "Warner Bros. Discovery"

    return "Altri"


def group_title_radio(ch: Dict[str, Any], url: str) -> str:
    name = normalize_name(ch.get("name") or "")
    u = (url or "").lower()

    if name.startswith("rai radio") or "raiplaysound" in (str((ch.get("epg") or {}).get("source") or "")).lower():
        return "RAI Radio"
    if "rtl" in name:
        return "RTL"
    if "rds" in name:
        return "RDS"
    if "deejay" in name or "m2o" in name or "capital" in name:
        return "GEDI"
    if "radioitalia" in name:
        return "Radio Italia"
    if "virgin" in name or "105" in name or "r101" in name or "monte carlo" in name:
        return "Radio Mediaset"
    if "vatican" in u or "vatican" in name or "radio vaticana" in name:
        return "Vaticano"
    return "Altre Radio"


# =========================
# SORTING
# =========================
def get_lcn(ch: Dict[str, Any]) -> Optional[int]:
    lcn = ch.get("parentLcn")
    if lcn is None:
        lcn = ch.get("lcn")
    return lcn if isinstance(lcn, int) else None


def get_sublcn(ch: Dict[str, Any]) -> int:
    return ch.get("sublcn") if isinstance(ch.get("sublcn"), int) else 0


def sort_key_tv(ch: Dict[str, Any]) -> Tuple[int, int, int, str]:
    """
    TV:
    - prima canali con LCN (0), poi il resto (1)
    - LCN: lcn asc, sublcn asc
    - poi nome
    """
    lcn = get_lcn(ch)
    name = normalize_name(ch.get("name") or "")
    if lcn is not None:
        return (0, lcn, get_sublcn(ch), name)
    return (1, 999999, 999999, name)


def sort_key_radio(ch: Dict[str, Any]) -> Tuple[str, str]:
    return (normalize_name(ch.get("name") or ""), normalize_name(str(ch.get("url") or "")))


# =========================
# BUILD M3U
# =========================
def extinf_line(display_name: str, tvg_id: str, tvg_logo: Optional[str], group: str, lcn: Optional[int]) -> str:
    lcn_tag = f"[{lcn}] " if isinstance(lcn, int) else ""
    attrs = [
        f'tvg-name="{display_name}"',
        f'tvg-id="{tvg_id}"',
        f'group-title="{group}"',
    ]
    if tvg_logo:
        attrs.insert(1, f'tvg-logo="{tvg_logo}"')
    return f'#EXTINF:-1 {" ".join(attrs)},{lcn_tag}{display_name}'


def main():
    # carico mapping xmltv-id tuo (best-effort)
    try:
        epg_map = load_xmltv_id_map(EPG_MAP_URL)
    except Exception:
        epg_map = {}

    tv_items: List[Tuple[Dict[str, Any], str]] = []
    radio_items: List[Tuple[Dict[str, Any], str]] = []

    # fetch + collect
    for src in SOURCES:
        data = fetch_json(src)
        for ch in flatten_channels(data):
            name = ch.get("name")
            if not name:
                continue

            url = pick_stream_url(ch)
            if not url:
                continue

            if is_radio_audio(ch, url):
                radio_items.append((ch, url))
            else:
                tv_items.append((ch, url))

    # sort
    tv_items.sort(key=lambda t: sort_key_tv(t[0]))
    radio_items.sort(key=lambda t: sort_key_radio(t[0]))

    # write TV
    tv_lines: List[str] = ["#EXTM3U", ""]
    for ch, url in tv_items:
        name = ch.get("name") or ""
        sublcn = ch.get("sublcn")
        display_name = name + (f" (S{sublcn})" if isinstance(sublcn, int) else "")

        tvg_logo = build_logo_url(ch.get("logo"))
        tvg_id = tvg_id_for_channel(display_name, ch, epg_map)
        group = group_title_tv(ch, url)
        lcn = get_lcn(ch)

        tv_lines.append(extinf_line(display_name, tvg_id, tvg_logo, group, lcn))
        tv_lines.append(url)
        tv_lines.append("")

    Path(OUT_TV).write_text("\n".join(tv_lines), encoding="utf-8")

    # write RADIO
    r_lines: List[str] = ["#EXTM3U", ""]
    for ch, url in radio_items:
        display_name = ch.get("name") or ""

        tvg_logo = build_logo_url(ch.get("logo"))
        tvg_id = tvg_id_for_channel(display_name, ch, epg_map)  # anche per radio va bene
        group = group_title_radio(ch, url)

        r_lines.append(extinf_line(display_name, tvg_id, tvg_logo, group, None))
        r_lines.append(url)
        r_lines.append("")

    Path(OUT_RADIO).write_text("\n".join(r_lines), encoding="utf-8")

    print(f"{OUT_TV} ✅  (TV: {len(tv_items)})")
    print(f"{OUT_RADIO} ✅  (Radio: {len(radio_items)})")


if __name__ == "__main__":
    main()
