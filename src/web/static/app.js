const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];
const SHEET_DAYS = ["월", "화", "수", "목", "금"];
const LIVE = ["localhost", "127.0.0.1"].includes(location.hostname);

const state = {
  ym: "",
  holidays: new Set(),
  calendar: null,
  plan: null,
  line: "kid",
  busy: false,
  holidayNames: {},
};

const $ = (id) => document.getElementById(id);

function parseYm(ym) {
  return { y: Number(ym.slice(0, 4)), m: Number(ym.slice(5, 7)) };
}
function fmtYm(y, m) {
  return `${y}-${String(m).padStart(2, "0")}`;
}
function shiftYm(ym, delta) {
  const { y, m } = parseYm(ym);
  const d = new Date(y, m - 1 + delta, 1);
  return fmtYm(d.getFullYear(), d.getMonth() + 1);
}
function ymd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function readJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

async function getJson(url, opts) {
  if (!LIVE) return staticGet(url, opts);
  const res = await fetch(url, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.detail || JSON.stringify(body);
    } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

async function staticGet(url, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  if (url.startsWith("/api/meta")) return readJson("data/meta.json");
  if (url.startsWith("/api/rules")) return readJson("data/rules.json");
  if (url.startsWith("/api/calendar")) {
    const q = new URL(url, "http://local.invalid").searchParams;
    const holParam = q.get("holidays");
    const hol = holParam === null ? null : holParam.split(",").filter(Boolean);
    return calendarView(q.get("ym"), hol);
  }
  if (url.startsWith("/api/plan") || (method === "POST" && url.includes("plan"))) {
    const body = JSON.parse(opts.body || "{}");
    const res = await pyCall({ type: "plan", ym: body.ym, holidays: body.holidays || [] });
    const plan = JSON.parse(res.json);
    if (res.xlsx) {
      if (state.xlsxUrl) URL.revokeObjectURL(state.xlsxUrl);
      state.xlsxUrl = URL.createObjectURL(new Blob([res.xlsx], {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      }));
      plan.download = state.xlsxUrl;
    }
    return plan;
  }
  if (url.includes("/api/verify")) {
    const ym = JSON.parse(opts.body || "{}").ym;
    const res = await pyCall({ type: "verify", ym });
    return JSON.parse(res.json);
  }
  throw new Error("정적 페이지에서 처리할 수 없는 요청입니다.");
}

let pyWorker = null;
let pyReady = null;
let pyReq = 0;

function setBusyText(title, body) {
  const t = $("busy-title");
  const b = $("busy-body");
  if (t) t.textContent = title;
  if (b) b.textContent = body;
}

function ensurePyWorker() {
  if (pyWorker) return pyReady;
  pyWorker = new Worker("static/py-worker.js");
  pyReady = new Promise((resolve, reject) => {
    const onMsg = (e) => {
      if (e.data.type === "progress") {
        setBusyText(e.data.message, "잠시만 기다려 주세요.");
        return;
      }
      if (e.data.type === "ready") {
        pyWorker.removeEventListener("message", onMsg);
        resolve();
        return;
      }
      if (e.data.type === "error" && e.data.id == null) {
        pyWorker.removeEventListener("message", onMsg);
        reject(new Error(e.data.message));
      }
    };
    pyWorker.addEventListener("message", onMsg);
    pyWorker.postMessage({ type: "init" });
  });
  return pyReady;
}

function pyCall(payload) {
  return ensurePyWorker().then(() => new Promise((resolve, reject) => {
    const id = ++pyReq;
    const onMsg = (e) => {
      if (e.data.type === "progress") {
        setBusyText(e.data.message, "레시피 로테이션과 조합 기피 룰을 적용하고 있어요.");
        return;
      }
      if (e.data.id !== id) return;
      pyWorker.removeEventListener("message", onMsg);
      if (e.data.type === "error") reject(new Error(e.data.message));
      else resolve(e.data);
    };
    pyWorker.addEventListener("message", onMsg);
    pyWorker.postMessage({ id, ...payload });
  }));
}

function nthWeekday(dt) {
  let n = 0;
  for (let x = 1; x <= dt.getDate(); x++) {
    if (new Date(dt.getFullYear(), dt.getMonth(), x).getDay() === dt.getDay()) n += 1;
  }
  return n;
}

function monthBusinessDays(y, m, holSet) {
  const last = new Date(y, m, 0).getDate();
  const days = [];
  for (let d = 1; d <= last; d++) {
    const dt = new Date(y, m - 1, d);
    const wd = dt.getDay();
    if (wd !== 0 && wd !== 6 && !holSet.has(ymd(dt))) days.push(dt);
  }
  return days;
}

function feastDays(biz) {
  const fri = biz.filter((d) => d.getDay() === 5).sort((a, b) => a - b);
  if (!fri.length) return [];
  const first = new Date(fri[0].getFullYear(), fri[0].getMonth(), 1);
  const shift = first.getDay() === 5 ? 1 : 0;
  const target = 3 + shift;
  const hit = fri.find((d) => nthWeekday(d) === target);
  if (hit) return [hit];
  const later = fri.filter((d) => nthWeekday(d) > target);
  return [(later[0] || fri[fri.length - 1])];
}

function gimDays(biz, feast) {
  const feastKey = new Set(feast.map(ymd));
  const fri = biz.filter((d) => d.getDay() === 5 && !feastKey.has(ymd(d)));
  if (fri.length <= 2) return fri;
  return [fri[0], fri[fri.length - 1]];
}

function calendarView(ym, holidays) {
  const { y, m } = parseYm(ym);
  const publicHolidays = Object.entries(state.holidayNames)
    .filter(([d]) => d.startsWith(ym))
    .map(([date, name]) => ({ date, name }));
  const hol = holidays == null ? publicHolidays.map((h) => h.date) : holidays;
  const holSet = new Set(hol);
  const biz = monthBusinessDays(y, m, holSet);
  const feast = feastDays(biz).map(ymd);
  const gim = gimDays(biz, feastDays(biz)).map(ymd);
  const firstWd = (new Date(y, m - 1, 1).getDay() + 6) % 7;
  const nDays = new Date(y, m, 0).getDate();
  const cells = Array(firstWd).fill(null);
  for (let day = 1; day <= nDays; day++) {
    const dt = new Date(y, m - 1, day);
    const iso = ymd(dt);
    cells.push({
      date: iso,
      day,
      weekday: (dt.getDay() + 6) % 7,
      weekday_label: WEEKDAYS[(dt.getDay() + 6) % 7],
      weekend: dt.getDay() === 0 || dt.getDay() === 6,
      holiday: holSet.has(iso),
      holiday_name: holSet.has(iso) ? (state.holidayNames[iso] || "휴무") : null,
      business: biz.some((d) => ymd(d) === iso),
      feast: feast.includes(iso),
      gim: gim.includes(iso),
    });
  }
  while (cells.length % 7) cells.push(null);
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return {
    ym, year: y, month: m,
    public_holidays: publicHolidays,
    holidays: [...holSet].sort(),
    business_days: biz.length,
    feast, gim, weeks,
  };
}

function setTab(name) {
  document.querySelectorAll(".tabs [role=tab]").forEach((btn) => {
    btn.setAttribute("aria-selected", btn.dataset.tab === name ? "true" : "false");
  });
  ["plan", "rules", "verify"].forEach((id) => {
    const el = $(`view-${id}`);
    const on = id === name;
    el.classList.toggle("hidden", !on);
    el.hidden = !on;
  });
  if (name === "rules") loadRules();
  if (name === "verify") fillVerifyMonths();
}

async function loadCalendar() {
  const { y, m } = parseYm(state.ym);
  $("month-label").textContent = `${y}년 ${m}월`;
  const hol = [...state.holidays].join(",");
  const qs = new URLSearchParams({ ym: state.ym, holidays: hol });
  state.calendar = await getJson(`/api/calendar?${qs}`);
  renderCalendar();
}

function renderCalendar() {
  const cal = state.calendar;
  const root = $("calendar");
  root.innerHTML = "";
  const hd = document.createElement("div");
  hd.className = "cal-hd";
  WEEKDAYS.forEach((w) => {
    const s = document.createElement("span");
    s.textContent = w;
    hd.appendChild(s);
  });
  root.appendChild(hd);

  cal.weeks.forEach((week) => {
    const row = document.createElement("div");
    row.className = "cal-row";
    week.forEach((cell) => {
      const btn = document.createElement("button");
      btn.type = "button";
      if (!cell) {
        btn.className = "day pad";
        btn.tabIndex = -1;
        row.appendChild(btn);
        return;
      }
      const cls = ["day"];
      if (cell.weekend) cls.push("weekend");
      if (cell.business) cls.push("biz");
      if (cell.holiday) cls.push("holiday");
      if (cell.feast) cls.push("feast");
      if (cell.gim) cls.push("gim");
      btn.className = cls.join(" ");
      btn.dataset.date = cell.date;
      const tag = cell.holiday
        ? (cell.holiday_name || "휴무")
        : cell.feast
          ? "특식"
          : cell.gim
            ? "김"
            : "";
      btn.innerHTML = `<span class="n">${cell.day}</span>${tag ? `<span class="tag">${tag}</span>` : ""}`;
      btn.disabled = cell.weekend;
      btn.setAttribute("aria-pressed", cell.holiday ? "true" : "false");
      btn.title = cell.weekend
        ? "주말은 영업일이 아닙니다"
        : cell.holiday
          ? `${cell.holiday_name || "휴무"} · 다시 누르면 영업일로`
          : "누르면 휴무로 뺍니다";
      if (!cell.weekend) {
        btn.addEventListener("click", () => toggleHoliday(cell.date));
      }
      row.appendChild(btn);
    });
    root.appendChild(row);
  });

  $("biz-count").textContent = cal.business_days;
  $("hol-count").textContent = cal.holidays.length;
  $("feast-count").textContent = cal.feast.length ? cal.feast.map((d) => Number(d.slice(-2)) + "일").join(", ") : "–";
}

async function toggleHoliday(iso) {
  if (state.holidays.has(iso)) state.holidays.delete(iso);
  else state.holidays.add(iso);
  await loadCalendar();
}

async function generate() {
  if (state.busy) return;
  state.busy = true;
  $("generate").disabled = true;
  $("empty").classList.add("hidden");
  $("result").classList.add("hidden");
  $("busy").classList.remove("hidden");
  $("status-line").textContent = !LIVE
    ? "생성 엔진을 준비한 뒤 한 달치를 짭니다. 처음에는 조금 걸립니다."
    : "한 달치를 짜는 중…";
  if (!LIVE) setBusyText("생성 엔진을 준비하는 중", "처음 한 번은 브라우저에 파이썬을 불러옵니다.");
  else setBusyText("한 달치를 짜는 중입니다", "레시피 로테이션과 조합 기피 룰을 적용하고 있어요. 보통 몇 초면 끝납니다.");
  try {
    const plan = await getJson("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ym: state.ym, holidays: [...state.holidays] }),
    });
    state.plan = plan;
    renderResult();
    $("status-line").textContent = "초안이 준비됐습니다. 엑셀을 받아 담당자가 손보면 됩니다.";
    $("generate").textContent = "다시 만들기";
  } catch (err) {
    $("empty").classList.remove("hidden");
    $("status-line").textContent = `만들지 못했습니다. ${err.message}`;
  } finally {
    state.busy = false;
    $("generate").disabled = false;
    $("busy").classList.add("hidden");
  }
}

