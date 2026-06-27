// Akshar OCR — frontend logic
const $ = (s) => document.querySelector(s);
const files = [];           // {file, pages}
const selectedLangs = new Set();

const fileInput = $("#fileInput");
const drop = $("#drop");
const fileListEl = $("#fileList");
const langChips = $("#langChips");
const convertBtn = $("#convertBtn");
const statusEl = $("#status");
const previewEl = $("#preview");
const downloadsEl = $("#downloads");
const copyBtn = $("#copyBtn");
const zipBtn = $("#zipBtn");
const previewEmpty = $("#previewEmpty");

function setPreview(text){
  previewEl.value = text;
  previewEmpty.style.display = text ? "none" : "flex";
  copyBtn.disabled = !text;
}

// ---------- languages ----------
async function loadLanguages() {
  let langs = [];
  try {
    langs = await (await fetch("/api/languages")).json();
  } catch (e) {
    langChips.innerHTML = "<span class='hint'>Could not load languages.</span>";
    return;
  }
  langChips.innerHTML = "";
  langs.forEach((l) => {
    const chip = document.createElement("div");
    chip.className = "chip " + (l.installed ? "off" : "off");
    chip.innerHTML =
      `<span class="glyph">${l.glyph}</span>` +
      `<span class="nm">${l.name}</span>` +
      (l.installed ? "" : `<span class="tag">install</span>`);
    if (l.installed) {
      chip.classList.remove("off");
      // default-select Gujarati + English
      if (l.code === "guj" || l.code === "eng") {
        chip.classList.add("on");
        selectedLangs.add(l.code);
      }
      chip.onclick = () => {
        if (selectedLangs.has(l.code)) {
          selectedLangs.delete(l.code);
          chip.classList.remove("on");
        } else {
          selectedLangs.add(l.code);
          chip.classList.add("on");
        }
        refresh();
      };
    }
    langChips.appendChild(chip);
  });
  refresh();
}

// ---------- files ----------
function addFiles(list) {
  for (const f of list) {
    if (!files.some((x) => x.file.name === f.name && x.file.size === f.size)) {
      files.push({ file: f, pages: "" });
    }
  }
  renderFiles();
}

function renderFiles() {
  fileListEl.innerHTML = "";
  files.forEach((entry, i) => {
    const li = document.createElement("li");
    li.className = "filerow";
    const kb = entry.file.size < 1024 * 1024
      ? (entry.file.size / 1024).toFixed(0) + " KB"
      : (entry.file.size / 1048576).toFixed(1) + " MB";
    li.innerHTML =
      `<span class="fname" title="${entry.file.name}">${entry.file.name}</span>` +
      `<span class="fsize">${kb}</span>`;
    const pg = document.createElement("input");
    pg.className = "pages";
    pg.placeholder = "Pages: all";
    pg.value = entry.pages;
    pg.title = "Page range, e.g. 1-3,5 (PDF / multipage)";
    pg.oninput = () => (entry.pages = pg.value.trim());
    li.appendChild(pg);
    const rm = document.createElement("button");
    rm.className = "rm";
    rm.textContent = "✕";
    rm.title = "Remove";
    rm.onclick = () => { files.splice(i, 1); renderFiles(); };
    li.appendChild(rm);
    fileListEl.appendChild(li);
  });
  refresh();
}

fileInput.onchange = () => { addFiles(fileInput.files); fileInput.value = ""; };
drop.onclick = () => fileInput.click();
drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") fileInput.click(); };
["dragover", "dragenter"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); }));
drop.addEventListener("drop", (e) => { if (e.dataTransfer?.files) addFiles(e.dataTransfer.files); });

// ---------- state ----------
function refresh() {
  convertBtn.disabled = !(files.length && selectedLangs.size);
}

function setStatus(text, cls = "") {
  statusEl.textContent = text;
  statusEl.className = "status " + cls;
}

// ---------- convert ----------
convertBtn.onclick = async () => {
  if (!files.length || !selectedLangs.size) return;
  const formats = [];
  if ($("#fmtTxt").checked) formats.push("txt");
  if ($("#fmtDocx").checked) formats.push("docx");
  if (!formats.length) { setStatus("Pick at least one output format.", "err"); return; }

  const pages = {};
  files.forEach((e) => { if (e.pages) pages[e.file.name] = e.pages; });

  const options = {
    langs: [...selectedLangs],
    dpi: parseInt($("#dpi").value) || 300,
    force_ocr: $("#forceOcr").checked,
    layout: document.querySelector("input[name=layout]:checked").value,
    formats,
    font: $("#font").value.trim() || "Hind Vadodara",
    pages,
  };

  const fd = new FormData();
  files.forEach((e) => fd.append("files", e.file, e.file.name));
  fd.append("options", JSON.stringify(options));

  convertBtn.disabled = true;
  convertBtn.classList.add("busy");
  setStatus("Converting… this can take a moment for scanned pages.", "busy");
  downloadsEl.innerHTML = "";
  setPreview("");
  zipBtn.hidden = true;

  try {
    const res = await fetch("/api/convert", { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const data = await res.json();
    renderResults(data);
    const okCount = data.results.filter((r) => !r.error).length;
    setStatus(`Done — ${okCount}/${data.results.length} file(s) converted.`);
  } catch (err) {
    setStatus("Failed: " + err.message, "err");
  } finally {
    convertBtn.disabled = false;
    convertBtn.classList.remove("busy");
  }
};

function renderResults(data) {
  const parts = [];
  data.results.forEach((r) => {
    const row = document.createElement("div");
    row.className = "dl";
    if (r.error) {
      row.innerHTML = `<span class="dl-name">${r.name}</span><span class="err">${r.error}</span>`;
    } else {
      const counts = Object.entries(r.counts).map(([k, v]) => `${k} ${v}`).join(" · ");
      let html = `<span class="dl-name">${r.name}</span>`;
      r.downloads.forEach((d) => {
        html += `<a href="/api/download/${data.job}/${encodeURIComponent(d.file)}" download>${d.label}</a>`;
      });
      if (counts) html += `<span class="badge">${counts}</span>`;
      row.innerHTML = html;
      parts.push(`########## ${r.name} ##########\n${r.text}`);
    }
    downloadsEl.appendChild(row);
  });

  if (data.zip) {
    zipBtn.href = `/api/download/${data.job}/${encodeURIComponent(data.zip)}`;
    zipBtn.setAttribute("download", "");
    zipBtn.hidden = false;
  }
  setPreview(parts.join("\n\n"));
}

copyBtn.onclick = async () => {
  try {
    await navigator.clipboard.writeText(previewEl.value);
    setStatus("Copied to clipboard.");
  } catch {
    previewEl.select();
    document.execCommand("copy");
    setStatus("Copied to clipboard.");
  }
};

loadLanguages();
