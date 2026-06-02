import requests
from flask import Flask, request, Response
from flask_cors import CORS
import re

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

BASE_URL = "https://oyster-app-4xkwy.ondigitalocean.app"
NGINX_URL = "https://corestream.ronaldovurdu.help"


@app.route('/<path:m3u8>')
def index(m3u8):
    source = request.url.replace('__', '/')
    source = source.replace(BASE_URL + '/', '')
    source = source.replace('%2F', '/')
    source = source.replace('%3F', '?')

    videoid = request.args.get("videoid", "")

    try:
        ts = requests.get(source, headers=HEADERS, timeout=10)
        tsal = ts.text
    except Exception as e:
        return str(e), 500

    # Chunk URL'lerini nginx üzerinden ver
    tsal = tsal.replace(
        videoid + '_',
        NGINX_URL + '/ott-seg/getstream?param=getts&source=https://edge10.xmediaget.com/hls-live/' + videoid + '/1/' + videoid + '_'
    )
    if "internal" in tsal:
        tsal = tsal.replace(
            'internal',
            NGINX_URL + '/ott-seg/getstream?param=getts&source=https://edge10.xmediaget.com/hls-live/' + videoid + '/1/internal'
        )
    if "segment" in tsal:
        tsal = tsal.replace(
            '\n' + 'media',
            '\n' + NGINX_URL + '/ott-seg/getstream?param=getts&source=https://edge10.xmediaget.com/hls-live/' + videoid + '/1/media'
        )

    return Response(tsal, content_type='application/vnd.apple.mpegurl')


@app.route('/getm3u8', methods=['GET'])
def getm3u8():
    source = request.url
    source = source.replace(BASE_URL + '/getm3u8?source=', '')
    source = source.replace('%2F', '/')
    source = source.replace('%3F', '?')

    videoid = request.args.get("videoid", "")

    try:
        ts = requests.get(source, headers=HEADERS, timeout=10)
        tsal = ts.text
    except Exception as e:
        return str(e), 500

    tsal = tsal.replace(
        videoid + '_',
        NGINX_URL + '/ott-seg/getstream?param=getts&source=https://edge10.xmediaget.com/hls-live/' + videoid + '/1/' + videoid + '_'
    )

    return Response(tsal, content_type='application/vnd.apple.mpegurl')


@app.route('/getstream', methods=['GET'])
def getstream():
    param = request.args.get("param")

    if param == "getts":
        source = request.url
        source = source.replace(BASE_URL + '/getstream?param=getts&source=', '')
        source = source.replace('%2F', '/')
        source = source.replace('%3F', '?')

        try:
            ts = requests.get(source, headers=HEADERS, timeout=10)
            return Response(ts.content, content_type=ts.headers.get('Content-Type', 'video/mp2t'))
        except Exception as e:
            return str(e), 500

    if param == "getm3u8":
        videoid = request.args.get("videoid", "")
        veriler = {
            "AppId": "3",
            "AppVer": "1025",
            "VpcVer": "1.0.11",
            "Language": "tr",
            "Token": "",
            "VideoId": videoid
        }

        try:
            r = requests.post("https://1xlite-26316.pro/cinema", json=veriler, timeout=10)
        except Exception as e:
            return str(e), 500

        if "FullscreenAllowed" in r.text:
            veri = r.text
            veri = re.findall('"URL":"(.*?)"', veri)
            if not veri:
                return "URL bulunamadi", 404
            veri = veri[0].replace("\\/", "__")
            for edge in ['edge3', 'edge4', 'edge2', 'edge5', 'edge6', 'edge7']:
                veri = veri.replace(edge, 'edge10')
            veri = veri.replace('edge1', 'edge10')
            veri = veri.replace('edge100', 'edge10')
            veri = veri.replace(':43434', '')
            if "m3u8" in veri:
                return BASE_URL + "/" + veri + '&videoid=' + videoid
        return "Veri yok", 404


if __name__ == '__main__':
    app.run()
