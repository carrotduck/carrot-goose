import * as T from "three";
const s = window.studio,
  view = document.getElementById("view"),
  ns = "http://www.w3.org/2000/svg";
const svg = document.createElementNS(ns, "svg");
svg.id = "joint-links";
svg.setAttribute("aria-hidden", "true");
view.append(svg);
let active = null,
  reversed = false;
const entries = Object.entries(s.joints).map(([id, joint]) => {
  const line = document.createElementNS(ns, "path"),
    dot = document.createElementNS(ns, "circle");
  line.setAttribute("class", "joint-link");
  dot.setAttribute("class", "joint-dot");
  dot.setAttribute("r", "3");
  svg.append(line, dot);
  const card = document.querySelector(".servo-" + id);
  const activate = () => {
    active = id;
    document
      .querySelectorAll(".servo-card")
      .forEach((el) => el.classList.toggle("active", el === card));
  };
  card.addEventListener("pointerdown", activate);
  card.addEventListener("focusin", activate);
  document.getElementById("edit-" + id).addEventListener("focus", activate);
  let behind = null;
  if (["pitch", "yaw"].includes(id)) {
    behind = new T.Line(
      new T.BufferGeometry(),
      new T.LineDashedMaterial({
        color: 0xe89032,
        dashSize: 0.004,
        gapSize: 0.003,
        depthTest: true,
        depthWrite: false,
      }),
    );
    behind.name = "head-link-" + id;
    s.scene.add(behind);
    line.style.display = dot.style.display = "none";
  }
  return { id, joint, line, dot, card, behind };
});
function tick() {
  s.scene.updateMatrixWorld(true);
  s.camera.updateMatrixWorld(true);
  const rect = view.getBoundingClientRect();
  const a = s.joints["16"]
    .getWorldPosition(new T.Vector3())
    .project(s.camera).x;
  const b = s.joints["8"].getWorldPosition(new T.Vector3()).project(s.camera).x;
  if (Math.abs(a - b) > 0.035) reversed = a > b;
  for (const e of entries) {
    if (e.behind) continue;
    const left =
      ["16", "15", "14", "13", "12", "11", "10", "9"].includes(e.id) !==
      reversed;
    e.card.style.left = left ? "9px" : "auto";
    e.card.style.right = left ? "auto" : "9px";
  }
  for (const { id, joint, line, dot, card, behind } of entries) {
    if (card.hidden) {
      line.style.display = dot.style.display = "none";
      if (behind) behind.visible = false;
      continue;
    }
    if (behind) {
      behind.visible = true;
      const end = joint.localToWorld(new T.Vector3(0, 0, -0.035));
      const depth = end.clone().project(s.camera).z,
        cr = card.getBoundingClientRect();
      const x = ((cr.left + cr.width / 2 - rect.left) / rect.width) * 2 - 1,
        y = 1 - ((cr.bottom - rect.top) / rect.height) * 2;
      const start = new T.Vector3(x, y, depth).unproject(s.camera);
      const projected = end.clone().project(s.camera);
      const shoulder = new T.Vector3(
        x,
        Math.min(y - 0.08, projected.y + 0.13),
        depth,
      ).unproject(s.camera);
      behind.geometry.dispose();
      behind.geometry = new T.BufferGeometry().setFromPoints([
        start,
        shoulder,
        end,
      ]);
      behind.computeLineDistances();
      continue;
    }
    const p = joint
        .localToWorld(
          new T.Vector3(0, ["7", "15"].includes(id) ? -0.036 : 0, 0.027),
        )
        .project(s.camera),
      cr = card.getBoundingClientRect();
    const x = ((p.x + 1) * rect.width) / 2,
      y = ((1 - p.y) * rect.height) / 2;
    const left = cr.left + cr.width / 2 < rect.left + rect.width / 2;
    const sx = (left ? cr.right : cr.left) - rect.left,
      sy = cr.top + cr.height / 2 - rect.top;
    line.setAttribute(
      "d",
      `M${sx},${sy} L${sx + (left ? 14 : -14)},${sy} L${x},${y}`,
    );
    line.classList.toggle("active", id === active);
    dot.setAttribute("cx", x);
    dot.setAttribute("cy", y);
    line.style.display = dot.style.display = p.z > 1 || p.z < -1 ? "none" : "";
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);
