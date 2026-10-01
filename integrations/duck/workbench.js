import { Router } from "express";
import { createSimulationRouter } from "./simulation.js";
export function createWorkbenchRouter({
  generate,
  library,
  origins = [
    "https://carrotgoose.online",
    "https://www.carrotgoose.online",
    "https://carrotduck.online",
  ],
} = {}) {
  const router = Router(),
    visitors = new Map();
  let day = -1,
    total = 0,
    active = 0;
  router.use((req, res, next) => {
    res.setHeader("Cache-Control", "no-store");
    if (req.method !== "POST" || req.path !== "/plan")
      return res.sendStatus(404);
    const origin = req.headers.origin;
    if (!origins.includes(origin))
      return res
        .status(403)
        .json({ error: "Open the workbench to generate a motion." });
    if (JSON.stringify(req.body || {}).length > 150000)
      return res.status(413).json({ error: "Motion request is too large." });
    const now = Date.now(),
      d = Math.floor(now / 86400000);
    if (day !== d) {
      day = d;
      total = 0;
      visitors.clear();
    }
    if (total >= 100 || active >= 2)
      return res
        .status(429)
        .json({
          error:
            "Motion planning is busy or its daily allowance has been reached. Please try later.",
        });
    const key = req.ip || req.socket.remoteAddress;
    let v = visitors.get(key);
    if (!v) {
      if (visitors.size >= 1000) return res.sendStatus(429);
      v = { start: now, count: 0 };
      visitors.set(key, v);
    }
    if (now - v.start >= 3600000) {
      v.start = now;
      v.count = 0;
    }
    if (v.count >= 20)
      return res
        .status(429)
        .json({ error: "Please wait before generating more motions." });
    v.count++;
    total++;
    next();
  });
  router.use(
    createSimulationRouter({
      library,
      identify: (req) => "workbench:" + req.ip,
      generate: async (...args) => {
        active++;
        try {
          return await generate(...args);
        } finally {
          active--;
        }
      },
    }),
  );
  return router;
}
