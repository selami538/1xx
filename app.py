import requests
import re
import time
import threading
from flask import Flask, request, Response, redirect
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

# ── CACHE AYARLARI ──
M3U8_CACHE = {}
M3U8_TTL = 8.0  # Sunucuya nefes aldırmak için en az 5-10 saniye arası olmalı

TOKEN_CACHE = {}
CACHE_LOCK = threading.Lock()


def get_m3u8_url(videoid):
    """1xlite API'sinden ana m3u8 url'sini çeker."""
    try:
        veriler = {"AppId": "3", "AppVer": "1025", "VpcVer": "1.0.11", "Language": "tr", "Token": "", "VideoId": videoid}
        r = requests.post("https://1xlite-26316.pro/cinema", json=veriler, timeout=5)
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
    except Exception:
        return None


def build_m3u8(videoid):
    """M3U8 dosyasını çeker, düzenler ve token/base bilgisini cache'ler."""
    m3u8_url = get_m3u8_url(videoid)
    if not m3u8_url:
        return None

    try:
        ts = requests.get(m3u8_url, headers=HEADERS, timeout=5)
        text = ts.text
    except Exception:
        return None

    base_source = re.sub(r'[^/]+\.m3u8.*', '', m3u8_url)
    query = m3u8_url.split('?', 1)[1] if '?' in m3u8_url else ''

    # Token ve Base URL bilgisini uzun süreli cache'e alıyoruz (Segment yönlendirmesi için)
    with CACHE_LOCK:
        TOKEN_CACHE[videoid] = {"base": base_source, "query": query, "updated_at": time.time()}

    # iOS uyumu — TARGETDURATION ayarı
    extinf_values = re.findall(r'#EXTINF:([\d.]+)', text)
    if extinf_values:
        max_dur = max(float(v) for v in extinf_values)
        new_target = int(max_dur) + 1
        text = re.sub(r'#EXT-X-TARGETDURATION:\d+', f'#EXT-X-TARGETDURATION:{new_target}', text)

    lines = text.split('\n')
    result = []
    
    # Kendi sunucunun URL yapısı (Örn: http://127.0.0.1:5000)
    host_url = request.host_url.rstrip('/')

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            if stripped.startswith('http'):
                fname = stripped.split('/')[-1].split('?')[0]
            else:
                fname = stripped.split('?')[0]
            
            # Uzantıyı yine senin istediğin gibi geçiriyoruz ancak istek /seg'e gelecek
            if not fname.endswith('.avif'):
                fname = fname.replace('.ts', '.avif')
                
            result.append(f"{host_url}/seg/{videoid}/{fname}")
        else:
            result.append(stripped)
            
    return '\n'.join(result)


@app.route('/ott/<videoid>.m3u8')
@app.route('/ott/<videoid>')
def ott(videoid):
    try:
        now = time.time()
        
        # 1. Aşama: M3U8 Cache Kontrolü
        with CACHE_LOCK:
            cached = M3U8_CACHE.get(videoid)
            
        if cached and (now - cached[0] < M3U8_TTL):
            return Response(cached[1], content_type='application/vnd.apple.mpegurl')

        # 2. Aşama: Cache yoksa veya eskidiyse yeniden üret
        m3u8 = build_m3u8(videoid)
        if not m3u8:
            # Eğer API o an hata verdiyse eski cache'i can simidi olarak 5 saniye daha kullan
            if cached:
                return Response(cached[1], content_type='application/vnd.apple.mpegurl')
            return "Veri yok", 404
            
        with CACHE_LOCK:
            M3U8_CACHE[videoid] = (now, m3u8)
            
        return Response(m3u8, content_type='application/vnd.apple.mpegurl')
    except Exception as e:
        return str(e), 500


@app.route('/seg/<videoid>/<filename>')
def seg(videoid, filename):
    """
    Kritik Değişiklik: Sunucu videoyu indirip proxy yapmaz!
    Doğrudan asıl video kaynağının URL'sine 302 Redirect atar.
    Böylece tüm video trafiği yükü asıl sunucuya biner, senin sunucun donmaz.
    """
    if filename.endswith('.avif'):
        filename = filename[:-5] + '.ts'

    with CACHE_LOCK:
        info = TOKEN_CACHE.get(videoid)

    # Eğer cache'de token yoksa veya çok eskiyse (örn 10 dakikadan eski) yenile
    if not info or (time.time() - info.get("updated_at", 0) > 600):
        build_m3u8(videoid)
        with CACHE_LOCK:
            info = TOKEN_CACHE.get(videoid)
            
    if not info:
        return "Token bulunamadı", 404

    # Asıl video segmentinin tam URL'sini inşa et
    source_url = info["base"] + filename
    if info["query"]:
        source_url += '?' + info["query"]

    # Kullanıcıyı/Oynatıcıyı doğrudan asıl video linkine yönlendiriyoruz
    return redirect(source_url, code=302)


if __name__ == '__main__':
    # threaded=True: Eşzamanlı isteklerin birbirini kitlemesini önler.
    app.run(host='0.0.0.0', port=5000, threaded=True)
