"use strict";
(() => {
  const $ = (s) => document.querySelector(s);
  const input = $("#question"),
    form = $("#chat-form"),
    send = $("#send-button");
  const messages = $("#messages"),
    empty = $("#empty-state"),
    scroll = $("#conversation-scroll");
  const error = $("#chat-error"),
    sidebar = $("#sidebar"),
    scrim = $("#sidebar-scrim");
  let busy = false,
    session = 0;
  const assistantIcon =
    '<span class="inline-flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm"><svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5a8.5 8.5 0 0 1-12.3 7.6L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5Z"/></svg></span>';
  const userIcon =
    '<span class="hidden size-8 shrink-0 items-center justify-center rounded-full border bg-muted sm:inline-flex"><svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M20 21a8 8 0 0 0-16 0M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z"/></svg></span>';
  function sync() {
    send.disabled = busy || !input.value.trim();
  }
  function showError(text) {
    error.textContent = text;
    error.classList.toggle("hidden", !text);
  }
  function closeSidebar() {
    sidebar.classList.add("hidden");
    scrim.classList.add("hidden");
    $("#open-sidebar").setAttribute("aria-expanded", "false");
  }
  $("#open-sidebar").addEventListener("click", () => {
    sidebar.classList.remove("hidden");
    sidebar.classList.add("flex");
    scrim.classList.remove("hidden");
    $("#open-sidebar").setAttribute("aria-expanded", "true");
    $("#close-sidebar").focus();
  });
  $("#close-sidebar").addEventListener("click", closeSidebar);
  scrim.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSidebar();
  });
  function scrollEnd() {
    scroll.scrollTo({
      top: scroll.scrollHeight,
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
  }
  function message(text, role) {
    const article = document.createElement("article");
    article.className =
      "flex items-start gap-3 " + (role === "user" ? "justify-end" : "");
    article.setAttribute(
      "aria-label",
      role === "user" ? "Pertanyaanmu" : "Balasan Ruang Warga",
    );
    const wrap = document.createElement("div");
    wrap.className = "min-w-0 max-w-[88%] sm:max-w-[85%]";
    const label = document.createElement("p");
    label.className =
      "mb-2 text-xs font-medium " +
      (role === "user" ? "text-right text-muted-foreground" : "");
    label.textContent = role === "user" ? "Kamu" : "Ruang Warga";
    const bubble = document.createElement("div");
    bubble.className =
      "whitespace-pre-line break-words rounded-xl p-4 text-sm leading-relaxed " +
      (role === "user"
        ? "rounded-tr-sm bg-primary text-primary-foreground"
        : "rounded-tl-sm border border-border/50 bg-muted/50");
    bubble.textContent = text;
    wrap.append(label, bubble);
    if (role === "assistant") {
      article.insertAdjacentHTML("beforeend", assistantIcon);
      article.append(wrap);
    } else {
      article.append(wrap);
      article.insertAdjacentHTML("beforeend", userIcon);
    }
    article.classList.add("msg-in");
    article.dataset.role = role;
    messages.append(article);
    scrollEnd();
    return article;
  }
  const API = "/api/chat",
    TIMEOUT_MS = 120000;
  let controller = null,
    slowTimer = null;
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  // Sumber hukum/rujukan: hanya tautan http(s) dari server, ditampilkan sebagai teks (tanpa HTML).
  function addSources(article, sumber) {
    const seen = new Set();
    const list = (sumber || [])
      .filter((s) => s && /^https?:\/\//.test(s.url || ""))
      .filter((s) => {
        const k = String(s.label || s.url)
          .toLowerCase()
          .replace(/^www\./, "");
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      }); // satu situs cukup sekali
    if (!list.length) return;
    const wrap = article.querySelector(".min-w-0");
    const box = el(
      "div",
      "mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 px-1 text-xs text-muted-foreground",
    );
    box.append(el("span", "font-medium", "Sumber:"));
    list.slice(0, 3).forEach((s, i) => {
      const a = el(
        "a",
        "underline decoration-dotted underline-offset-4 hover:text-foreground",
        s.label || s.url,
      );
      a.href = s.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.title = s.url;
      box.append(a);
      if (i < Math.min(list.length, 3) - 1) box.append(el("span", "", " · "));
    });
    wrap.append(box);
  }
  // "Apa maksud kamu …": tombol saran yang langsung mengirim pertanyaan saat diklik.
  function addSuggestions(article, saran) {
    const list = (saran || []).filter((s) => s && s.pertanyaan);
    if (!list.length) return;
    const wrap = article.querySelector(".min-w-0");
    const box = el("div", "saran mt-3 px-1");
    box.append(
      el(
        "p",
        "mb-2 text-xs font-medium text-muted-foreground",
        "Apa maksud kamu …",
      ),
    );
    const row = el("div", "flex flex-col items-start gap-2");
    list.slice(0, 3).forEach((s) => {
      const btn = el(
        "button",
        "saran-btn inline-flex max-w-full items-center gap-2 rounded-lg border bg-background px-3 py-2 text-left text-xs shadow-sm transition-colors duration-300 hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60",
      );
      btn.type = "button";
      btn.dataset.saran = s.pertanyaan;
      btn.append(el("span", "min-w-0", s.label || s.pertanyaan));
      btn.insertAdjacentHTML(
        "beforeend",
        '<svg class="size-3.5 shrink-0 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 17 17 7M7 7h10v10"/></svg>',
      );
      btn.addEventListener("click", () => {
        if (!busy) ask(s.pertanyaan);
      });
      row.append(btn);
    });
    box.append(row);
    wrap.append(box);
  }
  function addRetry(article, q) {
    const wrap = article.querySelector(".min-w-0");
    const btn = el(
      "button",
      "mt-2 inline-flex items-center gap-2 rounded-lg border bg-background px-3 py-1.5 text-xs shadow-sm hover:bg-muted",
      "Coba kirim lagi",
    );
    btn.type = "button";
    btn.addEventListener("click", () => {
      if (busy) return;
      article.remove();
      ask(q, true);
    });
    wrap.append(btn);
  }
  function setBusy(v) {
    busy = v;
    document.querySelectorAll("[data-question],.saran-btn").forEach((b) => {
      b.disabled = v;
    });
    input.setAttribute("aria-busy", v ? "true" : "false");
    sync();
  }
  async function callApi(q, signal) {
    const res = await fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pertanyaan: q }),
      signal,
    });
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      data = null;
    }
    if (!res.ok) {
      const e = new Error(
        (data && data.error) ||
          "Maaf, asisten sedang mengalami kendala (kode " +
            res.status +
            "). Coba lagi sebentar lagi, ya.",
      );
      e.server = true;
      throw e;
    }
    if (!data || typeof data.jawaban !== "string")
      throw new Error(
        "Maaf, jawaban tidak bisa ditampilkan. Coba kirim lagi, ya.",
      );
    return data;
  }
  async function ask(text, isRetry) {
    if (busy) return;
    const q = String(text || "").trim();
    if (!q) {
      showError("Tulis pertanyaanmu terlebih dahulu, ya.");
      return;
    }
    if (q.length > 600) {
      showError("Pertanyaan terlalu panjang. Ringkas hingga 600 karakter, ya.");
      return;
    }
    if (/\d{16}/.test(q.replace(/[\s-]/g, ""))) {
      showError(
        "Sepertinya ada nomor NIK atau nomor KK (16 angka). Hapus dulu sebelum mengirim, ya.",
      );
      input.value = q;
      sync();
      return;
    }
    showError("");
    empty.classList.add("hidden");
    messages.classList.remove("hidden");
    closeSidebar();
    if (!isRetry) message(q, "user");
    input.value = "";
    setBusy(true);
    const typing = message("", "assistant");
    typing.setAttribute("aria-label", "Asisten sedang menyiapkan balasan");
    typing.dataset.typing = "1";
    const bubble = typing.querySelector(".whitespace-pre-line");
    bubble.innerHTML =
      '<span class="sr-only">Menyiapkan balasan...</span><span class="inline-flex items-center gap-3 py-1" aria-hidden="true"><span class="inline-flex gap-1.5"><span class="typing-dot size-1.5 rounded-full bg-muted-foreground"></span><span class="typing-dot size-1.5 rounded-full bg-muted-foreground"></span><span class="typing-dot size-1.5 rounded-full bg-muted-foreground"></span></span><span class="shimmer text-xs font-medium" data-status>Menyiapkan jawaban</span></span>';
    scrollEnd();
    const current = session;
    controller = new AbortController();
    const ctl = controller;
    const timeout = setTimeout(() => ctl.abort("timeout"), TIMEOUT_MS);
    slowTimer = setTimeout(() => {
      const st = typing.querySelector("[data-status]");
      if (st) st.textContent = "Masih menyusun jawaban, sebentar ya";
    }, 8000);
    let data = null,
      err = null;
    try {
      data = await callApi(q, ctl.signal);
    } catch (e) {
      err = e;
    }
    clearTimeout(timeout);
    clearTimeout(slowTimer);
    if (current !== session) return; // percakapan sudah di-reset
    typing.remove();
    controller = null;
    if (data) {
      const art = message(
        data.jawaban.trim() ||
          "Maaf, jawaban kosong. Coba tanyakan dengan kalimat lain, ya.",
        "assistant",
      );
      addSources(art, data.sumber);
      addSuggestions(art, data.saran);
    } else {
      let msg;
      if (err && err.server) msg = err.message;
      else if (ctl.signal.aborted)
        msg =
          "Jawaban terlalu lama. Asisten mungkin masih bersiap, coba kirim lagi sebentar lagi.";
      else
        msg =
          "Tidak bisa terhubung ke asisten. Coba lagi sebentar lagi. (Untuk pengelola: pastikan python app.py masih berjalan.)";
      const art = message(msg, "assistant");
      art.dataset.error = "1";
      art.querySelector(".whitespace-pre-line").classList.add("border-dashed");
      addRetry(art, q);
    }
    setBusy(false);
    scrollEnd();
    if (!matchMedia("(pointer: coarse)").matches) input.focus();
  }
  function reset() {
    session++;
    if (controller) {
      controller.abort("reset");
      controller = null;
    }
    clearTimeout(slowTimer);
    setBusy(false);
    messages.replaceChildren();
    messages.classList.add("hidden");
    empty.classList.remove("hidden");
    input.value = "";
    showError("");
    sync();
    closeSidebar();
    scroll.scrollTop = 0;
    history.replaceState(null, "", location.pathname);
    input.focus();
  }
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    ask(input.value);
  });
  input.addEventListener("input", () => {
    sync();
    showError("");
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      ask(input.value);
    }
  });
  document.querySelectorAll("[data-question]").forEach((button) =>
    button.addEventListener("click", () => {
      if (!busy) ask(button.dataset.question);
    }),
  );
  $("#reset-chat").addEventListener("click", reset);
  $("#new-chat").addEventListener("click", reset);
  // Text-only render is deliberately used for every visitor message. No HTML injection.
  const q = new URLSearchParams(location.search).get("q");
  if (q) ask(q);
})();
