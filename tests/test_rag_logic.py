"""Uji logika koreksi retriever & saran dengan objek tiruan (tanpa model). Jalankan: python -m unittest discover tests"""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rag_adminduk as rag

KB = [
    {"intent": "ktp_hilang_syarat", "kategori": "layanan", "topik": "KTP hilang", "sumber": ["https://a.go.id/1"],
     "jawaban": "Syarat KTP hilang: surat kehilangan dari kepolisian dan fotokopi KK.",
     "contoh_pertanyaan": ["ktp ilang", "Apa persyaratan penerbitan KTP elektronik karena hilang?"]},
    {"intent": "ktp_rusak_syarat", "kategori": "layanan", "topik": "KTP rusak", "sumber": ["https://a.go.id/2"],
     "jawaban": "KTP rusak diganti dengan membawa KTP yang rusak dan KK.",
     "contoh_pertanyaan": ["KTP saya patah, bisa diganti nggak?"]},
    {"intent": "kk_baru", "kategori": "layanan", "topik": "KK baru", "sumber": ["https://a.go.id/3"],
     "jawaban": "KK baru dibuat dengan buku nikah dan surat pindah bila ada.",
     "contoh_pertanyaan": ["Bagaimana cara membuat KK baru setelah menikah?"]},
    {"intent": "klarifikasi_ktp", "kategori": "klarifikasi", "topik": "Klarifikasi", "sumber": ["pertanyaan klarifikasi"],
     "jawaban": "Maksudnya KTP yang mana dulu nih: baru, hilang, atau rusak?", "contoh_pertanyaan": ["ktp gmn"]},
    {"intent": "pii", "kategori": "data_pribadi", "topik": "Data pribadi", "sumber": [],
     "jawaban": "Maaf, saya tidak memproses data pribadi.", "contoh_pertanyaan": ["cek nik saya"]},
]


class FakeRetriever:
    def __init__(self, ranked):
        self.by_intent = {e["intent"]: e for e in KB}
        self.ranked = ranked
    def search(self, q, k=3):
        return self.ranked[:k]


def make_bot(ranked, llm_text, **kw):
    bot = rag.AsistenAdminduk(FakeRetriever(ranked), None, None, "sys", [], **kw)
    bot.generate = lambda messages: llm_text
    return bot

H = lambda *pairs: [{"intent": i, "skor": s} for i, s in pairs]
ANS = {e["intent"]: e["jawaban"] for e in KB}


class TestKoreksiRetriever(unittest.TestCase):
    def test_llm_sama_dengan_top1(self):
        out = make_bot(H(("ktp_hilang_syarat", .8), ("ktp_rusak_syarat", .1)), ANS["ktp_hilang_syarat"]).jawab("ktp ilang")
        self.assertEqual(out["mode"], "rag_llm"); self.assertEqual(out["intent"], "ktp_hilang_syarat")

    def test_retriever_yakin_llm_beda(self):  # skor >= trust -> ikuti retriever
        out = make_bot(H(("ktp_hilang_syarat", .6), ("ktp_rusak_syarat", .2)), ANS["ktp_rusak_syarat"]).jawab("ktp ilang")
        self.assertEqual(out["mode"], "koreksi_retriever"); self.assertEqual(out["jawaban"], ANS["ktp_hilang_syarat"])

    def test_skor_rendah_tapi_selisih_besar(self):  # aturan baru: gap >= switch_margin
        out = make_bot(H(("ktp_hilang_syarat", .25), ("ktp_rusak_syarat", .08), ("kk_baru", .05)),
                       ANS["ktp_rusak_syarat"]).jawab("ktp ilang")
        self.assertEqual(out["mode"], "koreksi_retriever"); self.assertEqual(out["jawaban"], ANS["ktp_hilang_syarat"])
        self.assertEqual(out["sumber"], ["https://a.go.id/1"])

    def test_skor_dekat_llm_boleh_pindah(self):  # ambigu -> LLM boleh pilih referensi lain
        out = make_bot(H(("ktp_hilang_syarat", .22), ("ktp_rusak_syarat", .18), ("kk_baru", .05)),
                       ANS["ktp_rusak_syarat"]).jawab("ktp ...")
        self.assertEqual(out["mode"], "rag_llm"); self.assertEqual(out["intent"], "ktp_rusak_syarat")
        self.assertEqual(out["sumber"], ["https://a.go.id/2"])

    def test_grounding_rendah(self):
        out = make_bot(H(("ktp_hilang_syarat", .8)), "jawaban ngawur tentang paspor dan sim").jawab("ktp ilang")
        self.assertEqual(out["mode"], "cadangan_referensi")


