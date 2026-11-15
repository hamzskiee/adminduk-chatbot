"""RAG adminduk v4: normalisasi bahasa gaul, retriever intent (embedding + TF-IDF karakter),
penyusunan prompt berreferensi, pelindung karakter CJK, dan pipeline jawab().
Dipakai bersama oleh notebook Colab dan app.py Flask (satu sumber kode)."""
import random
import re
import numpy as np

CJK_RE = re.compile(r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")
FALLBACK_ANSWER = ("Maaf, saya belum menangkap maksud pertanyaannya. Boleh dijelaskan lagi dokumen apa yang ingin diurus? "
                   "Saya bisa membantu soal KTP, KK (Kartu Keluarga), KIA (Kartu Identitas Anak), akta kelahiran, "
                   "akta kematian, IKD (KTP digital), dan pindah alamat.")
SYSTEM_PROMPT_NO_RAG = ("Kamu adalah asisten virtual layanan administrasi kependudukan (Dukcapil) di Indonesia. "
                        "Jawab dalam bahasa Indonesia yang sopan, singkat, dan langsung sesuai pertanyaan, termasuk jika pengguna "
                        "memakai bahasa gaul, singkatan, atau typo. Jangan mengarang syarat, biaya, atau aturan. "
                        "Jangan meminta atau memproses data pribadi.")  # hanya untuk pembanding tanpa RAG
POLICY_CATEGORIES = ("di_luar_cakupan", "data_pribadi")  # dijawab dengan teks baku, tidak lewat LLM


def normalize(text, slang):
    """Ubah teks gaul/typo ke bentuk baku: 'ktp gw ilang gmn' -> 'ktp saya hilang bagaimana'."""
    t = text.casefold()
    t = re.sub(r"(\w)\1{2,}", r"\1", t)  # 'ilaaang' -> 'ilang'
    for phrase, repl in slang.items():  # frasa multi-kata/berstrip lebih dulu
        if " " in phrase or "-" in phrase:
            t = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", f" {repl} ", t)
    out = []
    for tok in re.findall(r"[a-z0-9]+", t):
        rep = slang.get(tok, tok)
        out.extend(rep.split())
    return " ".join(out)


def word_f1(a, b):
    """Kemiripan kata (F1) dua teks; dipakai untuk menebak referensi mana yang dipakai jawaban."""
    wa, wb = re.findall(r"\w+", a.casefold()), re.findall(r"\w+", b.casefold())
    if not wa or not wb:
        return 0.0
    common = sum(min(wa.count(w), wb.count(w)) for w in set(wa))
    if common == 0:
        return 0.0
    p, r = common / len(wa), common / len(wb)
    return 2 * p * r / (p + r)


def ref_f1(text, entry):
    """Kemiripan jawaban model dengan entri KB. Dibandingkan dengan teks jawaban sekarang ('jawaban', versi bahasa
    awam) DAN teks yang dipakai saat fine-tuning ('jawaban_latih'), karena model dilatih dengan kalimat lama dan
    kadang masih menuliskannya. Nilai tertinggi yang dipakai."""
    s = word_f1(text, entry["jawaban"])
    if entry.get("jawaban_latih"):
        s = max(s, word_f1(text, entry["jawaban_latih"]))
    return s


def closest_intent(answer, kb_entries):
    """Intent di KB yang jawabannya paling mirip dengan teks jawaban model."""
    scores = [(ref_f1(answer, e), e["intent"]) for e in kb_entries]
    return max(scores)[1]


class IntentRetriever:
    """Retriever berbasis intent: memilih entri basis pengetahuan (KB) yang paling cocok.
    Gabungan dua 'pembaca' pada teks yang sudah dinormalisasi:
      1) makna kalimat  : embedding multilingual-e5-small + regresi logistik,
      2) ejaan/kata kunci: TF-IDF n-gram karakter (tahan typo) + regresi logistik.
    Probabilitas keduanya dirata-rata. Skor = probabilitas intent teratas (0-1)."""

    def __init__(self, kb, slang, encoder, C=20.0, prefix="query: "):
        self.kb, self.slang, self.encoder, self.C, self.prefix = kb, slang, encoder, C, prefix
        self.by_intent = {e["intent"]: e for e in kb}
        # contoh pertanyaan + label tombol saran (agar tombol "Apa maksud kamu ..." pasti kembali ke intent-nya)
        qs_of = lambda e: list(e["contoh_pertanyaan"]) + ([e["label_saran"]] if e.get("label_saran") else [])
        questions = [q for e in kb for q in qs_of(e)]
        labels = [e["intent"] for e in kb for _ in qs_of(e)]
        self.extra_text = [normalize(e["topik"], slang) for e in kb]  # kosakata topik untuk TF-IDF
        self.fit(questions, labels)

    def embed(self, texts_norm):
        return self.encoder.encode([self.prefix + t for t in texts_norm], normalize_embeddings=True,
                                   convert_to_numpy=True, batch_size=64, show_progress_bar=False)

    def _fit_models(self, norm_texts, labels, emb):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True)
        tfidf.fit(list(norm_texts) + self.extra_text)
        clf_emb = LogisticRegression(C=self.C, max_iter=5000).fit(emb, labels)
        clf_txt = LogisticRegression(C=self.C, max_iter=5000).fit(tfidf.transform(norm_texts), labels)
        return tfidf, clf_emb, clf_txt

    def fit(self, questions, labels):
        norm = [normalize(q, self.slang) for q in questions]
        self.tfidf, self.clf_emb, self.clf_txt = self._fit_models(norm, labels, self.embed(norm))
        self.classes = self.clf_emb.classes_

    @staticmethod
    def _proba(models, norm_texts, emb):
        tfidf, clf_emb, clf_txt = models
        return (clf_emb.predict_proba(emb) + clf_txt.predict_proba(tfidf.transform(norm_texts))) / 2

    def _hits(self, proba_row, classes, k):
        order = np.argsort(-proba_row)[:k]
        return [{"intent": str(classes[i]), "skor": float(proba_row[i])} for i in order]

    def search(self, question, k=3):
        norm = [normalize(question, self.slang)]
        proba = self._proba((self.tfidf, self.clf_emb, self.clf_txt), norm, self.embed(norm))[0]
        return self._hits(proba, self.classes, k)

    def search_many(self, questions, k=3):
        norm = [normalize(q, self.slang) for q in questions]
        proba = self._proba((self.tfidf, self.clf_emb, self.clf_txt), norm, self.embed(norm))
        return [self._hits(p, self.classes, k) for p in proba]

    def cross_val_search(self, questions, labels, k=3, folds=5, seed=42):
        """Prediksi 'jujur' untuk data latih: tiap pertanyaan diprediksi oleh model yang TIDAK melihatnya.
        Dipakai membuat referensi latih yang realistis (kadang salah urutan / salah tebak)."""
        from sklearn.model_selection import StratifiedKFold
        norm = [normalize(q, self.slang) for q in questions]
        emb = self.embed(norm)
        labels = np.array(labels)
        # Intent dengan contoh < folds tetap ikut latih di semua fold (tidak bisa distratifikasi).
        counts = {c: (labels == c).sum() for c in set(labels)}
        strat = np.array([l if counts[l] >= folds else "__langka__" for l in labels])
        results = [None] * len(questions)
        skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
        for tr_idx, te_idx in skf.split(norm, strat):
            rare = [i for i in te_idx if counts[labels[i]] < 2]  # satu-satunya contoh: tetap dilatih
            tr_all = np.concatenate([tr_idx, np.array(rare, dtype=int)])
            models = self._fit_models([norm[i] for i in tr_all], labels[tr_all], emb[tr_all])
            proba = self._proba(models, [norm[i] for i in te_idx], emb[te_idx])
            for row, i in zip(proba, te_idx):
                results[i] = self._hits(row, models[1].classes_, k)
        return results


