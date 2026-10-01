// Keep motion IDs and exported data stable; localize presentation only.
const dictionary = await (await fetch("./locale-data.json?v=13")).json();
let language = localStorage.getItem("goose_language") === "zh" ? "zh" : "en";
const originals = new WeakMap();
const keys = Object.keys(dictionary).sort((a, b) => b.length - a.length);
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const pattern = new RegExp(
  keys
    .map(
      (k) =>
        (/^[A-Za-z]/.test(k) ? "(?<![A-Za-z])" : "") +
        escape(k) +
        (/[A-Za-z]$/.test(k) ? "(?![A-Za-z])" : ""),
    )
    .join("|"),
  "g",
);
const observer = new MutationObserver((records) => {
  observer.disconnect();
  for (const r of records) {
    if (r.type === "characterData") visit(r.target);
    else if (r.type === "attributes") visit(r.target);
    else r.addedNodes.forEach(visit);
  }
  observe();
});
function translated(value) {
  return language === "en"
    ? value
    : value.replace(pattern, (key) => dictionary[key]);
}
function visit(node) {
  if (node.nodeType === 3) {
    if (
      !node.parentElement ||
      node.parentElement.closest(
        "script,style,textarea,pre,#language,[data-verbatim]",
      )
    )
      return;
    const old = originals.get(node);
    const source =
      old && node.textContent === old.rendered ? old.source : node.textContent;
    const rendered = translated(source);
    originals.set(node, { source, rendered });
    if (node.textContent !== rendered) node.textContent = rendered;
  } else if (node.nodeType === 1) {
    if (node.matches("script,style,pre,#language,[data-verbatim]")) return;
    let old = originals.get(node) || {};
    for (const key of ["placeholder", "aria-label", "title"]) {
      if (!node.hasAttribute(key)) continue;
      const value = node.getAttribute(key),
        entry = old[key];
      const source = entry && value === entry.rendered ? entry.source : value;
      const rendered = translated(source);
      old[key] = { source, rendered };
      if (value !== rendered) node.setAttribute(key, rendered);
    }
    originals.set(node, old);
    node.childNodes.forEach(visit);
  }
}
function observe() {
  observer.observe(document.body, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ["placeholder", "aria-label", "title"],
  });
}
function apply() {
  observer.disconnect();
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  visit(document.body);
  document.title =
    language === "zh"
      ? "胡萝卜鹅 · 动作工作台"
      : "Carrot Goose · Motion Studio";
  document.getElementById("language").value = language;
  observe();
}
document.getElementById("language").onchange = (e) => {
  language = e.target.value;
  localStorage.setItem("goose_language", language);
  apply();
};
apply();
window.gooseLocale = {
  apply,
  translate: translated,
  get language() {
    return language;
  },
};
