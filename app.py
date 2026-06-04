import requests
import re
from flask import Flask, redirect
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

HEADERS = {
    "accept": "*/*",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

FLUSSONIC_SERVER = "http://95.179.255.147"
# Flussonic'e komut vermek için config'deki edit_auth bilgilerini kullanıyoruz
FLUSSONIC_API_USER = "flussonic"
FLUSSONIC_API_PASS = "letmein!"

def get_m3u8_url(videoid):
    veriler = {"AppId": "3", "AppVer": "1025", "VpcVer": "1.0.11", "Language": "tr", "Token": "", "VideoId": videoid}
    try:
        r = requests.post("https://1xlite-26316.pro/cinema", json=veriler, timeout=10)
        if "FullscreenAllowed" not in r.text:
            return None
        veri = re.findall('"URL":"(.*?)"', r.text)
        if not veri:
            return None
        return veri[0].replace("\\/", "/").replace(':43434', '')
    except Exception:
        return None

@app.route('/ott/<videoid>.m3u8')
@app.route('/ott/<videoid>')
def ott(videoid):
    try:
        # 1. İstek geldiğinde Oyster'dan çalışan taze linki kapıyoruz
        oyster_real_url = get_m3u8_url(videoid)
        if not oyster_real_url: 
            return "Oyster kaynak linki çözülemedi", 404

        stream_name = f"ott_{videoid}"

        # 2. FLUSSONIC API'sine canlı olarak bu kanalı transcode ayarıyla ekle diyoruz
        # Hata payını sıfırlamak için resmi Flussonic API formatını kullanıyoruz
        api_url = f"{FLUSSONIC_SERVER}/flussonic/api/v3/streams/{stream_name}"
        
        payload = {
            "inputs": [{"url": oyster_real_url}],
            "transcoder": {
                "vcodec": [{"codec": "copy"}],
                "acodec": [{"codec": "aac", "bitrate": 128}]
            },
            "ondemand": True, # Kimse izlemezse kapansın sunucu yorulmasın
            "clients_timeout": 60
        }

        # Flussonic'e komutu gönderiyoruz
        requests.put(
            api_url, 
            json=payload, 
            auth=(FLUSSONIC_API_USER, FLUSSONIC_API_PASS), 
            timeout=5
        )

        # 3. İzleyiciyi Flussonic'in az önce oluşturduğu kusursuz tamir edilmiş yayına yönlendiriyoruz
        return redirect(f"{FLUSSONIC_SERVER}/{stream_name}/index.m3u8")

    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000)
