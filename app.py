
import os
import re
import time
import math
import threading
import logging

from collections import OrderedDict
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from flask import Flask, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ───────────── Kaynak ayarlari ─────────────

API_URL = "https://1xlite-6938.pro/cinema"

FORCE_EDGE = "edge3.xmediaget.com"

WORKERS = "https://lionfish-app-kmrcp.ondigitalocean.app"

HEADERS = {
    "accept": "*/*",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "tr-TR,tr;q=0.9",
    "origin": "https://www.maltinok.com",
    "referer": "https://www.maltinok.com/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/108.0.0.0 Safari/537.36"
    )
}

# ───────────── Cache ayarlari ─────────────

M3U8_TTL = 1.5
M3U8_STALE_MAX = 15

SEG_TTL = 60
SEG_MAX_BYTES = 150 * 1024 * 1024

TOKEN_TTL = 20

REQUEST_TIMEOUT = (5, 10)

LOCAL = threading.local()


def get_session():
    if not hasattr(LOCAL, "session"):
        LOCAL.session = requests.Session()
    return LOCAL.session


# ───────────── Edge3 sabitleme ─────────────

def force_edge3(url):
    """
    edge1, edge2, edge6 vb. kaynak adreslerini
    edge3.xmediaget.com olarak degistirir.
    """

    if not url:
        return url

    url = url.replace("\\/", "/")
    url = url.replace(":43434", "")

    parsed = urlsplit(url)

    hostname = parsed.hostname or ""

    if re.fullmatch(
        r"edge\d+\.xmediaget\.com",
        hostname,
        flags=re.IGNORECASE
    ):
        netloc = FORCE_EDGE

        if parsed.username or parsed.password:
            raise ValueError(
                "Beklenmeyen kaynak URL bilgisi"
            )

        if parsed.port and parsed.port != 43434:
            netloc += ":" + str(parsed.port)

        url = urlunsplit((
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.query,
            parsed.fragment
        ))

    return url


# ───────────── Single-flight ─────────────

class SingleFlight:
    def __init__(self):
        self.lock = threading.Lock()
        self.calls = {}

    def do(self, key, fn):
        with self.lock:
            call = self.calls.get(key)

            if call is None:
                call = {
                    "event": threading.Event(),
                    "result": None,
                    "error": None
                }

                self.calls[key] = call
                leader = True
            else:
                leader = False

        if leader:
            try:
                call["result"] = fn()

            except Exception as exc:
                call["error"] = exc

            finally:
                call["event"].set()

                with self.lock:
                    self.calls.pop(key, None)

        else:
            if not call["event"].wait(timeout=25):
                raise TimeoutError(
                    "Upstream istegi zaman asimina ugradi"
                )

        if call["error"] is not None:
            raise call["error"]

        return call["result"]


flight = SingleFlight()


# ───────────── Segment cache ─────────────

class SegmentCache:
    def __init__(self, max_bytes, ttl):
        self.max_bytes = max_bytes
        self.ttl = ttl

        self.size = 0
        self.data = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        now = time.monotonic()

        with self.lock:
            item = self.data.get(key)

            if item is None:
                return None

            expires, content = item

            if expires <= now:
                self.size -= len(content)
                del self.data[key]
                return None

            self.data.move_to_end(key)
            return content

    def put(self, key, content):
        if not content:
            return

        if len(content) > self.max_bytes // 4:
            return

        with self.lock:
            old = self.data.pop(key, None)

            if old is not None:
                self.size -= len(old[1])

            self.data[key] = (
                time.monotonic() + self.ttl,
                content
            )

            self.size += len(content)

            while self.size > self.max_bytes and self.data:
                _, (_, removed) = self.data.popitem(
                    last=False
                )

                self.size -= len(removed)

    def cleanup(self):
        now = time.monotonic()

        with self.lock:
            expired = [
                key
                for key, value in self.data.items()
                if value[0] <= now
            ]

            for key in expired:
                self.size -= len(self.data[key][1])
                del self.data[key]


