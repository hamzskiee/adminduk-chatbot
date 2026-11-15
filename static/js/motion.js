/* Shared motion layer. Vanilla ports of Aceternity UI (Text Generate Effect, Card Spotlight, Moving Border, Spotlight + Background Grid), 21st.dev (Blur Reveal, accordion). */
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches,
    root = document.documentElement;
  root.classList.add("js");
  const hero = document.querySelector("main section");
  const h1 = hero && document.querySelector("[data-hero] h1, main section h1");
  if (hero && h1 && !document.querySelector("#chat-form")) {
    hero.classList.add("relative");
    hero.style.isolation = "isolate";
    hero.insertAdjacentHTML(
      "afterbegin",
      '<div class="hero-grid" aria-hidden="true"></div><div class="hero-spot" aria-hidden="true"></div>',
    );
    let i = 0;
    const walk = (n) => {
      [...n.childNodes].forEach((c) => {
        if (c.nodeType === 3 && c.textContent.trim()) {
          const f = document.createDocumentFragment();
          c.textContent.split(/(\s+)/).forEach((w) => {
            if (!w) return;
            if (/^\s+$/.test(w)) {
              f.append(w);
              return;
            }
            const s = document.createElement("span");
            s.className = "tg-word";
            s.style.setProperty("--d", i++ * 90 + "ms");
            s.textContent = w;
            f.append(s);
          });
          c.replaceWith(f);
        } else if (c.nodeType === 1) walk(c);
      });
    };
    h1.setAttribute("aria-label", h1.textContent.replace(/\s+/g, " ").trim());
    walk(h1);
    let el = h1.nextElementSibling,
      k = 0;
    while (el) {
      el.classList.add("hero-enter");
      el.style.setProperty("--d", i * 90 + 150 + k++ * 120 + "ms");
      el = el.nextElementSibling;
    }
    const cta = hero.querySelector("a.bg-primary");
    if (cta) cta.classList.add("moving-border");
  }
  document.querySelectorAll("main section").forEach((s, si) => {
    if (s === hero && h1) return;
    [...s.querySelectorAll(":scope > *, :scope > div > *")]
      .slice(0, 24)
      .forEach((e, j) => {
        if (e.closest("[data-reveal]")) return;
        e.setAttribute("data-reveal", "");
        e.style.setProperty("--d", Math.min(j * 80, 400) + "ms");
      });
  });
  document
    .querySelectorAll(
      'main section [class*="rounded-xl"].border, main section [class*="rounded-2xl"].border, main section li.border',
    )
    .forEach((c) => {
      c.classList.add("spot");
      c.addEventListener("pointermove", (e) => {
        const r = c.getBoundingClientRect();
        c.style.setProperty("--mx", e.clientX - r.left + "px");
        c.style.setProperty("--my", e.clientY - r.top + "px");
      });
    });
  const show = (e) => e.classList.add("is-in");
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (es) =>
        es.forEach((en) => {
          if (en.isIntersecting) {
            show(en.target);
            io.unobserve(en.target);
          }
        }),
      { rootMargin: "0px 0px -8% 0px", threshold: 0.1 },
    );
    document.querySelectorAll("[data-reveal]").forEach((e) => io.observe(e));
  } else document.querySelectorAll("[data-reveal]").forEach(show);
  /* FAQ: animate body open and close */
  document.querySelectorAll("details").forEach((d) => {
    const sum = d.querySelector("summary");
    if (!sum) return;
    const body = document.createElement("div");
    body.className = "faq-body";
    const inner = document.createElement("div");
    [...d.childNodes].filter((n) => n !== sum).forEach((n) => inner.append(n));
    body.append(inner);
    d.append(body);
    if (d.open) body.classList.add("is-open");
    sum.addEventListener("click", (e) => {
      if (reduce) return;
      e.preventDefault();
      if (d.open) {
        body.classList.remove("is-open");
        setTimeout(() => {
          d.open = false;
        }, 350);
      } else {
        d.open = true;
        d.dispatchEvent(new Event("toggle"));
        requestAnimationFrame(() =>
          requestAnimationFrame(() => body.classList.add("is-open")),
        );
      }
    });
    d.addEventListener("toggle", () => {
      if (d.open) requestAnimationFrame(() => body.classList.add("is-open"));
      else body.classList.remove("is-open");
    });
  });
})();
