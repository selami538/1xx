import requests
import re
import time
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

# Segment gecmisi: {videoid: {seq: (extinf, encoded_url)}}
SEGMENT_HISTORY = {}
MAX_SEGMENTS = 12


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


@app.route('/ott/<videoid>.m3u8')
@app.route('/ott/<videoid>')
def ott(videoid):
    try:
        m3u8_url = get_m3u8_url(videoid)
        if not m3u8_url:
            return "Veri yok", 404
        ts = requests.get(m3u8_url, headers=HEADERS, timeout=10)
        text = ts.text
        base_source = re.sub(r'[^/]+\.m3u8.*', '', m3u8_url)

        # Kaynak MEDIA-SEQUENCE'i al
        mseq_match = re.search(r'#EXT-X-MEDIA-SEQUENCE:(\d+)', text)
        base_seq = int(mseq_match.group(1)) if mseq_match else 0

        # Segmentleri parse et, segment numarasini cikar
        lines = text.split('\n')
        max_extinf = 2.0
        i = 0
        seq_offset = 0
        if videoid not in SEGMENT_HISTORY:
            SEGMENT_HISTORY[videoid] = {}
        hist = SEGMENT_HISTORY[videoid]

        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('#EXTINF:'):
                dur = float(re.findall(r'[\d.]+', line)[0])
                max_extinf = max(max_extinf, dur)
                if i + 1 < len(lines):
                    seg_line = lines[i+1].strip()
                    if seg_line and not seg_line.startswith('#'):
                        full = seg_line if seg_line.startswith('http') else base_source + seg_line
                        # Segment numarasini dosya adindan cikar
                        num_match = re.search(r'segment(\d+)', full)
                        seg_num = int(num_match.group(1)) if num_match else (base_seq + seq_offset)
                        encoded = quote(full, safe='')
                        hist[seg_num] = (line, WORKERS + '/ott-seg/' + encoded + '.avif')
                        seq_offset += 1
                i += 2
            else:
                i += 1

        # Eski segmentleri temizle, son MAX_SEGMENTS tut
        if len(hist) > MAX_SEGMENTS:
            for k in sorted(hist.keys())[:-MAX_SEGMENTS]:
                del hist[k]

        # M3U8 olustur — sirali segmentler
        sorted_nums = sorted(hist.keys())
        target = int(max_extinf) + 1
        out = ['#EXTM3U', '#EXT-X-VERSION:3', f'#EXT-X-TARGETDURATION:{target}',
               f'#EXT-X-MEDIA-SEQUENCE:{sorted_nums[0]}']
        for n in sorted_nums:
            extinf, url = hist[n]
            out.append(extinf)
            out.append(url)

        return Response('\n'.join(out) + '\n', content_type='application/vnd.apple.mpegurl')
    except Exception as e:
        return str(e), 500


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
