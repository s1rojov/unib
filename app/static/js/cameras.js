// Kameralar nazorati: jonli ko'rish (kadrlar davriy so'raladi, faqat brauzer xotirasida).
(function () {
  "use strict";
  const FRAME_MS = 250; // ~4 kadr/s
  const tiles = Array.from(document.querySelectorAll(".cam-tile"));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function setup(tile) {
    const btn = tile.querySelector(".js-live");
    if (!btn) return;
    const img = tile.querySelector("img");
    const ph = tile.querySelector(".cam-placeholder");
    const stats = tile.querySelector(".cam-stats");
    const url = tile.dataset.snapshot;
    let live = false;
    let pausedByHide = false;
    let prevUrl = null;

    function placeholder(text) {
      ph.textContent = text;
      ph.hidden = false;
    }

    function showStats(h) {
      const faces = +h.get("X-Faces") || 0;
      const ok = +h.get("X-Faces-Ok") || 0;
      const rec = +h.get("X-Recognized") || 0;
      const minS = h.get("X-Min-Size");
      const minPx = h.get("X-Min-Face-Px");
      const src = h.get("X-Source") === "session" ? "sessiya tahlili (tanish bilan)" : "tekshiruv (faqat yuz sifati)";
      const parts = [
        `${h.get("X-Width")}×${h.get("X-Height")}`,
        `yuzlar: <b>${faces}</b>`,
        `talabga mos: <b>${ok}</b>`,
      ];
      if (h.get("X-Source") === "session") parts.push(`tanilgan: <b>${rec}</b>`);
      if (minS) parts.push(`eng kichik: <b>${minS}px</b> (kerak ≥ ${minPx}px)`);
      parts.push(`<span class="muted">${src}</span>`);
      stats.innerHTML = parts.join(" · ");
    }

    async function loop() {
      while (live) {
        const t0 = performance.now();
        try {
          const r = await fetch(url + "?t=" + Date.now(), { cache: "no-store", credentials: "same-origin" });
          const ctype = r.headers.get("Content-Type") || "";
          if (r.ok && ctype.startsWith("image/")) {
            const blob = await r.blob();
            if (!live) break;
            const u = URL.createObjectURL(blob);
            img.src = u;
            if (prevUrl) URL.revokeObjectURL(prevUrl);
            prevUrl = u;
            img.hidden = false;
            ph.hidden = true;
            showStats(r.headers);
          } else {
            const d = await r.json().catch(() => ({}));
            if (r.status === 403 && !d.error) { location.reload(); return; }
            if (d.stop) { stop(d.error); return; } // sessiya yakunlangan / ko'rish taqiqlangan — so'rovlar to'xtatiladi
            img.hidden = true;
            placeholder(d.error || "Kadr olinmadi");
            stats.textContent = "";
            await sleep(1000);
          }
        } catch (e) {
          placeholder("Server bilan aloqa yoʻq");
          await sleep(1500);
        }
        await sleep(Math.max(0, FRAME_MS - (performance.now() - t0)));
      }
    }

    function start() {
      if (live) return;
      live = true;
      btn.textContent = "■ Kamerani yashirish";
      placeholder("Kameraga ulanmoqda…");
      loop();
    }

    function stop(text) {
      live = false;
      btn.textContent = "▶ Kamerani koʻrsatish";
      img.hidden = true;
      if (prevUrl) { URL.revokeObjectURL(prevUrl); prevUrl = null; }
      img.removeAttribute("src");
      placeholder(text || "Jonli koʻrish oʻchiq");
      stats.textContent = "";
    }

    btn.addEventListener("click", () => (live ? stop() : start()));
    // Sahifa yashirilganda kamerani band qilib turmaslik uchun to'xtatiladi
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && live) { pausedByHide = true; stop("Pauza (sahifa yashirin)"); }
      else if (!document.hidden && pausedByHide) { pausedByHide = false; start(); }
    });
    tile._isLive = () => live;
  }

  tiles.forEach(setup);
  if (tiles.length === 1) {
    const b = tiles[0].querySelector(".js-live");
    if (b) b.click(); // bitta kamera bo'lsa jonli ko'rish darhol yoqiladi
  }

  // Navbatdagi tekshiruv natijasini kutish (odatda 1–3 s) — tayyor bo'lgach sahifa yangilanadi
  const checks = document.getElementById("checks");
  if (checks && checks.dataset.pending === "1") setTimeout(() => location.reload(), 3000);
})();