def build_user_prompt(question, ref_entries):
    lines = ["REFERENSI:"]
    for i, e in enumerate(ref_entries, 1):
        # Satu referensi = satu baris (seperti saat fine-tuning); baris baru/daftar di KB dirapatkan jadi spasi.
        lines.append(f"[{i}] {e['topik']}: {' '.join(e['jawaban'].split())}")
    lines += ["", f"PERTANYAAN: {question.strip()}"]
    return "\n".join(lines)


def build_rag_examples(rows, hits_list, by_intent, system_prompt, copies=1, shuffle_prob=0.5,
                       force_gold=True, seed=42):
    """Ubah baris dataset menjadi percakapan berreferensi (retrieval-augmented fine-tuning).
    - Referensi = top-k hasil retriever (bisa berisi intent yang mirip tapi salah -> model belajar memilih).
    - force_gold=True (khusus train): jika jawaban benar tidak terambil, ganti referensi terakhir dengannya.
    - Urutan referensi diacak sebagian agar model tidak sekadar menyalin referensi nomor 1."""
    rng = random.Random(seed)
    out = []
    for copy in range(copies):
        for row, hits in zip(rows, hits_list):
            intents = [h["intent"] for h in hits]
            gold_retrieved = row["intent"] in intents
            if force_gold and not gold_retrieved:
                intents[-1] = row["intent"]
            if force_gold and (copy > 0 or rng.random() < shuffle_prob):
                rng.shuffle(intents)
            refs = [by_intent[i] for i in intents]
            out.append({
                "messages": [{"role": "system", "content": system_prompt},
                             {"role": "user", "content": build_user_prompt(row["pertanyaan"], refs)},
                             {"role": "assistant", "content": row["jawaban"]}],
                "id": row["id"], "intent": row["intent"], "kategori": row["kategori"],
                "variation_type": row["variation_type"], "fakta_kunci": row["fakta_kunci"],
                "posisi_benar": intents.index(row["intent"]) + 1 if row["intent"] in intents else 0,
                "benar_dari_retriever": gold_retrieved})
    return out


