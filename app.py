import requests
from flask import Flask, request, Response
from flask_cors import CORS
import re

app = Flask(__name__)
CORS(app)

HEADERS = {
    "accept": "*/*",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "tr-TR, tr;q = 0.9",
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
    veri = re.sub(r'edge\d+', 'edge10', veri)
    veri = veri.replace(':43434', '')
    if "m3u8" not in veri:
        return None
    return veri


# ── Flussonic icin — chunk'lar oyster proxy uzerinden (header'li, 403 yok) ──
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
                if stripped.startswith('http'):
                    full = stripped
                else:
                    full = base_source + stripped
                # Chunk'i oyster getstream proxy'sine cevir (header ekler, 403 olmaz)
                result.append(BASE + '/getstream?param=getts&source=' + full)
            else:
                result.append(stripped)
        return Response('\n'.join(result), content_type='application/vnd.apple.mpegurl')
    except Exception as e:
        return str(e), 500


@app.route('/<m3u8>')
def index(m3u8):
    m3u8 = request.url.replace('__', '/')
    source = m3u8
    source = source.replace(BASE + '/', '')
    source = source.replace('%2F', '/')
    source = source.replace('%3F', '?')
    videoid = request.args.get("videoid")
    ts = requests.get(source, headers=HEADERS)
    tsal = ts.text
    tsal = tsal.replace(videoid + '_', BASE + '/getstream?param=getts&source=https://edge10.xmediaget.com/hls-live/' + videoid + '/1/' + videoid + '_')
    if "internal" in tsal:
        tsal = tsal.replace('internal', BASE + '/getstream?param=getts&source=https://edge10.xmediaget.com/hls-live/' + videoid + '/1/internal')
    if "segment" in tsal:
        tsal = tsal.replace('\nmedia', '\n' + BASE + '/getstream?param=getts&source=https://edge10.xmediaget.com/hls-live/' + videoid + '/1/media')
    return tsal


@app.route('/getstream', methods=['GET'])
def getstream():
    param = request.args.get("param")
    if param == "getts":
        source = request.url
        source = source.replace(BASE + '/getstream?param=getts&source=', '')
        source = source.replace('%2F', '/')
        source = source.replace('%3F', '?')
        ts = requests.get(source, headers=HEADERS)
        return ts.content
    if param == "getm3u8":
        videoid = request.args.get("videoid")
        veriler = {"AppId": "3", "AppVer": "1025", "VpcVer": "1.0.11", "Language": "tr", "Token": "", "VideoId": videoid}
        r = requests.post("https://1xlite-26316.pro/cinema", json=veriler)
        if "FullscreenAllowed" in r.text:
            veri = r.text
            veri = re.findall('"URL":"(.*?)"', veri)
            veri = veri[0].replace("\\/", "__")
            veri = re.sub(r'edge\d+', 'edge10', veri)
            veri = veri.replace(':43434', '')
            if "m3u8" in veri:
                return BASE + "/" + veri + '&videoid=' + videoid
        else:
            return "Veri yok"


if __name__ == '__main__':
    app.run()
