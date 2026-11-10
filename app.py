import requests
import re
import time
import threading
from collections import OrderedDict
from flask import Flask, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

HEADERS = {
    "accept": "*/*",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "tr-TR,tr;q=0.9",
    "origin": "https://www.maltinok.com",
    "referer": "https://www.maltinok.com/",
    'sec-ch-ua': '"Not?A_Brand";v="8", "Chromium";v="108", "Google Chrome";v="108"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'cross-site',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
}

WORKERS = "https://ts.yedeklinksa35.workers.dev"

# ───────────── Ayarlar ─────────────
M3U8_TTL = 1.5            # m3u8 taze kalma suresi (sn)
M3U8_STALE_MAX = 15       # hata durumunda eski m3u8 en fazla kac sn kullanilsin
SEG_TTL = 60              # segment cache suresi (sn)
SEG_MAX_BYTES = 150 * 1024 * 1024   # toplam segment cache boyutu (RAM)
TOKEN_TTL = 20            # token/base ne kadar sonra yenilensin (sn)

session = requests.Session()


# ───────────── Single-flight: ayni anahtar icin tek is ─────────────
class SingleFlight:
    def __init__(self):
        self._lock = threading.Lock()
        self._calls = {}

    def do(self, key, fn):
        with self._lock:
            call = self._calls.get(key)
            if call is None:
                call = {"event": threading.Event(), "result": None, "error": None}
                self._calls[key] = call
                leader = True
            else:
                leader = False
        if leader:
            try:
                call["result"] = fn()
            except Exception as e:
                call["error"] = e
            finally:
                call["event"].set()
                with self._lock:
                    self._calls.pop(key, None)
        else:
            call["event"].wait(timeout=20)
        if call["error"]:
            raise call["error"]
        return call["result"]


flight = SingleFlight()


# ───────────── Segment cache (LRU + TTL + boyut limiti) ─────────────
class SegmentCache:
    def __init__(self, max_bytes, ttl):
        self.max_bytes = max_bytes
        self.ttl = ttl
        self.size = 0
        self.data = OrderedDict()  # key -> (expire_ts, bytes)
        self.lock = threading.Lock()

    def get(self, key):
        now = time.time()
        with self.lock:
            item = self.data.get(key)
            if not item:
                return None
            if item[0] < now:
                self.size -= len(item[1])
                del self.data[key]
                return None
            self.data.move_to_end(key)
            return item[1]

    def put(self, key, content):
        if not content or len(content) > self.max_bytes // 4:
            return
        with self.lock:
            old = self.data.pop(key, None)
            if old:
                self.size -= len(old[1])
            self.data[key] = (time.time() + self.ttl, content)
            self.size += len(content)
            while self.size > self.max_bytes and self.data:
                _, (_, b) = self.data.popitem(last=False)
                self.size -= len(b)

    def cleanup(self):
        now = time.time()
        with self.lock:
            for k in [k for k, v in self.data.items() if v[0] < now]:
                self.size -= len(self.data[k][1])
                del self.data[k]


SEG_CACHE = SegmentCache(SEG_MAX_BYTES, SEG_TTL)

M3U8_CACHE = {}     # videoid -> (timestamp, m3u8_text)
TOKEN_CACHE = {}    # videoid -> {"base", "query", "ts"}
CACHE_LOCK = threading.Lock()


def janitor():
    while True:
        time.sleep(30)
        SEG_CACHE.cleanup()
        now = time.time()
        with CACHE_LOCK:
            for k in [k for k, v in M3U8_CACHE.items() if now - v[0] > 120]:
                del M3U8_CACHE[k]
            for k in [k for k, v in TOKEN_CACHE.items() if now - v["ts"] > 300]:
                del TOKEN_CACHE[k]


threading.Thread(target=janitor, daemon=True).start()


# ───────────── Kaynak islemleri ─────────────
def get_m3u8_url(videoid):
    veriler = {"AppId": "3", "AppVer": "1025", "VpcVer": "1.0.11", "Language": "tr", "Token": "", "VideoId": videoid}
    r = session.post("https://1xlite-6938.pro/cinema", json=veriler, timeout=10)
    if "FullscreenAllowed" not in r.text:
        return None
    veri = re.findall('"URL":"(.*?)"', r.text)
    if not veri:
        return None
    veri = veri[0].replace("\\/", "/").replace(':43434', '')
    if "m3u8" not in veri:
        return None
    return veri


