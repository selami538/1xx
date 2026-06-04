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


# ── Flussonic icin — chunk'lar oyster proxy uzerinden (header'li) ──
@app.route('/flu/<videoid>')
@app.route('/flu/<videoid>.m3u8')
def flu(videoid):
    try:
        m3u8_url = get_m3u8_url(videoid)
        if not m3u8_url:
            return "Veri yok", 404
        ts = requests.get(m3u8_url, headers=HEADERS, timeout=10)
        base_source = re.sub(r'[^/]+\.m3u8.*', '', m3u8_url)
        lines = ts.text.split('\n')
        result = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                full = stripped if stripped.startswith('http') else base_source + stripped
                encoded = quote(full, safe='')
                result.append(BASE + '/fluseg/' + encoded)
            else:
                result.append(stripped)
        return Response('\n'.join(result), content_type='application/vnd.apple.mpegurl')
    except Exception as e:
        return str(e), 500


@app.route('/fluseg/<path:encoded>')
def fluseg(encoded):
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
