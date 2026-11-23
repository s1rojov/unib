// Davomat oynasi: holatni Fetch API orqali davriy so'raydi (TZ: 2 s).
(function () {
  "use strict";
  const cfg = document.getElementById("session-config").dataset;
  const csrf = document.querySelector("input[name=csrfmiddlewaretoken]").value;
  const rowsEl = document.getElementById("rows");
  const pollMs = parseInt(cfg.pollMs, 10) || 2000;
  let filter = "all";
  let last = null;
  const known = new Map(); // id -> status (yangi aniqlanganlarni yoritish uchun)
  let inflight = false;

  const STATUS_CLASS = {
    present: "ok", absent: "bad", review_unrecognized: "warn", review_uncertain: "warn",
  };
  const SESSION_CLASS = {
    open: "info", connecting: "warn", active: "ok", disconnected: "bad", ended: "warn", confirmed: "ok",
  };

  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
    (children || []).forEach((c) => c && e.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
    return e;
  }

  function matches(r) {
    if (filter === "all") return true;
    if (filter === "review") return r.status === "review_unrecognized" || r.status === "review_uncertain";
    return r.status === filter;
  }

  function statusCell(r) {
    const children = [el("span", { class: "badge " + (STATUS_CLASS[r.status] || ""), text: r.status_label })];
    if (r.status === "review_uncertain" && r.uncertain_score != null) {
      children.push(el("div", { class: "muted small", text: "ehtimoliy nomzod, ball " + r.uncertain_score.toFixed(2) }));
    }
    if (!r.eligible && r.camera_status !== "recognized") {
      children.push(el("div", { class: "muted small", text: "yuz rasmi yoʻq — faqat qoʻlda" }));
    }
    return el("td", null, children);
  }

  function markButtons(r, canEdit) {
    const mk = (value, label, onCls) => el("button", {
      class: "btn sm" + (r.teacher_mark === value ? " " + onCls : ""),
      type: "button",
      text: label,
      "aria-pressed": r.teacher_mark === value ? "true" : "false",
      onclick: () => mark(r.id, r.teacher_mark === value && !last.status.startsWith("conf") ? "" : value),
      ...(canEdit ? {} : { disabled: "disabled" }),
    });
    return el("td", { class: "row", style: "gap:.35rem;flex-wrap:nowrap" }, [
      mk("present", "Keldi", "on-ok"), mk("absent", "Kelmadi", "on-bad"),
    ]);
  }

  function render(data) {
    last = data;
    const st = document.getElementById("status");
    st.textContent = data.status_label;
    st.className = "badge " + (SESSION_CLASS[data.status] || "");

    const c = data.counts;
    document.getElementById("c-camera").textContent = c.camera;
    document.getElementById("c-present").textContent = c.present;
    document.getElementById("c-review").textContent = c.review_unrecognized + c.review_uncertain;
    document.getElementById("c-absent").textContent = c.absent;
    document.getElementById("c-total").textContent = c.total;

    const camBanner = document.getElementById("banner-camera");
    if (data.is_live && data.status === "disconnected") {
      camBanner.textContent = "Kamera oqimi uzildi — qayta ulanishga urinilmoqda (" + data.worker.reconnects +
        " urinish). Avvalgi natijalar saqlangan.";
      camBanner.classList.remove("hidden");
    } else if (data.is_live && data.status === "connecting") {
      camBanner.textContent = "Kameraga ulanmoqda…";
      camBanner.className = "banner warn";
    } else {
      camBanner.className = "banner bad hidden";
    }
    document.getElementById("banner-worker").classList.toggle("hidden", !data.is_live || data.worker.ok || data.status === "open");

    const w = data.worker;
    document.getElementById("worker-info").textContent = data.is_live
      ? `Tahlil: ${w.fps.toFixed(1)} kadr/s · kadr uchun ${Math.round(w.process_ms)} ms · ishlangan kadrlar ${w.frames} · notanish yuzlar ${w.unknown_faces} · yangilangan ${data.server_time}`
      : `Ishlangan kadrlar: ${w.frames} · notanish yuzlar: ${w.unknown_faces}`;

    const frag = document.createDocumentFragment();
    const newlyShown = [];
    data.records.filter(matches).forEach((r) => {
      const prev = known.get(r.id);
      const tr = el("tr", { "data-id": r.id }, [
        el("td", { class: "num", text: r.code }),
        el("td", { text: r.name }),
        statusCell(r),
        el("td", { class: "hide-sm muted", text: r.source_label }),
        el("td", { class: "num", text: r.first_seen || "—" }),
        el("td", { class: "num hide-sm", text: r.score != null ? r.score.toFixed(3) : "—" }),
        markButtons(r, data.can_edit),
      ]);
      if (prev !== undefined && prev !== "recognized" && r.camera_status === "recognized") tr.classList.add("flash");
      frag.appendChild(tr);
    });
    data.records.forEach((r) => {
      if (r.camera_status === "recognized" && !r.displayed) newlyShown.push(r.id);
      known.set(r.id, r.camera_status);
    });
    rowsEl.replaceChildren(frag);
    if (!rowsEl.children.length) {
      rowsEl.appendChild(el("tr", null, [el("td", { colspan: "7", class: "muted", text: "Bu filtrda yozuv yoʻq" })]));
    }
    if (newlyShown.length) reportDisplayed(newlyShown);

    const cf = document.getElementById("confirm-form");
    if (cf && !cf.dataset.bound) {
      cf.dataset.bound = "1";
      cf.addEventListener("submit", (e) => {
        const n = (last.counts.review_unrecognized + last.counts.review_uncertain);
        const msg = n ? `${n} ta yozuv hali «Tekshirish kerak» holatida va «Kelmadi» deb belgilanadi. Tasdiqlaysizmi?`
                      : "Davomatni tasdiqlaysizmi?";
        if (!confirm(msg)) e.preventDefault();
      });
    }
  }

  // Kechikish metrikasi: natija ekranda ko'rsatilgan vaqtni serverga qaytarish
  function reportDisplayed(ids) {
    fetch(cfg.displayedUrl, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({ ids }),
    }).catch(() => {});
  }

  async function poll() {
    if (inflight) return;
    inflight = true;
    try {
      const r = await fetch(cfg.stateUrl, { credentials: "same-origin", cache: "no-store" });
      if (r.status === 403 || r.redirected) { location.reload(); return; }
      if (r.ok) {
        const data = await r.json();
        if (data.hidden) { location.reload(); return; }
        render(data);
        if (!data.is_live && cfg.live === "1") { location.reload(); return; }
      }
    } catch (e) {
      /* tarmoq xatosi — keyingi davrda qayta urinish */
    } finally {
      inflight = false;
    }
  }

  async function mark(id, value) {
    const url = cfg.markUrl.replace("/0/", "/" + id + "/");
    const r = await fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({ value }),
    });
    if (!r.ok) {
      let msg = "Saqlanmadi";
      try { msg = (await r.json()).error || msg; } catch (e) {}
      alert(msg);
    }
    poll();
  }

  document.querySelectorAll(".chip[data-filter]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".chip[data-filter]").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    filter = b.dataset.filter;
    if (last) render(last);
  }));

  poll();
  // Yakunlangan sessiyada davriy so'rov kerak emas (faqat belgilashdan keyin yangilanadi)
  if (cfg.live === "1") setInterval(poll, pollMs);
})();
