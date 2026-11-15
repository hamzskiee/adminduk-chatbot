const toggle = document.querySelector("#menu-toggle"),
  menu = document.querySelector("#mobile-menu");
function closeMenu() {
  menu.classList.add("hidden");
  toggle.setAttribute("aria-expanded", "false");
  toggle.setAttribute("aria-label", "Buka navigasi");
}
toggle?.addEventListener("click", () => {
  const open = menu.classList.toggle("hidden") === false;
  toggle.setAttribute("aria-expanded", String(open));
  toggle.setAttribute("aria-label", open ? "Tutup navigasi" : "Buka navigasi");
});
menu
  ?.querySelectorAll("a")
  .forEach((a) => a.addEventListener("click", closeMenu));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeMenu();
});
const dialog = document.querySelector("#legal-dialog");
const legal = {
  privasi: [
    "Privasi",
    "Pertanyaanmu hanya dikirim ke server asisten Ruang Warga untuk dibuatkan jawaban. Isi percakapan tidak disimpan dan hilang saat halaman dimuat ulang. Tidak ada pelacakan. Jangan masukkan NIK, nomor KK, alamat lengkap, atau foto dokumen.",
  ],
  ketentuan: [
    "Ketentuan penggunaan",
    "Ruang Warga adalah proyek mahasiswa, bukan situs resmi Dukcapil. Jawaban disusun oleh AI dan bisa keliru. Jangan jadikan jawaban sebagai keputusan resmi. Pastikan syarat terbaru ke Disdukcapil (Dinas Kependudukan dan Pencatatan Sipil) setempat.",
  ],
};
document.querySelectorAll("[data-legal]").forEach((b) =>
  b.addEventListener("click", () => {
    const [t, c] = legal[b.dataset.legal];
    document.querySelector("#legal-title").textContent = t;
    document.querySelector("#legal-copy").textContent = c;
    dialog.showModal();
  }),
);
document.querySelectorAll("details").forEach((d) =>
  d.addEventListener("toggle", () => {
    if (d.open)
      document.querySelectorAll("details").forEach((o) => {
        if (o !== d) o.open = false;
      });
  }),
);
