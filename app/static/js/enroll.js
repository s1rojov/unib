// Andoza uchun brauzerda kameradan suratga olish. Suratlar faqat xotirada:
// fayl maydoniga qo'yilib, oddiy forma bilan yuboriladi.
(function () {
  "use strict";
  const start = document.getElementById("cam-start");
  if (!start) return;
  const video = document.getElementById("cam-video");
  const shot = document.getElementById("cam-shot");
  const send = document.getElementById("cam-send");
  const reset = document.getElementById("cam-reset");
  const thumbs = document.getElementById("cam-thumbs");
  const msg = document.getElementById("cam-msg");
  const form = document.getElementById("samples-form");
  const input = form.querySelector("input[type=file]");
  const MAX = 5;
  let stream = null;
  let shots = [];

  function update() {
    shot.textContent = `Suratga olish (${shots.length}/${MAX})`;
    shot.disabled = shots.length >= MAX;
    send.hidden = shots.length === 0;
    reset.hidden = shots.length === 0;
  }

  start.addEventListener("click", async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      msg.textContent = "Brauzer kameraga kirishni qoʻllab-quvvatlamaydi (localhost yoki HTTPS kerak).";
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } } });
    } catch (e) {
      msg.textContent = "Kamera ochilmadi: " + e.message + ". Kamera boshqa dastur (masalan, worker) tomonidan band boʻlishi mumkin.";
      return;
    }
    video.srcObject = stream;
    video.hidden = false;
    start.hidden = true;
    shot.hidden = false;
    msg.textContent = "";
    update();
  });

  shot.addEventListener("click", () => {
    if (!video.videoWidth) return;
    const c = document.createElement("canvas");
    c.width = video.videoWidth;
    c.height = video.videoHeight;
    c.getContext("2d").drawImage(video, 0, 0);
    c.toBlob((blob) => {
      shots.push(blob);
      const img = document.createElement("img");
      img.src = URL.createObjectURL(blob);
      img.style.cssText = "width:96px;border-radius:6px";
      img.alt = "surat " + shots.length;
      thumbs.appendChild(img);
      update();
    }, "image/jpeg", 0.92);
  });

  reset.addEventListener("click", () => {
    thumbs.querySelectorAll("img").forEach((i) => URL.revokeObjectURL(i.src));
    thumbs.replaceChildren();
    shots = [];
    update();
  });

  send.addEventListener("click", () => {
    const dt = new DataTransfer();
    shots.forEach((b, i) => dt.items.add(new File([b], `kamera_${i + 1}.jpg`, { type: "image/jpeg" })));
    input.files = dt.files;
    if (stream) stream.getTracks().forEach((t) => t.stop());
    send.disabled = true;
    msg.textContent = "Andoza yaratilmoqda…";
    form.submit();
  });

  window.addEventListener("pagehide", () => { if (stream) stream.getTracks().forEach((t) => t.stop()); });
})();
