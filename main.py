from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import re
import aiohttp

app = FastAPI(title="FB Downloader API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

def is_valid_fb_url(url: str) -> bool:
    pattern = r'(https?://)?(www\.)?(facebook\.com|fb\.watch|fb\.com|m\.facebook\.com)/.+'
    return bool(re.match(pattern, url))

def format_duration(seconds):
    if not seconds:
        return "غير معروف"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02}:{s:02}"
    return f"{m}:{s:02}"

def format_size(bytes_val):
    if not bytes_val:
        return "غير معروف"
    mb = bytes_val / (1024 * 1024)
    return f"~{mb:.0f} MB"

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api/proxy")
async def proxy_download(url: str = Query(...), filename: str = Query(default="video.mp4")):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.facebook.com/",
    }
    async def stream():
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                async for chunk in resp.content.iter_chunked(8192):
                    yield chunk
    return StreamingResponse(
        stream(),
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/download")
async def download(url: str = Query(...)):
    if not url:
        return JSONResponse(status_code=422, content={"success": False, "error": "الرجاء إدخال رابط الفيديو"})

    if not is_valid_fb_url(url):
        return JSONResponse(status_code=422, content={"success": False, "error": "الرابط غير صالح — يجب أن يكون رابط فيسبوك"})

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 30,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        title = (info.get("title") or "فيديو فيسبوك")[:100]
        duration = format_duration(info.get("duration"))
        thumbnail = info.get("thumbnail", "")
        formats = info.get("formats", [])

        qualities = []
        added = set()

        for f in formats:
            h = f.get("height") or 0
            ext = f.get("ext", "mp4")
            furl = f.get("url", "")
            size = format_size(f.get("filesize") or f.get("filesize_approx"))
            vcodec = f.get("vcodec", "none")

            if vcodec == "none":
                continue

            # بناء رابط البروكسي
            import urllib.parse
            proxy_url = f"/api/proxy?url={urllib.parse.quote(furl)}&filename=video_{h}p.mp4"

            if h >= 1080 and "1080p" not in added:
                qualities.append({"quality": "1080p", "label": "عالي الدقة جداً", "url": proxy_url, "size": size, "type": "HD", "ext": ext})
                added.add("1080p")
            elif h >= 720 and "720p" not in added:
                qualities.append({"quality": "720p", "label": "عالي الدقة", "url": proxy_url, "size": size, "type": "HD", "ext": ext})
                added.add("720p")
            elif h >= 480 and "480p" not in added:
                qualities.append({"quality": "480p", "label": "جودة متوسطة", "url": proxy_url, "size": size, "type": "SD", "ext": ext})
                added.add("480p")
            elif h >= 360 and "360p" not in added:
                qualities.append({"quality": "360p", "label": "جودة عادية", "url": proxy_url, "size": size, "type": "SD", "ext": ext})
                added.add("360p")

        # Audio only
        for f in formats:
            if f.get("vcodec") == "none" and f.get("acodec") != "none" and "audio" not in added:
                import urllib.parse
                proxy_url = f"/api/proxy?url={urllib.parse.quote(f.get('url',''))}&filename=audio.mp3"
                qualities.append({
                    "quality": "MP3",
                    "label": "صوت فقط",
                    "url": proxy_url,
                    "size": format_size(f.get("filesize") or f.get("filesize_approx")),
                    "type": "audio",
                    "ext": "mp3"
                })
                added.add("audio")
                break

        if not qualities:
            return JSONResponse(status_code=422, content={"success": False, "error": "لم نتمكن من استخراج روابط التحميل"})

        return {
            "success": True,
            "data": {
                "title": title,
                "duration": duration,
                "thumbnail": thumbnail,
                "qualities": qualities
            }
        }

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "Private" in msg or "login" in msg.lower():
            error = "هذا الفيديو خاص أو يتطلب تسجيل دخول"
        elif "not available" in msg.lower():
            error = "الفيديو غير متاح أو تم حذفه"
        else:
            error = "تعذّر تحميل الفيديو — تأكد من الرابط وحاول مرة أخرى"
        return JSONResponse(status_code=422, content={"success": False, "error": error})

    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": "حدث خطأ في السيرفر"})