function renderResult() {
  const plan = state.plan;
  $("empty").classList.add("hidden");
  $("result").classList.remove("hidden");
  const s = plan.stats;
  $("chips").innerHTML = [
    chip(`${s.business_days}영업일`),
    chip(`배치 실패 ${s.failures}건`, s.failures ? "warn" : ""),
    chip(`성인식 상이 ${s.divergence}%`, "soft"),
    chip(`완조리 메인 ${s.ready_main}/${s.ready_main_max}`, "gold"),
    s.feast.length ? chip(`특식 ${s.feast.map((d) => Number(d.slice(-2))).join(", ")}일`) : "",
  ].join("");

  const fail = $("fail-banner");
  if (plan.failures.length) {
    fail.classList.remove("hidden");
    fail.textContent = "비운 날: " + plan.failures.map((f) => `${f.date.slice(8)}일 ${f.reason}`).join(" · ");
  } else {
    fail.classList.add("hidden");
    fail.textContent = "";
  }

  $("download").href = plan.download;
  $("download").setAttribute("download", plan.filename);
  renderWeeks();
}

function chip(text, cls = "") {
  return `<span class="chip ${cls}">${text}</span>`;
}

function renderWeeks() {
  const plan = state.plan;
  const days = plan[state.line];
  const nRows = plan.menu_rows || 8;
  const title = state.line === "adult" ? plan.title_adult : plan.title_kid;
  const root = $("weeks");
  const weeks = weekBlocks(days);

  const headWd = `<tr class="wd"><th>요일</th>${SHEET_DAYS.map((w) => `<th colspan="2">${w}</th>`).join("")}</tr>`;
  const body = weeks.map((dmap, wi) => weekBlockHtml(dmap, wi + 1, nRows)).join("");
  const legend = esc(plan.legend || "").replace(/\n/g, "<br>");

  root.innerHTML = `
    <div class="sheet">
      <table>
        <thead>
          <tr class="title"><th colspan="11">${esc(title)}</th></tr>
          ${headWd}
        </thead>
        <tbody>${body}</tbody>
        <tfoot>
          <tr class="legend"><td colspan="11">${legend}</td></tr>
        </tfoot>
      </table>
    </div>`;
}