def cjk_token_ids(tokenizer):
    """ID token yang memuat aksara Tionghoa/Jepang/Korea atau byte awalnya (UTF-8 lead byte 0xE3-0xEF).
    Token ini dilarang saat generate sehingga jawaban tidak mungkin berisi huruf Cina."""
    from transformers.models.gpt2.tokenization_gpt2 import bytes_to_unicode
    byte_dec = {v: k for k, v in bytes_to_unicode().items()}
    special = set(tokenizer.all_special_ids)
    banned = []
    for tid in range(len(tokenizer)):
        if tid in special:
            continue
        tok = tokenizer.convert_ids_to_tokens(tid)
        try:
            raw = bytes(byte_dec[c] for c in tok)
        except (KeyError, TypeError):
            continue
        if any(0xE3 <= b <= 0xEF for b in raw) or CJK_RE.search(raw.decode("utf-8", "ignore")):
            banned.append(tid)
    return banned


class AsistenAdminduk:
    """Pipeline lengkap: retrieval -> aturan keamanan -> LLM dengan referensi -> pemeriksaan akhir.

    Tambahan versi web:
      - switch_margin: LLM hanya boleh "pindah" ke referensi lain bila skor retriever untuk referensi itu
        cukup dekat dengan skor top-1 (selisih < switch_margin). Jika retriever jelas lebih yakin pada top-1,
        jawaban resmi top-1 yang dipakai (mode 'koreksi_retriever').
      - saran: daftar pertanyaan alternatif ("Apa maksud kamu ...") untuk mode klarifikasi / skor rendah."""

    def __init__(self, retriever, model, tokenizer, system_prompt, suppress_ids, top_k=3,
                 min_confidence=0.10, policy_confidence=0.30, trust_confidence=0.30, min_grounding=0.35,
                 max_new_tokens=200, repetition_penalty=1.0, max_input_tokens=1024,
                 switch_margin=0.10, saran_confidence=0.25, saran_k=3, min_copy_similarity=0.80):
        self.r, self.model, self.tok, self.system = retriever, model, tokenizer, system_prompt
        self.suppress_ids, self.top_k, self.min_conf = suppress_ids, top_k, min_confidence
        self.policy_conf, self.trust_conf, self.min_grounding = policy_confidence, trust_confidence, min_grounding
        self.max_new_tokens, self.rep, self.max_input = max_new_tokens, repetition_penalty, max_input_tokens
        self.switch_margin, self.saran_conf, self.saran_k = switch_margin, saran_confidence, saran_k
        self.min_copy = min_copy_similarity

    def generate(self, messages):
        import torch
        inputs = self.tok.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                              return_dict=True, return_tensors="pt")
        if inputs["input_ids"].shape[1] > self.max_input:
            raise ValueError("Pertanyaannya terlalu panjang. Coba diringkas, ya.")
        inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
        with torch.inference_mode():
            out = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False, num_beams=1,
                                      repetition_penalty=self.rep, suppress_tokens=self.suppress_ids or None,
                                      eos_token_id=self.tok.eos_token_id, pad_token_id=self.tok.pad_token_id,
                                      temperature=None, top_p=None, top_k=None)
        return self.tok.decode(out[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()

    def jawab(self, pertanyaan, use_rag=True, use_guard=True):
        if not isinstance(pertanyaan, str) or not pertanyaan.strip():
            raise ValueError("Tulis pertanyaanmu terlebih dahulu, ya.")
        if len(pertanyaan) > 1000:
            raise ValueError("Pertanyaannya terlalu panjang (maksimal 1000 huruf). Coba diringkas, ya.")
        if not use_rag:  # mode pembanding: LLM tanpa referensi
            text = self.generate([{"role": "system", "content": SYSTEM_PROMPT_NO_RAG},
                                  {"role": "user", "content": pertanyaan.strip()}])
            if use_guard and CJK_RE.search(text):
                text = CJK_RE.sub("", text)
            return {"jawaban": text, "intent": None, "topik": None, "skor": None, "sumber": [], "mode": "tanpa_rag",
                    "saran": []}
        # Satu kali retrieval dengan peringkat lebih panjang: top_k untuk prompt, sisanya untuk saran.
        ranked = self.r.search(pertanyaan, k=max(self.top_k, 15))
        return self.jawab_dengan_hits(pertanyaan, ranked[:self.top_k], use_guard, ranked=ranked)

    # ---------- saran "Apa maksud kamu ..." ----------
    @staticmethod
    def label_saran(entry):
        """Label tombol saran: 'label_saran' (kalimat sederhana) bila ada, jika tidak pertanyaan contoh yang rapi."""
        if entry.get("label_saran"):
            return entry["label_saran"].strip()
        qs = entry.get("contoh_pertanyaan") or []
        for q in qs:
            if q.strip().endswith("?") and len(q.split()) >= 4:
                return q.strip()
        return qs[0].strip() if qs else entry["topik"]

    def buat_saran(self, ranked, exclude=()):
        """Ambil intent layanan teratas (bukan klarifikasi/kebijakan) dari peringkat retriever."""
        out, seen = [], set(exclude)
        for h in ranked:
            e = self.r.by_intent.get(h["intent"])
            if e is None or e["intent"] in seen or e.get("kategori") != "layanan":
                continue
            seen.add(e["intent"])
            q = self.label_saran(e)
            out.append({"label": q, "pertanyaan": q, "intent": e["intent"]})
            if len(out) >= self.saran_k:
                break
        return out

    def _dengan_saran(self, res, ranked):
        """Tambahkan field 'saran' bila sistem bertanya balik atau kurang yakin."""
        mode, kat = res.get("mode"), None
        if res.get("intent") in self.r.by_intent:
            kat = self.r.by_intent[res["intent"]].get("kategori")
        perlu = (mode == "klarifikasi_skor_rendah" or kat == "klarifikasi"
                 or (mode not in ("aturan_kebijakan",) and kat not in POLICY_CATEGORIES
                     and res.get("skor") is not None and res["skor"] < self.saran_conf))
        res["saran"] = self.buat_saran(ranked or [], exclude=[res.get("intent")]) if perlu else []
        return res

    def jawab_dengan_hits(self, pertanyaan, hits, use_guard=True, llm_text=None, ranked=None):
        """llm_text: jawaban LLM yang sudah dihitung (dipakai evaluasi agar tidak generate dua kali).
        ranked: peringkat retriever yang lebih panjang (opsional) untuk membuat saran."""
        res = self._jawab_inti(pertanyaan, hits, use_guard, llm_text)
        return self._dengan_saran(res, ranked if ranked is not None else hits)

    def _jawab_inti(self, pertanyaan, hits, use_guard=True, llm_text=None):
        top = self.r.by_intent[hits[0]["intent"]]
        skor_of = {h["intent"]: h["skor"] for h in hits}
        result = {"intent": top["intent"], "topik": top["topik"], "skor": round(hits[0]["skor"], 3),
                  "sumber": top["sumber"], "kandidat": [h["intent"] for h in hits]}
        if use_guard and hits[0]["skor"] < self.min_conf:
            return {**result, "jawaban": FALLBACK_ANSWER, "intent": None, "topik": None, "sumber": [],
                    "mode": "klarifikasi_skor_rendah"}
        if use_guard and top["kategori"] in POLICY_CATEGORIES and hits[0]["skor"] >= self.policy_conf:
            return {**result, "jawaban": top["jawaban"], "mode": "aturan_kebijakan"}
        refs = [self.r.by_intent[h["intent"]] for h in hits]
        text = llm_text if llm_text is not None else self.generate(
            [{"role": "system", "content": self.system},
             {"role": "user", "content": build_user_prompt(pertanyaan, refs)}])
        if not use_guard:
            return {**result, "jawaban": text, "mode": "rag_llm_tanpa_aturan"}
        if not text or CJK_RE.search(text):
            return {**result, "jawaban": top["jawaban"], "mode": "cadangan_referensi"}
        # Pemeriksaan grounding: jawaban harus bersandar pada salah satu referensi.
        best = max(refs, key=lambda e: ref_f1(text, e))
        if ref_f1(text, best) < self.min_grounding:
            return {**result, "jawaban": top["jawaban"], "mode": "cadangan_referensi"}
        if best["intent"] != top["intent"]:
            # LLM memakai referensi lain dari top-1 retriever. Ikuti retriever bila:
            #  (a) retriever cukup yakin (skor >= trust_confidence), atau
            #  (b) skor referensi pilihan LLM jauh di bawah top-1 (selisih >= switch_margin).
            gap = hits[0]["skor"] - skor_of.get(best["intent"], 0.0)
            if hits[0]["skor"] >= self.trust_conf or gap >= self.switch_margin:
                return {**result, "jawaban": top["jawaban"], "mode": "koreksi_retriever"}
        base = {**result, "intent": best["intent"], "topik": best["topik"], "sumber": best["sumber"],
                "jawaban_llm": text}
        # Teks KB sudah ditulis ulang dengan bahasa awam (dengan baris baru/daftar bernomor), sedangkan model
        # dilatih dengan kalimat lama dan menulis satu paragraf. Karena itu yang DITAMPILKAN adalah teks KB terbaru
        # dari referensi yang dipilih model (intent pilihan LLM, sudah lolos grounding & koreksi retriever):
        #   - mode 'rag_llm'        : keluaran model hampir sama dengan teks baru (hanya dirapikan tata letaknya)
        #   - mode 'rag_llm_teks_kb': keluaran model masih memakai kalimat lama / terpotong -> diganti teks baru
        # min_copy_similarity=0 mematikan perilaku ini (keluaran model ditampilkan apa adanya).
        if not self.min_copy:
            return {**base, "jawaban": text, "mode": "rag_llm"}
        f_baru = word_f1(text, best["jawaban"])
        f_lama = word_f1(text, best["jawaban_latih"]) if best.get("jawaban_latih") else 0.0
        mode = "rag_llm" if (f_baru >= self.min_copy and f_baru >= f_lama) else "rag_llm_teks_kb"
        return {**base, "jawaban": best["jawaban"], "mode": mode}