class TestSaran(unittest.TestCase):
    def test_skor_rendah_ada_saran(self):
        ranked = H(("ktp_hilang_syarat", .05), ("klarifikasi_ktp", .04), ("ktp_rusak_syarat", .03), ("pii", .02), ("kk_baru", .01))
        out = make_bot(ranked, "x").jawab("hmm")
        self.assertEqual(out["mode"], "klarifikasi_skor_rendah")
        self.assertEqual([s["intent"] for s in out["saran"]], ["ktp_hilang_syarat", "ktp_rusak_syarat", "kk_baru"])
        self.assertEqual(out["saran"][0]["pertanyaan"], "Apa persyaratan penerbitan KTP elektronik karena hilang?")

    def test_intent_klarifikasi_ada_saran(self):
        ranked = H(("klarifikasi_ktp", .7), ("ktp_hilang_syarat", .1), ("ktp_rusak_syarat", .1), ("kk_baru", .05))
        out = make_bot(ranked, ANS["klarifikasi_ktp"]).jawab("ktp gmn")
        self.assertEqual(out["intent"], "klarifikasi_ktp")
        self.assertEqual([s["intent"] for s in out["saran"]], ["ktp_hilang_syarat", "ktp_rusak_syarat", "kk_baru"])

    def test_yakin_tanpa_saran(self):
        out = make_bot(H(("ktp_hilang_syarat", .8), ("ktp_rusak_syarat", .1)), ANS["ktp_hilang_syarat"]).jawab("ktp ilang")
        self.assertEqual(out["saran"], [])

    def test_kebijakan_tanpa_saran(self):
        out = make_bot(H(("pii", .9), ("ktp_hilang_syarat", .05)), "x").jawab("cek nik 123")
        self.assertEqual(out["mode"], "aturan_kebijakan"); self.assertEqual(out["saran"], [])

    def test_saran_tidak_mengulang_intent_jawaban(self):
        ranked = H(("ktp_hilang_syarat", .2), ("ktp_rusak_syarat", .15), ("kk_baru", .1))
        out = make_bot(ranked, ANS["ktp_hilang_syarat"]).jawab("ktp")
        self.assertEqual(out["mode"], "rag_llm")
        self.assertNotIn("ktp_hilang_syarat", [s["intent"] for s in out["saran"]])
        self.assertTrue(out["saran"])


# ---- KB versi bahasa awam: 'jawaban' baru, 'jawaban_latih' = kalimat lama yang dipakai saat fine-tuning ----
KB2 = [dict(e) for e in KB]
KB2[0].update(jawaban="Untuk KTP-el (KTP elektronik) yang hilang, siapkan:\n1. Surat keterangan kehilangan dari kepolisian.\n2. Fotokopi KK (Kartu Keluarga).",
              jawaban_latih=KB[0]["jawaban"], label_saran="KTP saya hilang, apa saja syaratnya?")


class FakeRetriever2(FakeRetriever):
    def __init__(self, ranked):
        super().__init__(ranked); self.by_intent = {e["intent"]: e for e in KB2}


def make_bot2(ranked, llm_text, **kw):
    bot = rag.AsistenAdminduk(FakeRetriever2(ranked), None, None, "sys", [], **kw)
    bot.generate = lambda messages: llm_text
    return bot


class TestBahasaAwam(unittest.TestCase):
    def test_llm_pakai_kalimat_lama_diganti_teks_kb_baru(self):
        out = make_bot2(H(("ktp_hilang_syarat", .8), ("ktp_rusak_syarat", .1)), KB[0]["jawaban"]).jawab("ktp ilang")
        self.assertEqual(out["mode"], "rag_llm_teks_kb"); self.assertEqual(out["jawaban"], KB2[0]["jawaban"])

    def test_llm_menyalin_teks_baru_dipakai(self):
        out = make_bot2(H(("ktp_hilang_syarat", .8)), KB2[0]["jawaban"]).jawab("ktp ilang")
        self.assertEqual(out["mode"], "rag_llm"); self.assertEqual(out["jawaban"], KB2[0]["jawaban"])

    def test_grounding_lolos_untuk_kalimat_lama(self):  # tidak jatuh ke cadangan hanya karena gaya berbeda
        out = make_bot2(H(("ktp_hilang_syarat", .8)), KB[0]["jawaban"]).jawab("ktp ilang")
        self.assertNotEqual(out["mode"], "cadangan_referensi")

    def test_label_saran_dipakai(self):
        self.assertEqual(rag.AsistenAdminduk.label_saran(KB2[0]), "KTP saya hilang, apa saja syaratnya?")


class TestKBAsli(unittest.TestCase):
    """Cek file KB paket: fakta kunci tetap ada, panjang wajar, label saran ada untuk layanan."""
    @classmethod
    def setUpClass(cls):
        import json
        base = Path(__file__).resolve().parents[1]
        cls.kb = json.loads((base / "knowledge_base_adminduk_v4.json").read_text(encoding="utf-8"))

    def test_fakta_kunci_tetap_ada(self):
        for e in self.kb:
            for f in e.get("fakta_kunci", []):
                self.assertIn(f.lower(), e["jawaban"].lower(), e["intent"])

    def test_jawaban_latih_dan_label(self):
        for e in self.kb:
            self.assertTrue(e.get("jawaban_latih"), e["intent"])
            if e["kategori"] == "layanan":
                self.assertTrue(e.get("label_saran", "").endswith("?"), e["intent"])
            self.assertLess(len(e["jawaban"]), 800, e["intent"])


if __name__ == "__main__":
    unittest.main()