function weekBlocks(days) {
  const map = new Map();
  days.forEach((d) => {
    const key = mondayOf(d.date);
    if (!map.has(key)) map.set(key, {});
    map.get(key)[d.weekday] = d;
  });
  return [...map.values()];
}

function weekBlockHtml(dmap, weekNo, nRows) {
  const dates = SHEET_DAYS.map((_, i) => {
    const d = dmap[i];
    const label = d ? `${d.month}월 ${d.day}일` : "";
    return `<td colspan="2">${label}</td>`;
  }).join("");
  const hdr = SHEET_DAYS.map(() => `<td>메뉴</td><td>알레르기표기</td>`).join("");
  const menus = [];
  for (let k = 0; k < nRows; k++) {
    const cells = [];
    for (let i = 0; i < 5; i++) {
      const d = dmap[i];
      const row = d && d.rows[k];
      if (!row) {
        cells.push(`<td class="menu"></td><td class="alg"></td>`);
        continue;
      }
      const tip = row.reason ? ` data-tip="${esc(row.reason)}"` : "";
      cells.push(
        `<td class="menu${row.is_side ? " side" : ""}"${tip}>${esc(row.name)}</td>` +
        `<td class="alg">${esc(row.allergy)}</td>`
      );
    }
    const wk = k === 0
      ? `<th class="wk" rowspan="${nRows}">${weekNo}주</th>`
      : "";
    menus.push(`<tr>${wk}${cells.join("")}</tr>`);
  }
  return `
    <tr class="date"><th>날짜</th>${dates}</tr>
    <tr class="hdr"><th>주차</th>${hdr}</tr>
    ${menus.join("")}`;
}

