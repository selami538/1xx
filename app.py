import requests
import re
import time
import threading
from flask import Flask, request, Response
from flask_cors import CORS
from urllib.parse import quote

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

M3U8_CACHE = {}
M3U8_TTL = 1.5
CACHE_LOCK = threading.Lock()


def get_m3u8_url(videoid):
    veriler = {"AppId": "3", "AppVer": "1025", "VpcVer": "1.0.11", "Language": "tr", "Token": "", "VideoId": videoid}
    r = requests.post("https://1xlite-26316.pro/cinema", json=veriler, timeout=10)
    if "FullscreenAllowed" not in r.text:
        return None
    veri = re.findall('"URL":"(.*?)"', r.text)
    if not veri:
        return None
    veri = veri[0].replace("\\/", "/")
    veri = veri.replace(':43434', '')
    if "m3u8" not in veri:
        return None
    return veri


def build_m3u8(videoid):
    m3u8_url = get_m3u8_url(videoid)
    if not m3u8_url:
        return None

    ts = requests.get(m3u8_url, headers=HEADERS, timeout=10)
    text = ts.text
    base_source = re.sub(r'[^/]+\.m3u8.*', '', m3u8_url)
    query = m3u8_url.split('?', 1)[1] if '?' in m3u8_url else ''

    extinf_values = re.findall(r'#EXTINF:([\d.]+)', text)
    if extinf_values:
        max_dur = max(float(v) for v in extinf_values)
        new_target = int(max_dur) + 1
        text = re.sub(r'#EXT-X-TARGETDURATION:\d+', f'#EXT-X-TARGETDURATION:{new_target}', text)

    lines = text.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            # TAM xmediaget URL'i kur
            if stripped.startswith('http'):
                full = stripped
            else:
                full = base_source + stripped
                if query and '?' not in stripped:
                    full += '?' + query
            # Tam URL'i encode et — nginx decode edip xmediaget'e gidecek
            encoded = quote(full, safe='')
            result.append(WORKERS + '/seg/' + encoded + '.avif')
        else:
            result.append(stripped)
    return '\n'.join(result)


@app.route('/ott/<videoid>.m3u8')
@app.route('/ott/<videoid>')
def ott(videoid):
    try:
        now = time.time()
        with CACHE_LOCK:
            cached = M3U8_CACHE.get(videoid)
        if cached and (now - cached[0] < M3U8_TTL):
            return Response(cached[1], content_type='application/vnd.apple.mpegurl')

        m3u8 = build_m3u8(videoid)
        if not m3u8:
            return "Veri yok", 404
        with CACHE_LOCK:
            M3U8_CACHE[videoid] = (now, m3u8)
        return Response(m3u8, content_type='application/vnd.apple.mpegurl')
    except Exception as e:
        return str(e), 500


# Chunk artik OYSTER'a gelmiyor — nginx direkt xmediaget'e gidiyor.
# Bu endpoint sadece fallback/acil durum icin.
@app.route('/seg/<path:encoded>')
def seg(encoded):
    from urllib.parse import unquote
    if encoded.endswith('.avif'):
        encoded = encoded[:-5]
    source = unquote(encoded)
    try:
        ts = requests.get(source, headers=HEADERS, timeout=10)
        content = ts.content
        resp = Response(content, content_type='video/mp2t')
        resp.headers['Content-Length'] = str(len(content))
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except Exception as e:
        return str(e), 500


if __name__ == '__main__':
    app.run()
