import requests
import re
from flask import Flask, request, Response
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

BASE = "https://oyster-app-4xkwy.ondigitalocean.app"
WORKERS = "https://ts.yedeklinksa35.workers.dev"

# videoid -> {"base": edge+path prefix, "query": token query}
TOKEN_CACHE = {}


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


def fix_m3u8(tsal, videoid, m3u8_url):
    # base_source: edge + path (mediaplaylist.m3u8'e kadar)
    base_source = re.sub(r'[^/]+\.m3u8.*', '', m3u8_url)
    # token query (m3u8 URL'indeki ?s=...&t=...)
    query = ''
    if '?' in m3u8_url:
        query = m3u8_url.split('?', 1)[1]

    # Bu videoid icin edge+token sakla
    TOKEN_CACHE[videoid] = {"base": base_source, "query": query}

    # iOS uyumu — TARGETDURATION
    extinf_values = re.findall(r'#EXTINF:([\d.]+)', tsal)
    if extinf_values:
        max_dur = max(float(v) for v in extinf_values)
        new_target = int(max_dur) + 1
        tsal = re.sub(r'#EXT-X-TARGETDURATION:\d+', f'#EXT-X-TARGETDURATION:{new_target}', tsal)

    lines = tsal.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            # sadece dosya adini al (segment1804.ts gibi), token'i at
            if stripped.startswith('http'):
                fname = stripped.split('/')[-1].split('?')[0]
            else:
                fname = stripped.split('?')[0]
            # KISA chunk URL: /seg/<videoid>/<dosyaadi>
            result.append(WORKERS + '/seg/' + videoid + '/' + fname)
        else:
            result.append(stripped)
    return '\n'.join(result)


@app.route('/ott/<videoid>.m3u8')
@app.route('/ott/<videoid>')
def ott(videoid):
    try:
        m3u8_url = get_m3u8_url(videoid)
        if not m3u8_url:
            return "Veri yok", 404
        ts = requests.get(m3u8_url, headers=HEADERS, timeout=10)
        tsal = fix_m3u8(ts.text, videoid, m3u8_url)
        return Response(tsal, content_type='application/vnd.apple.mpegurl')
    except Exception as e:
        return str(e), 500


# KISA chunk endpoint — /seg/<videoid>/<dosyaadi>
@app.route('/seg/<videoid>/<filename>')
def seg(videoid, filename):
    info = TOKEN_CACHE.get(videoid)
    if not info:
        # token yoksa once m3u8 cek (edge+token doldur)
        m3u8_url = get_m3u8_url(videoid)
        if m3u8_url:
            base_source = re.sub(r'[^/]+\.m3u8.*', '', m3u8_url)
            query = m3u8_url.split('?', 1)[1] if '?' in m3u8_url else ''
            info = {"base": base_source, "query": query}
            TOKEN_CACHE[videoid] = info
        else:
            return "Veri yok", 404

    source = info["base"] + filename
    if info["query"]:
        source += '?' + info["query"]
    try:
        ts = requests.get(source, headers=HEADERS, timeout=10)
        content = ts.content
        # token eskiyse (bos donduyse) bir kez yenile ve tekrar dene
        if len(content) == 0:
            m3u8_url = get_m3u8_url(videoid)
            if m3u8_url:
                base_source = re.sub(r'[^/]+\.m3u8.*', '', m3u8_url)
                query = m3u8_url.split('?', 1)[1] if '?' in m3u8_url else ''
                TOKEN_CACHE[videoid] = {"base": base_source, "query": query}
                source = base_source + filename
                if query:
                    source += '?' + query
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
