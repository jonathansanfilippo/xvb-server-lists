#!/usr/bin/env python3
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode

# === CONFIG ===
COUNTRY = "IT"
LANGUAGE = "it"
OUTFILE = Path("xvb-fast-pluto.m3u")
GROUP_TITLE = "FAST • Pluto TV"

# Elenco canali (metadata)
PLUTO_CHANNELS_API = "https://api.pluto.tv/v2/channels"

# Stitch HLS host (molto usato negli m3u pubblici)
STITCH_HOST = "http://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv/stitch/hls/channel/"


@dataclass
class Channel:
    name: str
    url: str
    logo: str | None
    tvg_id: str | None


def http_get_json(url: str, ua: str = "xvb-fast-bot/1.0") -> object:
    req = Request(url, headers={"User-Agent": ua})
    with urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def build_stitched_url(channel_id: str, device_id: str, sid: str) -> str:
    params = {
        "appName": "web",
        "appVersion": "unknown",
        "clientTime": "0",
        "deviceDNT": "0",
        "deviceId": device_id,
        "deviceMake": "Chrome",
        "deviceModel": "web",
        "deviceType": "web",
        "deviceVersion": "unknown",
        "includeExtendedEvents": "false",
        "serverSideAds": "false",
        "sid": sid,
    }
    return f"{STITCH_HOST}{channel_id}/master.m3u8?{urlencode(params)}"


def parse_channels() -> list[Channel]:
    # device identifiers (stabili dentro la run)
    device_id = str(uuid.uuid4())
    sid = str(uuid.uuid4())

    # Pluto metadata
    url = f"{PLUTO_CHANNELS_API}?country={COUNTRY}&language={LANGUAGE}"
    data = http_get_json(url)

    out: list[Channel] = []
    if not isinstance(data, list):
        return out

    for ch in data:
        if not isinstance(ch, dict):
            continue
        ch_id = ch.get("_id") or ch.get("id")
        name = ch.get("name")
        if not ch_id or not name:
            continue

        logo = None
        # spesso Pluto mette "colorLogoPNG" / "logo" / "images"
        for k in ("colorLogoPNG", "logo"):
            if ch.get(k):
                logo = ch.get(k)
                break
        if not logo:
            images = ch.get("images") or {}
            if isinstance(images, dict) and images.get("logo"):
                logo = images.get("logo")

        stitched = build_stitched_url(str(ch_id), device_id, sid)
        tvg_id = f"PlutoTV.{ch_id}.it"

        out.append(Channel(name=name.strip(), url=stitched, logo=logo, tvg_id=tvg_id))

    out.sort(key=lambda x: x.name.lower())
    return out


def build_m3u(channels: list[Channel]) -> str:
    lines = ["#EXTM3U", ""]
    for ch in channels:
        attrs = [
            f'tvg-name="{ch.name}"',
            f'tvg-id="{ch.tvg_id}"' if ch.tvg_id else None,
            f'tvg-logo="{ch.logo}"' if ch.logo else None,
            f'group-title="{GROUP_TITLE}"',
        ]
        attrs = [a for a in attrs if a]
        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{ch.name}')
        lines.append(ch.url)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    channels = parse_channels()
    OUTFILE.write_text(build_m3u(channels), encoding="utf-8")
    print(f"{OUTFILE} generato: {len(channels)} canali ✅")


if __name__ == "__main__":
    main()
