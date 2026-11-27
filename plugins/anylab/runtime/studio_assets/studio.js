"use strict";
const form = document.querySelector("#config");
const statusLine = document.querySelector("#status");
const resumeButton = document.querySelector("#resume");
const stopButton = document.querySelector("#stop");
const refreshCashier = document.querySelector("#refresh-cashier");
const downloadButton = document.querySelector("#download");
const assistantPanel = document.querySelector("#assistant-handoff");
const assistantRequest = document.querySelector("#assistant-request");
const submitButtons = Array.from(form.querySelectorAll('[type="submit"]'));
const token = document.querySelector('meta[name="anylab-token"]').content;
let catalog, selected, jobId, running = false;
let previewedJob;
let pollTimer;

async function api(path, payload) {
  const options = {headers: {"X-AnyLab-Token": token}};
  if (payload !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(path, options);
  if (!response.ok) throw new Error((await response.json()).error);
  return response;
}

function setRunning(value) {
  running = value;
  for (const button of submitButtons) button.disabled = value;
}

function selectLab(lab) {
  selected = lab;
  const item = catalog[lab];
  const early = Number(lab) <= 3;
  form.elements.hold.disabled = early || lab === "6";
  document.querySelector("#hold-option").hidden = form.elements.hold.disabled;
  document.querySelector("#metro-hint").hidden = lab !== "4";
  document.querySelector("#template-options").hidden = early;
  document.querySelector("#addon-options").hidden = early;
  document.querySelector("#media-delivery").hidden = early;
  for (const button of submitButtons) button.hidden = early && button.value !== "full";
  document.querySelector("#build-package").textContent = early ? "Выполнить через Codex" : "Собрать комплект";
  document.querySelector("#codex-hint").textContent = early
    ? "Codex выполнит задания, проверит модели и подготовит отчёт."
    : "Заполните пожелания, чтобы Codex доработал модели. При сборке комплекта Codex также пишет текст отчёта.";
  for (const button of document.querySelectorAll("#labs button")) {
    button.setAttribute("aria-current", String(button.dataset.lab === lab));
  }
  for (const [name, type, choices] of [["templates", "radio", item.templates], ["addons", "checkbox", item.addons]]) {
    const group = document.getElementById(name);
    group.replaceChildren();
    for (const [value, text] of Object.entries(choices)) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = type;
      input.name = name === "templates" ? "template" : "addons";
      input.value = value;
      input.checked = type === "radio" && group.children.length === 0;
      label.append(input, document.createTextNode(text));
      group.append(label);
    }
  }
  const details = document.querySelector("#details");
  details.replaceChildren();
  const choices = {...item.choices};
  if (item.variants.length) choices.variant = Object.fromEntries(item.variants.map(v => [v, v]));
  for (const [name, values] of Object.entries(choices)) {
    const label = document.createElement("label");
    label.textContent = ({layout: "Трасса", component: "Деталь", variant: "Вариант", metro_station: "Станция метро", mall: "Торговый центр (4.2)"})[name];
    const select = document.createElement("select");
    select.name = name;
    for (const [value, title] of Object.entries(values)) select.add(new Option(title, value));
    label.append(select);
    details.append(label);
  }
  for (const [name, title] of Object.entries(item.fields)) {
    const label = document.createElement("label");
    label.textContent = title;
    const input = document.createElement("input");
    input.name = name;
    input.maxLength = name === "station" ? 70 : 50;
    label.append(input);
    details.append(label);
  }
  const palettes = {
    "4": [["metro_walls","Стены метро","#d7c4a7"],["metro_accent","Пути на плане и акценты","#174e3c"],
          ["mall_floor","Пол ТЦ","#d7d9d7"],["mall_facade","Фасад ТЦ","#98b5bc"]],
    "5": [["ordinary","Обычная","#19b6b0"],["fragile","Хрупкая","#f28a3c"],
          ["manual","Ручная","#2457cc"],["sheet","Лист","#fff1cf"],["tape","Лента","#f28a3c"]],
    "6": [["station_roof","Крыша","#d9ccaa"],["station_walls","Стены","#254f54"],
          ["station_trim","Стойки и окантовка","#278579"]],
  };
  if (palettes[lab]) {
    const colors = palettes[lab];
    for (const [key, title, initial] of colors) {
      const label = document.createElement("label");
      label.textContent = "Цвет · " + title;
      const input = document.createElement("input");
      input.type = "color";
      input.name = "color-" + key;
      input.value = initial;
      input.addEventListener("input", () => input.dataset.changed = "true");
      label.append(input);
      details.append(label);
    }
  }
}

async function poll() {
  clearTimeout(pollTimer);
  const status = await (await api("/api/jobs/" + jobId)).json();
  statusLine.textContent = status.message;
  assistantPanel.hidden = status.state !== "assistant_required";
  assistantRequest.value = status.assistant_request ?? "";
  stopButton.hidden = status.state !== "running";
  resumeButton.hidden = !["prepared", "preview", "stale_preview", "assistant_required", "error", "interrupted", "cancelled"].includes(status.state);
  resumeButton.textContent = status.state === "assistant_required" ? "Проверить и продолжить" : "Продолжить сборку";
  refreshCashier.hidden = status.state !== "stale_preview" || status.config.lab !== "6";
  downloadButton.hidden = status.state !== "complete";
  document.querySelector("#controls").hidden = stopButton.hidden && resumeButton.hidden && downloadButton.hidden;
  setRunning(status.state === "running");
  if (["preview", "complete"].includes(status.state) && previewedJob !== jobId) await showPhotos(status);
  if (status.state === "stale_preview") document.querySelector("#photos").hidden = true;
  if (running) pollTimer = setTimeout(() => poll().catch(showError), 1600);
}