function mondayOf(iso) {
  const d = new Date(iso + "T00:00:00");
  const day = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - day);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/"/g, "&quot;");
}

async function loadRules() {
  const root = $("rules");
  if (root.dataset.loaded) return;
  const data = await getJson("/api/rules");
  root.innerHTML = data.rules.map((r) => `
    <article class="rule">
      <div class="row">
        <span class="badge code">${r.code}</span>
        <span class="badge ${r.level}">${r.level_label}</span>
        <span class="badge scope">${r.scope_label}</span>
      </div>
      <h3>${esc(r.title)}</h3>
      <p>${esc(r.rationale)}</p>
      <p>${esc(r.evidence)}</p>
    </article>
  `).join("");
  root.dataset.loaded = "1";
}

function fillVerifyMonths() {
  const sel = $("verify-month");
  if (sel.dataset.loaded) return;
  (state.meta.history_months || []).slice().reverse().forEach((ym) => {
    const opt = document.createElement("option");
    opt.value = ym;
    const { y, m } = parseYm(ym);
    opt.textContent = `${y}년 ${m}월`;
    sel.appendChild(opt);
  });
  sel.dataset.loaded = "1";
}

async function runVerify() {
  const ym = $("verify-month").value;
  const out = $("verify-out");
  out.innerHTML = `<div class="busy"><span class="spinner"></span><div><strong>과거 달과 대조하는 중</strong></div></div>`;
  try {
    const v = await getJson("/api/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ym }),
    });
    if (v.empty) {
      out.innerHTML = `<p class="note">${esc(v.message)}</p>`;
      return;
    }
    out.innerHTML = `
      <div class="metrics">
        ${metric("메뉴 집합 일치", v.set_rate + "%", v.set)}
        ${metric("하드 위반 생성/실제", `${v.gen_violations} / ${v.act_violations}`, "생성본이 규칙을 지켰는가")}
        ${metric("칸 단위 일치", v.exact_rate + "%", v.exact + " · 낮아도 정상")}
        ${metric("단백질 구성", v.protein_rate + "%", "같은 주재료인가")}
        ${metric("조리방식", v.cook_rate + "%", "같은 조리인가")}
        ${metric("영업일", v.business_days, "실패 " + v.failures + "일")}
      </div>
      <p class="note">${esc(v.note)}</p>
      <p class="note">자리별 집합: ${Object.entries(v.set_by_slot).map(([k, x]) => `${k} ${x}`).join(" · ")}</p>
    `;
  } catch (err) {
    out.innerHTML = `<p class="note">${esc(err.message)}</p>`;
  }
}

