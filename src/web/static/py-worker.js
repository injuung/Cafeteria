/* GitHub Pages에서 식단표 초안을 돌리는 워커. 로컬 FastAPI 경로에서는 쓰이지 않는다. */
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

let pyodide = null;

function runtimeUrl() {
  return new URL("../py/runtime.zip", self.location.href).href;
}

async function init() {
  self.postMessage({ type: "progress", message: "브라우저 생성 엔진을 받는 중…" });
  pyodide = await loadPyodide({
    indexURL: "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/",
  });
  self.postMessage({ type: "progress", message: "엑셀 라이브러리를 준비하는 중…" });
  await pyodide.loadPackage("micropip");
  const micropip = pyodide.pyimport("micropip");
  await micropip.install("openpyxl");
  self.postMessage({ type: "progress", message: "레시피 마스터를 여는 중…" });
  const zip = await fetch(runtimeUrl());
  if (!zip.ok) throw new Error("생성 엔진 파일을 받지 못했습니다.");
  const buf = await zip.arrayBuffer();
  pyodide.unpackArchive(buf, "zip");
  pyodide.runPython(`
import sys
sys.path.insert(0, ".")
`);
  self.postMessage({ type: "ready" });
}

async function runPlan(ym, holidays) {
  pyodide.globals.set("ym", ym);
  pyodide.globals.set("holidays_js", holidays);
  await pyodide.runPythonAsync(`
from src.web.service import generate_plan
import json
from pathlib import Path
holidays = holidays_js.to_py() if hasattr(holidays_js, "to_py") else list(holidays_js)
plan = generate_plan(ym, holidays)
Path("plan_out.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
xlsx_name = f"output/plan_{ym}.xlsx"
`);
  const json = pyodide.FS.readFile("plan_out.json", { encoding: "utf8" });
  const xlsxPath = `output/plan_${ym}.xlsx`;
  let xlsx = null;
  try {
    const bytes = pyodide.FS.readFile(xlsxPath);
    xlsx = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  } catch (_) {}
  return { json, xlsx };
}

async function runVerify(ym) {
  pyodide.globals.set("ym", ym);
  await pyodide.runPythonAsync(`
from src.web.service import verify
import json
from pathlib import Path
Path("verify_out.json").write_text(json.dumps(verify(ym), ensure_ascii=False), encoding="utf-8")
`);
  return pyodide.FS.readFile("verify_out.json", { encoding: "utf8" });
}

self.onmessage = async (ev) => {
  const { id, type } = ev.data || {};
  try {
    if (type === "init") {
      await init();
      return;
    }
    if (!pyodide) await init();
    if (type === "plan") {
      self.postMessage({ type: "progress", message: "한 달치를 짜는 중…" });
      const { json, xlsx } = await runPlan(ev.data.ym, ev.data.holidays || []);
      const msg = { id, type: "plan", json };
      if (xlsx) self.postMessage({ ...msg, xlsx }, [xlsx]);
      else self.postMessage(msg);
      return;
    }
    if (type === "verify") {
      const json = await runVerify(ev.data.ym);
      self.postMessage({ id, type: "verify", json });
      return;
    }
  } catch (err) {
    self.postMessage({ id, type: "error", message: String(err && err.message ? err.message : err) });
  }
};