async function showPhotos(status) {
  previewedJob = status.id;
  const list = document.querySelector("#photo-list");
  list.replaceChildren();
  for (const [part, frames] of Object.entries(status.result.photos)) {
    const figure = document.createElement("figure");
    const select = document.createElement("select");
    select.setAttribute("aria-label", "Точка камеры " + part);
    const names = status.result.shot_labels?.[part] || [];
    for (const key of Object.keys(frames)) {
      const match = /^Ракурс (\d+)$/.exec(key);
      if (key !== "План" && !match) continue;
      const index = match ? Number(match[1]) : 0;
      select.add(new Option(names[index - 1] || key, index));
    }
    if (frames["Ракурс 1"]) select.value = "1";
    const image = document.createElement("img");
    image.alt = "Трёхмерный вид задания " + part;
    async function showFrame() {
      const index = select.value;
      const response = await api("/api/jobs/" + status.id + "/photos/" + part + "/" + index);
      const blob = await response.blob();
      if (select.value !== index) return;
      const url = URL.createObjectURL(blob);
      if (image.src) URL.revokeObjectURL(image.src);
      image.src = url;
    }
    select.addEventListener("change", () => showFrame().catch(showError));
    const label = document.createElement("figcaption");
    label.textContent = "Задание " + part;
    figure.append(label,select,image);
    list.append(figure);
    await showFrame();
  }
  document.querySelector("#photos").hidden = !list.children.length;
}

function showError(error) {
  statusLine.textContent = error.message;
  setRunning(false);
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (running) return;
  setRunning(true);
  document.querySelector("#controls").hidden = true;
  document.querySelector("#photos").hidden = true;
  assistantPanel.hidden = true;
  try {
    const formData = new FormData(form);
    const config = Object.fromEntries(formData);
    config.lab = selected;
    config.addons = formData.getAll("addons");
    config.seed = Number(config.seed);
    config.hold = Number(config.hold ?? 0);
    config.speed = Number(config.speed ?? 0);
    config.colors = Object.fromEntries(Array.from(form.querySelectorAll('input[type="color"][data-changed]'),
      input => [input.name.slice(6), input.value]));
    const file = formData.get("photoFile");
    delete config.photoFile;
    if (file?.size) {
      if (file.size > 2097152) throw new Error("Фото должно быть не больше 2 МБ");
      config.photo = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = reject;
        reader.onload = () => resolve(reader.result.split(",")[1]);
        reader.readAsDataURL(file);
      });
    }
    const response = await api("/api/jobs", {config, mode: event.submitter?.value || "full"});
    jobId = (await response.json()).id;
    sessionStorage.setItem("anylab-job", jobId);
    await poll();
  } catch (error) { showError(error); }
});

document.querySelector("#copy-assistant-request").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(assistantRequest.value);
    statusLine.textContent = "Запрос скопирован. Вставьте его в чат Codex, затем вернитесь к этой сборке.";
  } catch {
    assistantRequest.focus();
    assistantRequest.select();
  }
});

stopButton.addEventListener("click", async () => {
  stopButton.disabled = true;
  try {
    await api("/api/jobs/" + jobId + "/cancel", {});
    await poll();
  } catch (error) {
    statusLine.textContent = error.message;
  } finally {
    stopButton.disabled = false;
  }
});

resumeButton.addEventListener("click", async () => {
  try {
    resumeButton.hidden = true;
    await api("/api/jobs/" + jobId + "/resume", {});
    await poll();
  } catch (error) { showError(error); resumeButton.hidden = false; }
});

refreshCashier.addEventListener("click", async () => {
  try {
    refreshCashier.hidden = true;
    previewedJob = undefined;
    await api("/api/jobs/" + jobId + "/cashier-preview", {});
    await poll();
  } catch (error) { showError(error); refreshCashier.hidden = false; }
});

downloadButton.addEventListener("click", async () => {
  try {
    const response = await api("/api/jobs/" + jobId + "/archive");
    const objectUrl = URL.createObjectURL(await response.blob());
    const name = (response.headers.get("Content-Disposition") || "").split("''")[1];
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = name ? decodeURIComponent(name) : "Комплект.zip";
    link.click();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
  } catch (error) { showError(error); }
});

(async () => {
  catalog = await (await api("/api/catalog")).json();
  for (const [lab, item] of Object.entries(catalog)) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.lab = lab;
    button.textContent = "ЛР" + lab + " · " + item.title;
    button.addEventListener("click", () => selectLab(lab));
    document.querySelector("#labs").append(button);
  }
  jobId = new URLSearchParams(location.search).get("job") || sessionStorage.getItem("anylab-job");
  const recent = await (await api("/api/jobs")).json();
  const active = recent.find(job => job.id === jobId) ?? recent[0];
  jobId = active?.id;
  selectLab(active?.config.lab ?? "4");
  if (jobId) await poll();
})().catch(showError);
