// Chiroyli tanlash ro'yxati: oddiy <select> ustiga quriladi (progressive enhancement).
// Asl <select> sahifada qoladi (ko'rinmas): forma yuborish, required tekshiruvi va
// onchange="this.form.submit()" kabi ishlovchilar avvalgidek ishlaydi.
(function () {
  "use strict";
  const SEARCH_MIN = 7; // shuncha va undan ko'p variant bo'lsa — qidiruv maydoni
  let uid = 0;
  let openInst = null;

  const norm = (s) => (s || "").toLowerCase().replace(/[ʻʼ‘’`']/g, "'").normalize("NFKD").replace(/[̀-ͯ]/g, "");
  const isDashes = (t) => /^-{3,}$/.test((t || "").trim());

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  const CHEVRON = '<svg class="sel-chev" viewBox="0 0 20 20" aria-hidden="true"><path d="M5.5 7.5 10 12l4.5-4.5"/></svg>';
  const CHECK = '<svg class="sel-check" viewBox="0 0 20 20" aria-hidden="true"><path d="m4.5 10.5 3.5 3.5 7.5-8"/></svg>';

  function enhance(select) {
    if (select.multiple || select.size > 1 || select.dataset.native !== undefined || select._sel) return;
    const id = "sel" + ++uid;
    const wrap = el("div", "sel");
    const btn = el("button", "sel-btn");
    btn.type = "button";
    btn.setAttribute("aria-haspopup", "listbox");
    btn.setAttribute("aria-expanded", "false");
    const label = select.getAttribute("aria-label") ||
      (select.id && document.querySelector(`label[for="${select.id}"]`)?.textContent.replace(/:$/, "").trim()) || "";
    if (label) btn.setAttribute("aria-label", label);
    const valueEl = el("span", "sel-value");
    btn.append(valueEl);
    btn.insertAdjacentHTML("beforeend", CHEVRON);

    const pop = el("div", "sel-pop");
    pop.hidden = true;
    const list = el("ul", "sel-list");
    list.id = id + "-list";
    list.setAttribute("role", "listbox");
    btn.setAttribute("aria-controls", list.id);
    let search = null;
    if (select.options.length >= SEARCH_MIN) {
      const sw = el("div", "sel-search");
      sw.innerHTML = '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="9" cy="9" r="5.5"/><path d="m13.5 13.5 3.5 3.5"/></svg>';
      search = el("input");
      search.type = "text";
      search.placeholder = "Qidirish…";
      search.setAttribute("aria-label", "Roʻyxatdan qidirish");
      search.setAttribute("aria-controls", list.id);
      search.autocomplete = "off";
      sw.append(search);
      pop.append(sw);
    }
    const empty = el("div", "sel-empty", "Hech narsa topilmadi");
    empty.hidden = true;
    pop.append(list, empty);

    // Asl select ko'rinmaydi, lekin formada qoladi
    select.classList.add("sel-native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    select.parentNode.insertBefore(wrap, select);
    wrap.append(btn, select);
    // Inline kenglik (masalan, style="width:100%") komponentga o'tadi
    if (select.style.width) { wrap.style.width = select.style.width; }
    document.body.append(pop);

    let items = []; // {li, opt}
    let active = -1;

    function placeholderText(opt) {
      if (!opt || opt.value !== "") return null;
      return isDashes(opt.text) ? "Tanlang…" : opt.text;
    }

    function syncButton() {
      const opt = select.options[select.selectedIndex];
      const ph = placeholderText(opt);
      valueEl.textContent = ph != null ? ph : (opt ? opt.text : "Tanlang…");
      btn.classList.toggle("is-placeholder", ph != null || !opt);
      btn.disabled = select.disabled;
      wrap.classList.toggle("is-invalid", select.closest(".has-error") != null);
    }

    function build(q) {
      list.replaceChildren();
      items = [];
      const nq = norm(q);
      let lastGroup = null;
      Array.from(select.options).forEach((opt) => {
        const text = placeholderText(opt) ?? opt.text;
        if (nq && (opt.value === "" || !norm(opt.text).includes(nq))) return;
        const grp = opt.parentElement.tagName === "OPTGROUP" ? opt.parentElement : null;
        if (grp && grp !== lastGroup) {
          list.append(el("li", "sel-group", grp.label));
          lastGroup = grp;
        }
        const li = el("li", "sel-opt" + (opt.value === "" ? " is-placeholder" : ""));
        li.id = `${id}-o${opt.index}`;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", opt.selected ? "true" : "false");
        if (opt.disabled) li.setAttribute("aria-disabled", "true");
        const span = el("span", "sel-text");
        const i = nq ? norm(text).indexOf(nq) : -1;
        if (i >= 0) {
          span.append(text.slice(0, i), el("mark", null, text.slice(i, i + q.length)), text.slice(i + q.length));
        } else {
          span.textContent = text;
        }
        li.append(span);
        li.insertAdjacentHTML("beforeend", CHECK);
        li.addEventListener("mousedown", (e) => e.preventDefault()); // fokus qidiruvda qolsin
        li.addEventListener("click", () => { if (!opt.disabled) choose(opt); });
        li.addEventListener("mousemove", () => setActive(items.findIndex((x) => x.li === li), false));
        list.append(li);
        items.push({ li, opt });
      });
      empty.hidden = items.length > 0;
      const sel = items.findIndex((x) => x.opt.selected);
      setActive(sel >= 0 ? sel : (items.length ? 0 : -1), true);
    }

    function setActive(i, scroll) {
      if (active >= 0 && items[active]) items[active].li.classList.remove("is-active");
      active = i;
      const cur = items[i];
      if (!cur) { btn.removeAttribute("aria-activedescendant"); return; }
      cur.li.classList.add("is-active");
      (search || btn).setAttribute("aria-activedescendant", cur.li.id);
      if (scroll) cur.li.scrollIntoView({ block: "nearest" });
    }

    function move(delta) {
      if (!items.length) return;
      let i = active;
      for (let n = 0; n < items.length; n++) {
        i = (i + delta + items.length) % items.length;
        if (!items[i].opt.disabled) break;
      }
      setActive(i, true);
    }

    function position() {
      const r = btn.getBoundingClientRect();
      const vw = document.documentElement.clientWidth;
      // Kamida tugma kengligida, uzun nomlar uchun kengayadi (ekrandan chiqmagan holda)
      pop.style.minWidth = Math.max(r.width, 220) + "px";
      pop.style.maxWidth = Math.min(460, vw - 16) + "px";
      const width = pop.offsetWidth;
      pop.style.left = Math.max(8, Math.min(r.left, vw - width - 8)) + "px";
      pop.style.maxHeight = "";
      const h = pop.offsetHeight;
      const below = window.innerHeight - r.bottom - 8;
      const above = r.top - 8;
      if (h > below && above > below) {
        pop.classList.add("is-up");
        pop.style.top = Math.max(8, r.top - Math.min(h, above) - 4) + "px";
        pop.style.maxHeight = above + "px";
      } else {
        pop.classList.remove("is-up");
        pop.style.top = r.bottom + 4 + "px";
        pop.style.maxHeight = Math.max(160, below) + "px";
      }
    }

    function open(initial) {
      if (btn.disabled) return;
      if (openInst && openInst !== inst) openInst.close(false);
      openInst = inst;
      if (search) search.value = initial || "";
      build(search ? search.value : "");
      pop.hidden = false;
      wrap.classList.add("is-open");
      btn.setAttribute("aria-expanded", "true");
      position();
      if (search) { search.focus(); search.setSelectionRange(search.value.length, search.value.length); }
    }

    function close(refocus) {
      if (pop.hidden) return;
      pop.hidden = true;
      wrap.classList.remove("is-open");
      btn.setAttribute("aria-expanded", "false");
      btn.removeAttribute("aria-activedescendant");
      if (openInst === inst) openInst = null;
      if (refocus) btn.focus();
    }

    function choose(opt) {
      const changed = select.value !== opt.value;
      select.value = opt.value;
      syncButton();
      close(true);
      if (changed) {
        select.dispatchEvent(new Event("input", { bubbles: true }));
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    function onKey(e) {
      const isOpen = !pop.hidden;
      switch (e.key) {
        case "ArrowDown": e.preventDefault(); isOpen ? move(1) : open(); break;
        case "ArrowUp": e.preventDefault(); isOpen ? move(-1) : open(); break;
        case "Home": if (isOpen) { e.preventDefault(); setActive(0, true); } break;
        case "End": if (isOpen) { e.preventDefault(); setActive(items.length - 1, true); } break;
        case "Enter":
          if (isOpen) { e.preventDefault(); if (items[active] && !items[active].opt.disabled) choose(items[active].opt); }
          else if (e.target === btn) { e.preventDefault(); open(); }
          break;
        case " ":
          if (e.target === btn) { e.preventDefault(); isOpen ? close(true) : open(); }
          break;
        case "Escape": if (isOpen) { e.preventDefault(); e.stopPropagation(); close(true); } break;
        case "Tab": if (isOpen) close(false); break;
        default:
          // Harf yozilsa: qidiruv bo'lsa — unga o'tadi, bo'lmasa — shu harf bilan boshlanadigan variantga sakraydi
          if (e.target === btn && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
            if (search) { e.preventDefault(); open(e.key); }
            else {
              if (!isOpen) open();
              const k = norm(e.key);
              const start = active + 1;
              for (let n = 0; n < items.length; n++) {
                const it = items[(start + n) % items.length];
                if (norm(it.li.textContent).startsWith(k)) { setActive(items.indexOf(it), true); break; }
              }
            }
          }
      }
    }

    btn.addEventListener("click", () => (pop.hidden ? open() : close(true)));
    btn.addEventListener("keydown", onKey);
    if (search) {
      search.addEventListener("keydown", onKey);
      search.addEventListener("input", () => build(search.value));
    }
    select.addEventListener("change", syncButton);
    select.addEventListener("focus", () => btn.focus()); // label bosilganda yoki validatsiyada
    select.addEventListener("invalid", () => wrap.classList.add("is-invalid"));
    select.form && select.form.addEventListener("reset", () => setTimeout(syncButton));

    const inst = { close, position, pop, wrap };
    select._sel = inst;
    syncButton();
  }

  // Tashqariga bosilganda / aylantirilganda / oyna o'lchami o'zgarganda yopish
  document.addEventListener("mousedown", (e) => {
    if (openInst && !openInst.wrap.contains(e.target) && !openInst.pop.contains(e.target)) openInst.close(false);
  });
  // Yopilmaydi, faqat joyi qayta hisoblanadi: telefonda qidiruvga bosilganda klaviatura
  // chiqib oyna o'lchami o'zgaradi — ro'yxat ochiq qolishi kerak
  window.addEventListener("resize", () => openInst && openInst.position());
  window.addEventListener("scroll", (e) => {
    if (openInst && !openInst.pop.contains(e.target)) openInst.position();
  }, true);

  function init(root) {
    (root || document).querySelectorAll("select").forEach(enhance);
  }
  window.enhanceSelects = init;
  // Skript <body> oxirida: yuqoridagi elementlar tayyor — darhol quriladi;
  // keyin qo'shilganlari uchun DOMContentLoaded'da yana (takroriy chaqiruv xavfsiz)
  init();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => init());
})();
