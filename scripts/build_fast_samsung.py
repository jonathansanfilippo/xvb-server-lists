#!/usr/bin/env python3
import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import unquote

# === CONFIG ===
COUNTRY = "it"
OUTFILE = Path("xvb-fast-samsung.m3u")

# Source: lista canali Samsung TV Plus (gz JSON) usata comunemente
SAMSUNG_LIST_GZ = "https://i.mjh.nz/SamsungTVPlus/all.json.gz"

# Redirect service -> ti dà la m3u8 finale in Location header
JMP2 = "https://jmp2.uk/stvp-"

GROUP_TITLE = "FAST • Samsung TV Plus"


@dataclass
class Channel:
    name: str
    lcn: int | None
    url: str
    logo: str | None
    tvg_id: str | None


def http_get_bytes(url: str, ua: str = "xvb-fast-bot/1.0") -> bytes:
    req = Request(url, headers={"User-Agent": ua})
    with urlopen(req, timeout=45) as r:
        return r.read()


def resolve_redirect(url: str, ua: str = "xvb-fast-bot/1.0") -> str | None:
    """
    Fa una GET ma NON segue redirect automaticamente: in urllib è difficile.
    Trucco: apriamo e prendiamo r.url SOLO se il server ha già fatto redirect lato CDN.
    In pratica jmp2.uk risponde 302 e urllib segue: quindi r.url diventa la finale.
    """
    try:
        req = Request(url, headers={"User-Agent": ua})
        with urlopen(req, timeout=45) as r:
            final_url = r.url
            if final_url and final_url != url:
                return final_url
            # se non è cambiato, a volte è già la playlist
            return final_url
    except Exception:
        return None


def normalize_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    return name


def parse_channels() -> list[Channel]:
    raw_gz = http_get_bytes(SAMSUNG_LIST_GZ)
    data = json.loads(gzip.decompress(raw_gz).decode("utf-8", "replace"))

    out: list[Channel] = []

    # La struttura di all.json.gz è: { "countries": { "it": { "channels": {...}}}}
    countries = data.get("countries") or {}
    it = countries.get(COUNTRY) or {}
    channels = it.get("channels") or {}

    for ch_id, ch in channels.items():
        # Skip DRM (se presente)
        if ch.get("license_url"):
            continue

        name = normalize_name(ch.get("name") or ch_id)
        lcn = ch.get("lcn")
        try:
            lcn = int(lcn) if lcn is not None else None
        except Exception:
            lcn = None

        # Logo
        logo = ch.get("logo") or ch.get("logo_url")

        # tvg-id: per FAST non hai la tua EPG, quindi almeno ID stabile
        tvg_id = f"SamsungTVPlus.{ch_id}.it"

        # URL finale (redirect -> m3u8)
        final = resolve_redirect(JMP2 + ch_id)
        if not final:
            continue

        out.append(Channel(name=name, lcn=lcn, url=final, logo=logo, tvg_id=tvg_id))

    # Ordina: prima quelli con LCN, poi il resto
    out.sort(key=lambda x: (x.lcn is None, x.lcn if x.lcn is not None else 999999, x.name.lower()))
    return out


def build_m3u(channels: list[Channel]) -> str:
    lines = ["#EXTM3U", ""]
    for ch in channels:
        lcn_tag = f"[{ch.lcn}] " if ch.lcn is not None else ""
        attrs = [
            f'tvg-name="{ch.name}"',
            f'tvg-id="{ch.tvg_id}"' if ch.tvg_id else None,
            f'tvg-logo="{ch.logo}"' if ch.logo else None,
            f'group-title="{GROUP_TITLE}"',
        ]
        attrs = [a for a in attrs if a]
        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{lcn_tag}{ch.name}')
        lines.append(ch.url)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    channels = parse_channels()
    OUTFILE.write_text(build_m3u(channels), encoding="utf-8")
    print(f"{OUTFILE} generato: {len(channels)} canali ✅")


if __name__ == "__main__":
    main()
