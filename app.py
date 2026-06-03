import requests
import re
from flask import Flask, request, Response
from flask_cors import CORS
from urllib.parse import quote, unquote

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
    base_source = re.sub(r'[^/]+\.m3u8.*', '', m3u8_url)

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
            if stripped.startswith('http'):
                full = stripped
            else:
                full = base_source + stripped
            # Tam URL'i encode et, Workers /ott-seg/<encoded>.avif ile ver
            encoded = quote(full, safe='')
            result.append(WORKERS + '/ott-seg/' + encoded + '.avif')
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


# Chunk proxy — encoded source path'te, .avif sonek atilir
@app.route('/ott-seg/<path:encoded>')
def ott_seg(encoded):
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