SEG_CACHE = SegmentCache(
    SEG_MAX_BYTES,
    SEG_TTL
)

M3U8_CACHE = {}
TOKEN_CACHE = {}

CACHE_LOCK = threading.Lock()


# ───────────── Cache temizleyici ─────────────

def janitor():
    while True:
        time.sleep(30)

        SEG_CACHE.cleanup()

        now = time.monotonic()

        with CACHE_LOCK:
            for key in list(M3U8_CACHE):
                if now - M3U8_CACHE[key][0] > 120:
                    del M3U8_CACHE[key]

            for key in list(TOKEN_CACHE):
                if now - TOKEN_CACHE[key]["ts"] > 300:
                    del TOKEN_CACHE[key]


threading.Thread(
    target=janitor,
    daemon=True
).start()


# ───────────── Kaynak URL alma ─────────────

def get_m3u8_url(videoid):
    payload = {
        "AppId": "3",
        "AppVer": "1025",
        "VpcVer": "1.0.11",
        "Language": "tr",
        "Token": "",
        "VideoId": videoid
    }

    response = get_session().post(
        API_URL,
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    raw_text = response.text

    if "FullscreenAllowed" not in raw_text:
        return None

    url = None

    try:
        data = response.json()

        if isinstance(data, dict):
            url = data.get("URL")

    except ValueError:
        pass

    if not url:
        matches = re.findall(
            r'"URL"\s*:\s*"(.*?)"',
            raw_text
        )

        if matches:
            url = matches[0].replace("\\/", "/")

    if not url:
        return None

    # EDGE3 ZORUNLU
    url = force_edge3(url)

    if ".m3u8" not in url:
        return None

    if urlsplit(url).scheme not in (
        "http",
        "https"
    ):
        return None

    logger.info(
        "Video %s icin kaynak host: %s",
        videoid,
        urlsplit(url).hostname
    )

    return url


# ───────────── M3U8 olusturma ─────────────

def _build_m3u8(videoid):
    m3u8_url = get_m3u8_url(videoid)

    if not m3u8_url:
        return None

    response = get_session().get(
        m3u8_url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    playlist = response.text

    if "#EXTM3U" not in playlist:
        raise ValueError(
            "Gecersiz M3U8 verisi"
        )

    parsed = urlsplit(m3u8_url)

    base_source = urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rsplit("/", 1)[0] + "/",
        "",
        ""
    ))

    query = parsed.query

    with CACHE_LOCK:
        TOKEN_CACHE[videoid] = {
            "base": base_source,
            "query": query,
            "ts": time.monotonic()
        }

    durations = re.findall(
        r"#EXTINF:([\d.]+)",
        playlist
    )

    if durations:
        max_duration = max(
            float(value)
            for value in durations
        )

        target = math.ceil(max_duration)

        playlist = re.sub(
            r"#EXT-X-TARGETDURATION:\d+",
            f"#EXT-X-TARGETDURATION:{target}",
            playlist
        )

    result = []

    for line in playlist.splitlines():
        stripped = line.strip()

        if not stripped:
            result.append("")
            continue

        if stripped.startswith("#"):
            result.append(stripped)
            continue

        segment_url = urljoin(
            m3u8_url,
            stripped
        )

        segment_path = urlsplit(
            segment_url
        ).path

        filename = segment_path.rsplit(
            "/",
            1
        )[-1]

        if filename.endswith(".ts"):
            filename = filename[:-3] + ".avif"

        result.append(
            f"{WORKERS}/seg/{videoid}/{filename}"
        )

    return "\n".join(result) + "\n"


def build_m3u8(videoid):
    return flight.do(
        "m3u8:" + videoid,
        lambda: _build_m3u8(videoid)
    )


# ───────────── Token islemleri ─────────────