function metric(label, value, sub) {
  return `<div class="metric"><span>${label}</span><b>${value}</b><span>${sub}</span></div>`;
}

function bindTip() {
  const tip = $("tip");
  document.addEventListener("pointerover", (e) => {
    const cell = e.target.closest("[data-tip]");
    if (!cell || !cell.dataset.tip) {
      tip.hidden = true;
      return;
    }
    tip.textContent = cell.dataset.tip;
    tip.hidden = false;
    const r = cell.getBoundingClientRect();
    tip.style.left = Math.min(r.left, window.innerWidth - 300) + "px";
    tip.style.top = r.bottom + 8 + "px";
  });
  document.addEventListener("pointerout", (e) => {
    if (!e.target.closest("[data-tip]")) tip.hidden = true;
  });
}

async function boot() {
  if (!LIVE) {
    state.holidayNames = await readJson("data/holidays.json");
    $("pub-banner").classList.remove("hidden");
  }
  state.meta = await getJson("/api/meta");
  state.ym = state.meta.default_ym;
  const cal0 = await getJson(`/api/calendar?ym=${state.ym}`);
  state.holidays = new Set(cal0.holidays);
  state.calendar = cal0;
  const { y, m } = parseYm(state.ym);
  $("month-label").textContent = `${y}년 ${m}월`;
  renderCalendar();

  $("prev-month").onclick = async () => { state.ym = shiftYm(state.ym, -1); await resetMonth(); };
  $("next-month").onclick = async () => { state.ym = shiftYm(state.ym, 1); await resetMonth(); };
  $("generate").onclick = generate;
  $("run-verify").onclick = runVerify;
  document.querySelectorAll(".tabs [role=tab]").forEach((btn) => {
    btn.onclick = () => setTab(btn.dataset.tab);
  });
  document.querySelectorAll(".seg-btn").forEach((btn) => {
    btn.onclick = () => {
      state.line = btn.dataset.line;
      document.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("on", b === btn));
      if (state.plan) renderWeeks();
    };
  });
  bindTip();
}

async function resetMonth() {
  const cal0 = await getJson(`/api/calendar?ym=${state.ym}`);
  state.holidays = new Set(cal0.holidays);
  state.calendar = cal0;
  const { y, m } = parseYm(state.ym);
  $("month-label").textContent = `${y}년 ${m}월`;
  $("generate").textContent = "이 달 초안 만들기";
  renderCalendar();
}

boot().catch((err) => {
  $("status-line").textContent = `화면을 열지 못했습니다. ${err.message}`;
});