def _build_m3u8(videoid):
    m3u8_url = get_m3u8_url(videoid)
    if not m3u8_url:
        return None

    ts = session.get(m3u8_url, headers=HEADERS, timeout=10)
    text = ts.text
    base_source = re.sub(r'[^/]+\.m3u8.*', '', m3u8_url)
    query = m3u8_url.split('?', 1)[1] if '?' in m3u8_url else ''

    with CACHE_LOCK:
        TOKEN_CACHE[videoid] = {"base": base_source, "query": query, "ts": time.time()}

    extinf_values = re.findall(r'#EXTINF:([\d.]+)', text)
    if extinf_values:
        max_dur = max(float(v) for v in extinf_values)
        new_target = int(max_dur) + 1
        text = re.sub(r'#EXT-X-TARGETDURATION:\d+', f'#EXT-X-TARGETDURATION:{new_target}', text)

    result = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            if stripped.startswith('http'):
                fname = stripped.split('/')[-1].split('?')[0]
            else:
                fname = stripped.split('?')[0]
            result.append(WORKERS + '/seg/' + videoid + '/' + fname.replace('.ts', '.avif'))
        else:
            result.append(stripped)
    return '\n'.join(result)


def build_m3u8(videoid):
    """Ayni videoid icin ayni anda tek upstream cagrisi."""
    return flight.do("m3u8:" + videoid, lambda: _build_m3u8(videoid))


def get_token(videoid, force=False):
    with CACHE_LOCK:
        info = TOKEN_CACHE.get(videoid)
    if force or not info or time.time() - info["ts"] > TOKEN_TTL:
        build_m3u8(videoid)
        with CACHE_LOCK:
            info = TOKEN_CACHE.get(videoid)
    return info


def fetch_segment(videoid, filename, force_token=False):
    info = get_token(videoid, force=force_token)
    if not info:
        return None
    source = info["base"] + filename
    if info["query"]:
        source += '?' + info["query"]
    r = session.get(source, headers=HEADERS, timeout=10)
    return r.content


# ───────────── Route'lar ─────────────
@app.route('/ott/<videoid>.m3u8')
@app.route('/ott/<videoid>')
def ott(videoid):
    now = time.time()
    with CACHE_LOCK:
        cached = M3U8_CACHE.get(videoid)

    if cached and now - cached[0] < M3U8_TTL:
        return m3u8_response(cached[1])

    try:
        m3u8 = build_m3u8(videoid)
        if not m3u8:
            return "Veri yok", 404
        with CACHE_LOCK:
            M3U8_CACHE[videoid] = (time.time(), m3u8)
        return m3u8_response(m3u8)
    except Exception as e:
        # kaynak hata verdi: eski m3u8 varsa yayin kesilmesin
        if cached and now - cached[0] < M3U8_STALE_MAX:
            return m3u8_response(cached[1])
        return str(e), 500


def m3u8_response(text):
    resp = Response(text, content_type='application/vnd.apple.mpegurl')
    resp.headers['Cache-Control'] = 'public, max-age=1'
    return resp


@app.route('/seg/<videoid>/<filename>')
def seg(videoid, filename):
    if filename.endswith('.avif'):
        filename = filename[:-5] + '.ts'

    key = videoid + '/' + filename
    content = SEG_CACHE.get(key)

    if content is None:
        try:
            def load():
                c = fetch_segment(videoid, filename)
                if not c:  # token eskimis olabilir, bir kez yenile
                    c = fetch_segment(videoid, filename, force_token=True)
                return c
            content = flight.do("seg:" + key, load)
        except Exception as e:
            return str(e), 502
        if not content:
            return "Veri yok", 404
        SEG_CACHE.put(key, content)

    resp = Response(content, content_type='video/mp2t')
    resp.headers['Content-Length'] = str(len(content))
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'public, max-age=60'
    return resp


if __name__ == '__main__':
    app.run(threaded=True)
