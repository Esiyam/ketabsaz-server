import os, re, json, base64, uuid, shutil, subprocess
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

BASE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(BASE, "template.apk")      # APK قالب کتاب‌خوان
OUT_DIR = os.path.join(BASE, "output")
KEYSTORE = os.path.join(BASE, "ketabsaz.jks")
KEY_PASS = "ketabsaz123"
API_KEY = os.environ.get("API_KEY", "")   # خالی = بدون کلید

os.makedirs(OUT_DIR, exist_ok=True)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[-400:]}")


def ensure_keystore():
    if not os.path.exists(KEYSTORE):
        run(["keytool", "-genkeypair", "-keystore", KEYSTORE,
             "-alias", "ketabsaz", "-keyalg", "RSA", "-keysize", "2048",
             "-validity", "10000", "-storepass", KEY_PASS,
             "-keypass", KEY_PASS, "-dname", "CN=KetabSaz"])


def clean(h):
    h = re.sub(r"<\s*(script|iframe|object|embed)[^>]*>.*?<\s*/\s*\1\s*>", "", h, flags=re.S | re.I)
    h = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", h, flags=re.I)
    return re.sub(r"javascript:", "", h, flags=re.I)


def build_apk(data):
    for c in data["chapters"]:
        c["html"] = clean(c.get("html") or "")
    job = uuid.uuid4().hex[:10]
    work = os.path.join("/tmp", job)
    dec = os.path.join(work, "dec")
    os.makedirs(work)
    try:
        run(["apktool", "d", "-f", TEMPLATE, "-o", dec])

        # 1) محتوای کتاب
        assets = os.path.join(dec, "assets")
        os.makedirs(assets, exist_ok=True)
        book = {
            "title": data["title"],
            "author": data.get("author", ""),
            "about_author": data.get("about_author", ""),
            "book_bg": data.get("book_bg", "#FFF8E1"),
            "menu_bg": data.get("menu_bg", "#3E2723"),
            "chapters": data["chapters"],   # [{"title":..., "text":...}]
        }
        with open(os.path.join(assets, "book.json"), "w", encoding="utf-8") as f:
            json.dump(book, f, ensure_ascii=False)
        shutil.copy(os.path.join(BASE, "index.html"), os.path.join(assets, "index.html"))
        with open(os.path.join(assets, "book.js"), "w", encoding="utf-8") as f:
            f.write("var BOOK = " + json.dumps(book, ensure_ascii=False) + ";")

        # 2) عکس‌ها (همه base64 هستن و اختیاری)
        imgs = {"cover": "cover.png", "author_photo": "author.png",
                "book_bg_image": "book_bg.png", "menu_bg_image": "menu_bg.png"}
        for key, fn in imgs.items():
            if data.get(key):
                with open(os.path.join(assets, fn), "wb") as f:
                    f.write(base64.b64decode(data[key]))

        # آیکون برنامه (اگه نداد، از کاور استفاده میشه)
        icon = data.get("icon") or data.get("cover")
        if icon:
            img = base64.b64decode(icon)
            for root, _, files in os.walk(os.path.join(dec, "res")):
                for fn in files:
                    if fn in ("ic_launcher.png", "ic_launcher_round.png"):
                        with open(os.path.join(root, fn), "wb") as f:
                            f.write(img)

        # 3) اسم برنامه
        sp = os.path.join(dec, "res", "values", "strings.xml")
        if os.path.exists(sp):
            s = open(sp, encoding="utf-8").read()
            title = (data["title"].replace("&", "&amp;")
                     .replace("<", "&lt;").replace("'", "\\'"))
            s = re.sub(r'(<string name="app_name">).*?(</string>)',
                       lambda m: m.group(1) + title + m.group(2), s)
            open(sp, "w", encoding="utf-8").write(s)

        # 4) پکیج یکتا تا چند کتاب کنار هم نصب بشن
        mp = os.path.join(dec, "AndroidManifest.xml")
        m = open(mp, encoding="utf-8").read()
        m = re.sub(r'(<manifest[^>]*package=")[^"]+(")',
                   lambda x: x.group(1) + f"com.ketabsaz.b{job}" + x.group(2),
                   m, count=1)
        open(mp, "w", encoding="utf-8").write(m)

        # 5) ساخت، زیپ‌الاین، امضا
        raw = os.path.join(work, "raw.apk")
        aligned = os.path.join(work, "aligned.apk")
        final = os.path.join(OUT_DIR, f"{job}.apk")
        run(["apktool", "b", dec, "-o", raw])
        run(["zipalign", "-f", "4", raw, aligned])
        run(["apksigner", "sign", "--ks", KEYSTORE,
             "--ks-pass", f"pass:{KEY_PASS}", "--key-pass", f"pass:{KEY_PASS}",
             "--out", final, aligned])
        return job
    finally:
        shutil.rmtree(work, ignore_errors=True)


@app.route("/")
def home():
    return send_from_directory(BASE, "maker.html")


@app.route("/build", methods=["POST"])
def build():
    if API_KEY and request.headers.get("X-API-Key") != API_KEY:
        return jsonify(error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    if not data.get("title") or not data.get("chapters"):
        return jsonify(error="title and chapters required"), 400
    try:
        job = build_apk(data)
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(url=request.host_url + f"download/{job}.apk")


@app.route("/download/<name>")
def download(name):
    return send_from_directory(OUT_DIR, name, as_attachment=True)


ensure_keystore()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
