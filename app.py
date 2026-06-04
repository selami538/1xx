import requests
import re
from flask import Flask, Response
from flask_cors import CORS
from urllib.parse import quote

app = Flask(__name__)
CORS(app)

HEADERS = {
    "accept": "*/*",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

WORKERS = "https://ts.yedeklinksa35.workers.dev"

def get_m3u8_url(videoid):
    veriler = {"AppId": "3", "AppVer": "1025", "VpcVer": "1.0.11", "Language": "tr", "Token": "", "VideoId": videoid}
    try:
        r = requests.post("https://1xlite-26316.pro/cinema", json=veriler, timeout=10)
        veri = re.findall('"URL":"(.*?)"', r.text)
        if not veri: return None
        return veri[0].replace("\\/", "/").replace(':43434', '')
    except:
        return None

@app.route('/ott/<videoid>.m3u8')
@app.route('/ott/<videoid>')
def ott(videoid):
    try:
        m3u8_url = get_m3u8_url(videoid)
        if not m3u8_url: return "Veri yok", 404

        ts = requests.get(m3u8_url, headers=HEADERS, timeout=10)
        lines = ts.text.split('\n')
        base_source = re.sub(r'[^/]+\.m3u8.*', '', m3u8_url)

        out = []
        for line in lines:
            line_str = line.strip()
            if not line_str: continue
            
            if not line_str.startswith('#'):
                full_url = line_str if line_str.startswith('http') else base_source + line_str
                encoded = quote(full_url, safe='')
                out.append(f"{WORKERS}/ott-seg/{encoded}.ts") # iOS için .ts uzantısını koru
            else:
                out.append(line_str)

        return Response('\n'.join(out) + '\n', content_type='application/vnd.apple.mpegurl')
    except Exception as e:
        return str(e), 500

@app.route('/ott-seg/<path:encoded>')
def ott_seg(encoded):
    if encoded.endswith('.ts'): encoded = encoded[:-3]
    elif encoded.endswith('.avif'): encoded = encoded[:-5]
    source = requests.utils.unquote(encoded)
    try:
        ts = requests.get(source, headers=HEADERS, timeout=10)
        resp = Response(ts.content, content_type='video/mp2t')
        resp.headers['Access-Control-Allow-Origin'] = '*'
        return resp
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
