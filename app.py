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

BASE_URL = "https://oyster-app-4xkwy.ondigitalocean.app"
WORKERS_URL = "https://ts.yedeklinksa35.workers.dev"


def normalize_edge(url):
    url = re.sub(r'edge\d+', 'edge10', url)
    url = url.replace(':43434', '')
    return url


def get_m3u8_url(videoid):
    veriler = {
        "AppId": "3",
        "AppVer": "1025",
        "VpcVer": "1.0.11",
        "Language": "tr",
        "Token": "",
        "VideoId": videoid
    }
    r = requests.post("https://1xlite-26316.pro/cinema", json=veriler, timeout=10)
    if "FullscreenAllowed" not in r.text:
        return None
    veri = re.findall('"URL":"(.*?)"', r.text)
    if not veri:
        return None
    veri = veri[0].replace("\\/", "/")
    veri = normalize_edge(veri)
    if "m3u8" not in veri:
        return None
    return veri


def fix_m3u8(tsal, videoid, m3u8_url, chunk_base):
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
                filename = stripped.split('/')[-1].split('?')[0]
                query = '?' + stripped.split('?')[1] if '?' in stripped else ''
            else:
                full = base_source + stripped
                filename = full.split('/')[-1].split('?')[0]
                query = '?' + full.split('?')[1] if '?' in full else ''
            filename_avif = filename.replace('.ts', '.avif')
            result.append(chunk_base + filename_avif + query)
        else:
            result.append(stripped)

    return '\n'.join(result)


# ── Flussonic icin — chunk'lar HAM xmediaget (Workers degil) ──
@app.route('/flu/<videoid>')
@app.route('/flu/<videoid>.m3u8')
def flu(videoid):
    try:
        m3u8_url = get_m3u8_url(videoid)
        if not m3u8_url:
            return "Veri yok", 404
        ts = requests.get(m3u8_url, headers=HEADERS, timeout=10)
        # Chunk'lar direkt xmediaget — Flussonic pull edebilsin
        base_source = re.sub(r'[^/]+\.m3u8.*', '', m3u8_url)
        lines = ts.text.split('\n')
        result = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                if stripped.startswith('http'):
                    result.append(stripped)
                else:
                    result.append(base_source + stripped)
            else:
                result.append(stripped)
        return Response('\n'.join(result), content_type='application/vnd.apple.mpegurl')
    except Exception as e:
        return str(e), 500


@app.route('/ott/<videoid>.m3u8')
def ott_m3u8(videoid):
    try:
        m3u8_url = get_m3u8_url(videoid)
        if not m3u8_url:
            return "Veri yok", 404
        ts = requests.get(m3u8_url, headers=HEADERS, timeout=10)
        tsal = fix_m3u8(ts.text, videoid, m3u8_url, WORKERS_URL + '/ott-seg/' + videoid + '/')
        return Response(tsal, content_type='application/vnd.apple.mpegurl')
    except Exception as e:
        return str(e), 500


@app.route('/ott/<videoid>')
def ott(videoid):
    try:
        m3u8_url = get_m3u8_url(videoid)
        if not m3u8_url:
            return "Veri yok", 404
        ts = requests.get(m3u8_url, headers=HEADERS, timeout=10)
        tsal = fix_m3u8(ts.text, videoid, m3u8_url, WORKERS_URL + '/ott-seg/' + videoid + '/')
        return Response(tsal, content_type='application/vnd.apple.mpegurl')
    except Exception as e:
        return str(e), 500


@app.route('/ott-seg/<videoid>/<path:filename>')
def ott_seg(videoid, filename):
    filename = filename.replace('.avif', '.ts')
    query = request.query_string.decode()
    source = 'https://edge10.xmediaget.com/hls-live/' + videoid + '/1/' + filename
    if query:
        source += '?' + query
    try:
        ts = requests.get(source, headers=HEADERS, timeout=10)
        return Response(ts.content, content_type=ts.headers.get('Content-Type', 'video/mp2t'))
    except Exception as e:
        return str(e), 500


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
        try:
            m3u8_url = get_m3u8_url(videoid)
            if not m3u8_url:
                return "Veri yok", 404
            return BASE_URL + "/" + m3u8_url.replace("/", "__") + '&videoid=' + videoid
        except Exception as e:
            return str(e), 500
    return "param hatali", 400


@app.route('/<path:m3u8>')
def index(m3u8):
    source = request.url.replace('__', '/')
    source = source.replace(BASE_URL + '/', '')
    source = source.replace('%2F', '/')
    source = source.replace('%3F', '?')
    videoid = request.args.get("videoid", "")
    try:
        ts = requests.get(source, headers=HEADERS, timeout=10)
        tsal = fix_m3u8(ts.text, videoid, source, WORKERS_URL + '/ott-seg/' + videoid + '/')
        return Response(tsal, content_type='application/vnd.apple.mpegurl')
    except Exception as e:
        return str(e), 500


if __name__ == '__main__':
    app.run()