def get_token(videoid, force=False):
    with CACHE_LOCK:
        info = TOKEN_CACHE.get(videoid)

    expired = (
        info is None
        or time.monotonic() - info["ts"] > TOKEN_TTL
    )

    if force or expired:
        build_m3u8(videoid)

        with CACHE_LOCK:
            info = TOKEN_CACHE.get(videoid)

    return info


# ───────────── Segment indirme ─────────────

def fetch_segment(
    videoid,
    filename,
    force_token=False
):
    info = get_token(
        videoid,
        force=force_token
    )

    if not info:
        return None

    source = urljoin(
        info["base"],
        filename
    )

    if info["query"]:
        source += "?" + info["query"]

    # Segment kaynagi da edge3 olsun
    source = force_edge3(source)

    response = get_session().get(
        source,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code in (
        401,
        403,
        404
    ):
        return None

    response.raise_for_status()

    if not response.content:
        return None

    return response.content


# ───────────── HTTP response ─────────────

def m3u8_response(content):
    response = Response(
        content,
        content_type="application/vnd.apple.mpegurl"
    )

    response.headers["Cache-Control"] = (
        "public, max-age=1"
    )

    return response


def segment_response(content):
    response = Response(
        content,
        content_type="video/mp2t"
    )

    response.headers["Content-Length"] = str(
        len(content)
    )

    response.headers["Cache-Control"] = (
        "public, max-age=60"
    )

    response.headers[
        "Access-Control-Allow-Origin"
    ] = "*"

    return response


# ───────────── Health check ─────────────

@app.route("/health")
def health():
    return {
        "status": "ok",
        "service": "hls-proxy",
        "edge": FORCE_EDGE
    }, 200


@app.route("/")
def index():
    return {
        "status": "running",
        "service": "hls-proxy",
        "edge": FORCE_EDGE
    }, 200


# ───────────── Playlist route ─────────────

@app.route("/ott/<videoid>.m3u8")
@app.route("/ott/<videoid>")
def ott(videoid):
    now = time.monotonic()

    with CACHE_LOCK:
        cached = M3U8_CACHE.get(videoid)

    if (
        cached
        and now - cached[0] < M3U8_TTL
    ):
        return m3u8_response(
            cached[1]
        )

    try:
        playlist = build_m3u8(videoid)

        if not playlist:
            if (
                cached
                and time.monotonic() - cached[0]
                < M3U8_STALE_MAX
            ):
                return m3u8_response(
                    cached[1]
                )

            return "Veri yok", 404

        with CACHE_LOCK:
            M3U8_CACHE[videoid] = (
                time.monotonic(),
                playlist
            )

        return m3u8_response(
            playlist
        )

    except Exception:
        logger.exception(
            "M3U8 hatasi: %s",
            videoid
        )

        if (
            cached
            and time.monotonic() - cached[0]
            < M3U8_STALE_MAX
        ):
            return m3u8_response(
                cached[1]
            )

        return "Kaynak hatasi", 502


# ───────────── Segment route ─────────────

@app.route("/seg/<videoid>/<path:filename>")
def seg(videoid, filename):
    if filename.endswith(".avif"):
        filename = filename[:-5] + ".ts"

    if (
        ".." in filename
        or filename.startswith("/")
        or "\\" in filename
    ):
        return "Gecersiz dosya", 400

    key = videoid + "/" + filename

    content = SEG_CACHE.get(key)

    if content is None:
        try:
            def load():
                result = fetch_segment(
                    videoid,
                    filename
                )

                if result is None:
                    result = fetch_segment(
                        videoid,
                        filename,
                        force_token=True
                    )

                return result

            content = flight.do(
                "seg:" + key,
                load
            )

        except Exception:
            logger.exception(
                "Segment hatasi: %s",
                key
            )

            return "Kaynak hatasi", 502

        if not content:
            return "Veri yok", 404

        SEG_CACHE.put(
            key,
            content
        )

    return segment_response(
        content
    )


# ───────────── DigitalOcean start ─────────────

if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            "8080"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
