"""Server Flask chatbot adminduk (offline) + tampilan web.

Jalankan:  python app.py   ->  buka http://127.0.0.1:5000

Halaman : GET /            beranda
          GET /chat        halaman chat
API     : POST /api/chat   {"pertanyaan": "..."} -> {"jawaban", "sumber", "saran"}
          POST /chat       sama, versi lama (juga mengembalikan intent/topik/skor/mode untuk keperluan uji)
          GET  /health     status server

Mode uji tanpa model (hanya untuk mengecek tampilan):  ADMINDUK_MOCK=1 python app.py
"""
import os
# Pakai PyTorch saja; cegah transformers memuat TensorFlow/Keras yang terpasang di laptop
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("USE_FLAX", "0")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
import json
import sys
import time
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

os.environ.setdefault("HF_HUB_OFFLINE", "1")        # tidak pernah menghubungi internet
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from flask import Flask, jsonify, redirect, render_template, request

import rag_adminduk as rag

BASE = Path(__file__).resolve().parent
MODEL_DIR = BASE / "qwen_adminduk_merged"
RETRIEVER_DIR = BASE / "retriever_e5_small"
MOCK = os.environ.get("ADMINDUK_MOCK", "").strip().lower() in ("1", "true", "ya", "yes")

# rag_config.json dari paket ini; kunci yang tidak ada memakai nilai bawaan di rag_adminduk.py
CFG = json.loads((BASE / "rag_config.json").read_text(encoding="utf-8"))
KB = json.loads((BASE / "knowledge_base_adminduk_v4.json").read_text(encoding="utf-8"))
SLANG = json.loads((BASE / "slang_id.json").read_text(encoding="utf-8"))
SYSTEM_PROMPT = (BASE / "system_prompt.txt").read_text(encoding="utf-8").strip()


def load_real_bot():
    missing = [p.name for p in (MODEL_DIR, RETRIEVER_DIR)
               if not ((p / "config.json").exists() or (p / "modules.json").exists())]
    if missing:
        sys.exit("\n[!] Folder model belum ada / belum lengkap: " + ", ".join(missing) +
                 "\n    Ekstrak adminduk_chatbot_v4.zip dari Google Drive (hasil_v4/<tanggal>/),"
                 "\n    lalu salin folder qwen_adminduk_merged/ dan retriever_e5_small/ ke:\n    " + str(BASE) + "\n")
    import torch
    from sentence_transformers import SentenceTransformer
    from transformers import AutoModelForCausalLM, AutoTokenizer
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    print(f"Memuat model di {device} (±10–60 detik)...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(MODEL_DIR, dtype=dtype, local_files_only=True).to(device).eval()
    encoder = SentenceTransformer(str(RETRIEVER_DIR), device=device, local_files_only=True)
    retriever = rag.IntentRetriever(KB, SLANG, encoder, C=CFG["retriever_C"], prefix=CFG["prefix"])
    bot = rag.AsistenAdminduk(retriever, model, tokenizer, SYSTEM_PROMPT, rag.cjk_token_ids(tokenizer),
                              **CFG["pipeline"])
    return bot, device


if MOCK:
    import mock_bot
    bot, DEVICE = mock_bot.build(KB, SLANG, SYSTEM_PROMPT, CFG), "mock"
    print("\n*** MODE UJI (ADMINDUK_MOCK=1): jawaban TIDAK dari model AI, hanya untuk cek tampilan. ***\n", flush=True)
else:
    bot, DEVICE = load_real_bot()
lock = Lock()  # satu model dipakai bergantian agar aman

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024


def sumber_web(items):
    """Hanya tautan http(s) yang ditampilkan sebagai sumber; catatan internal KB disaring.
    Satu situs (domain) cukup ditampilkan sekali: tautan pertama dari domain itu yang dipakai."""
    out, seen = [], set()
    for s in items or []:
        if isinstance(s, str) and s.startswith(("http://", "https://")):
            label = urlparse(s).netloc.lower().removeprefix("www.")
            if label and label not in seen:
                seen.add(label)
                out.append({"url": s, "label": label})
    return out


def proses(payload):
    if not isinstance(payload, dict):
        return None, (jsonify(error="Kirim JSON dengan field 'pertanyaan'."), 400)
    try:
        with lock:
            out = bot.jawab(payload.get("pertanyaan"))
    except ValueError as err:
        return None, (jsonify(error=str(err)), 400)
    except Exception as err:  # jangan sampai server mati karena satu pertanyaan
        app.logger.exception("Gagal menjawab: %s", err)
        return None, (jsonify(error="Maaf, terjadi kendala saat menyiapkan jawaban. Coba lagi, ya."), 500)
    return out, None


@app.after_request
def cors(response):
    response.headers["Access-Control-Allow-Origin"] = os.environ.get("ALLOWED_ORIGIN", "*")
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    return response


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/chat")
def chat_page():
    return render_template("chat.html")


@app.get("/index.html")
def index_html():
    return redirect("/", code=301)


@app.get("/chat.html")
def chat_html():
    return redirect("/chat" + (("?" + request.query_string.decode()) if request.query_string else ""), code=301)


@app.get("/health")
def health():
    return jsonify(status="ok", device=DEVICE, intents=len(KB), mock=MOCK)


@app.route("/api/chat", methods=["POST", "OPTIONS"])
def api_chat():
    """Dipakai halaman web: hanya jawaban, sumber, dan saran (tanpa skor/mode/topik)."""
    if request.method == "OPTIONS":
        return ("", 204)
    t0 = time.perf_counter()
    out, err = proses(request.get_json(silent=True))
    if err:
        return err
    app.logger.info("mode=%s intent=%s skor=%s %.1fs", out.get("mode"), out.get("intent"), out.get("skor"),
                    time.perf_counter() - t0)
    return jsonify(jawaban=out["jawaban"], sumber=sumber_web(out.get("sumber")),
                   saran=[{"label": s["label"], "pertanyaan": s["pertanyaan"]} for s in out.get("saran", [])])


@app.route("/chat", methods=["POST", "OPTIONS"])
def chat_api_lama():
    """Kompatibel dengan versi sebelumnya (Postman/curl/notebook)."""
    if request.method == "OPTIONS":
        return ("", 204)
    out, err = proses(request.get_json(silent=True))
    if err:
        return err
    return jsonify(jawaban=out["jawaban"], intent=out["intent"], topik=out["topik"], sumber=out["sumber"],
                   skor=out["skor"], mode=out["mode"],
                   saran=[{"label": s["label"], "pertanyaan": s["pertanyaan"]} for s in out.get("saran", [])])


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return jsonify(error="Endpoint tidak ditemukan."), 404
    return render_template("404.html"), 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"Server siap: buka http://127.0.0.1:{port}", flush=True)
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)
