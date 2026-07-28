/** Simple read-only calendar modal (day list, ±1 week). */
(function () {
  const WEEK_STEP = 7;
  let anchor = null;
  let today = null;

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  }

  function addDays(iso, n) {
    const d = new Date(iso + "T12:00:00");
    d.setDate(d.getDate() + n);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function kindLabel(item) {
    const wt = item.work_type || item.kind || "";
    if (wt === "content" || wt === "gsc") return wt.toUpperCase();
    if (wt === "todo") return "TODO";
    return String(wt || "work").toUpperCase();
  }

  function openOverlay() {
    const el = document.getElementById("hub-cal-overlay");
    if (!el) return;
    el.hidden = false;
    el.classList.add("open");
    loadCalendar();
  }

  function closeOverlay() {
    const el = document.getElementById("hub-cal-overlay");
    if (!el) return;
    el.classList.remove("open");
    el.hidden = true;
  }

  function render(data) {
    const body = document.getElementById("hub-cal-body");
    const range = document.getElementById("hub-cal-range");
    if (!body) return;
    anchor = data.anchor || data.today;
    today = data.today;
    if (range) {
      range.textContent = `${data.start} → ${data.end} · 콘텐츠·GSC`;
    }
    const days = data.days || [];
    if (!days.length) {
      body.innerHTML = '<div class="hub-cal-empty" style="padding:20px;text-align:center">일정 없음</div>';
      return;
    }
    body.innerHTML = days
      .map((day) => {
        const items = day.items || [];
        const head = `${day.date} (${day.weekday || ""})`;
        const meta = [
          day.is_today ? "오늘" : "",
          day.holiday ? `🇯🇵 ${day.holiday}` : "",
        ]
          .filter(Boolean)
          .join(" · ");
        let itemsHtml;
        if (!items.length) {
          itemsHtml = '<div class="hub-cal-empty">—</div>';
        } else {
          itemsHtml = items
            .map((it) => {
              const site = (it.site_id || "").trim();
              const siteHtml = site
                ? `<a href="/site/${encodeURIComponent(site)}">${esc(site)}</a>`
                : "<span>—</span>";
              const color = it.color || "#666";
              const label = it.summary || it.label || it.title || "";
              return `<div class="hub-cal-item">
                <span class="hub-cal-dot" style="background:${esc(color)}"></span>
                ${siteHtml}
                <span class="hub-cal-kind">${esc(kindLabel(it))}</span>
                <span class="hub-cal-label" title="${esc(label)}">${esc(label)}</span>
              </div>`;
            })
            .join("");
        }
        return `<div class="hub-cal-day${day.is_today ? " today" : ""}">
          <div class="hub-cal-day-head">
            <span>${esc(head)}</span>
            <span class="meta">${esc(meta)}</span>
          </div>
          ${itemsHtml}
        </div>`;
      })
      .join("");
  }

  async function loadCalendar(nextAnchor) {
    const body = document.getElementById("hub-cal-body");
    if (body) body.innerHTML = '<div class="hub-cal-loading">불러오는 중…</div>';
    const q = nextAnchor ? `?anchor=${encodeURIComponent(nextAnchor)}` : "";
    try {
      const res = await fetch("/api/calendar/days" + q, { credentials: "same-origin" });
      if (!res.ok) throw new Error("load failed");
      render(await res.json());
    } catch (_) {
      if (body) {
        body.innerHTML = '<div class="hub-cal-error">달력을 불러오지 못했습니다</div>';
      }
    }
  }

  function bind() {
    const openBtn = document.getElementById("hub-cal-open");
    const overlay = document.getElementById("hub-cal-overlay");
    if (!openBtn || !overlay) return;

    openBtn.addEventListener("click", openOverlay);
    document.getElementById("hub-cal-close")?.addEventListener("click", closeOverlay);
    document.getElementById("hub-cal-today")?.addEventListener("click", () => {
      loadCalendar(today || undefined);
    });
    document.getElementById("hub-cal-prev")?.addEventListener("click", () => {
      if (!anchor) return;
      loadCalendar(addDays(anchor, -WEEK_STEP));
    });
    document.getElementById("hub-cal-next")?.addEventListener("click", () => {
      if (!anchor) return;
      loadCalendar(addDays(anchor, WEEK_STEP));
    });
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeOverlay();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && overlay.classList.contains("open")) closeOverlay();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }

  window.openHubCalendar = openOverlay;
})();
