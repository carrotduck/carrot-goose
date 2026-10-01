import * as T from "three";
// Photo-based approximation. Dimensions and hinge placement are not factory CAD.
export function createRobot(scene) {
  const mat = (c, m = 0) =>
    new T.MeshStandardMaterial({ color: c, metalness: m, roughness: 0.5 });
  const white = mat("#f2f1ed", 0.12),
    black = mat("#171a20", 0.08),
    metal = mat("#959f9e", 0.8),
    rubber = mat("#393d3c"),
    blue = mat("#322632", 0.3);
  const root = new T.Group();
  scene.add(root);
  const joints = {};
  function group(p, n, xyz) {
    let g = new T.Group();
    g.name = n;
    g.position.set(...xyz);
    p.add(g);
    return g;
  }
  function mesh(p, geo, xyz, material = white) {
    let m = new T.Mesh(geo, material);
    m.position.set(...xyz);
    m.castShadow = true;
    m.receiveShadow = true;
    p.add(m);
    return m;
  }
  const box = (p, pos, size, m = white) =>
    mesh(p, new T.BoxGeometry(...size), pos, m);
  function cylinder(p, pos, r, len, m = metal) {
    let x = mesh(p, new T.CylinderGeometry(r, r, len, 32), pos, m);
    x.rotation.x = Math.PI / 2;
    return x;
  }
  function plate(p, pos, w, h, holes = [], m = white) {
    let s = new T.Shape();
    const r = 0.005;
    s.moveTo(-w / 2 + r, -h / 2);
    s.lineTo(w / 2 - r, -h / 2);
    s.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
    s.lineTo(w / 2, h / 2 - r);
    s.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2);
    s.lineTo(-w / 2 + r, h / 2);
    s.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
    s.lineTo(-w / 2, -h / 2 + r);
    s.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
    for (const [x, y, hr] of holes) {
      let path = new T.Path();
      path.absarc(x, y, hr, 0, Math.PI * 2, true);
      s.holes.push(path);
    }
    return mesh(
      p,
      new T.ExtrudeGeometry(s, {
        depth: 0.002,
        bevelEnabled: true,
        bevelSegments: 2,
        steps: 1,
        bevelSize: 0.0005,
        bevelThickness: 0.0004,
      }),
      pos,
      m,
    );
  }
  function screw(p, x, y, z, r = 0.0025) {
    cylinder(p, [x, y, z], r, 0.0015, black);
    box(p, [x, y, z + 0.001], [r, 0.00065, 0.0004], metal);
  }
  function label(p, text, pos, w, h) {
    let c = document.createElement("canvas");
    c.width = 256;
    c.height = 128;
    let ctx = c.getContext("2d");
    ctx.fillStyle = "#242826";
    ctx.fillRect(0, 0, 256, 128);
    ctx.fillStyle = "#e0dfcc";
    ctx.font = "bold 34px sans-serif";
    ctx.fillText(text, 12, 52);
    ctx.font = "18px sans-serif";
    ctx.fillText("BUS SERVO", 12, 91);
    let tex = new T.CanvasTexture(c);
    tex.colorSpace = T.SRGBColorSpace;
    return mesh(
      p,
      new T.PlaneGeometry(w, h),
      pos,
      new T.MeshStandardMaterial({ map: tex, roughness: 0.7 }),
    );
  }
  function servo(p, pos, w = 0.035, h = 0.049) {
    box(p, pos, [w, h, 0.035], black);
    box(p, [pos[0], pos[1] + h / 2, pos[2]], [w + 0.006, 0.003, 0.038], black);
    label(p, "824HV", [pos[0], pos[1], pos[2] + 0.0178], w * 0.8, h * 0.5);
  }
  function wire(p, points) {
    let curve = new T.CatmullRomCurve3(points.map((v) => new T.Vector3(...v)));
    return mesh(
      p,
      new T.TubeGeometry(curve, 24, 0.0015, 6, false),
      [0, 0, 0],
      rubber,
    );
  }
  function polygon(p, points, z, material = white) {
    const s = new T.Shape();
    s.moveTo(...points[0]);
    points.slice(1).forEach((v) => s.lineTo(...v));
    s.closePath();
    return mesh(
      p,
      new T.ExtrudeGeometry(s, {
        depth: 0.002,
        bevelEnabled: true,
        bevelSize: 0.001,
        bevelThickness: 0.0008,
        bevelSegments: 3,
      }),
      [0, 0, z],
      material,
    );
  }
  // Folded shield panels and waist bracket follow the front reference.

  polygon(
    root,
    [
      [-0.077, 0.353],
      [-0.055, 0.359],
      [0, 0.354],
      [0.055, 0.359],
      [0.077, 0.353],
      [0.077, 0.284],
      [0.052, 0.272],
      [0, 0.259],
      [-0.052, 0.272],
      [-0.077, 0.284],
    ],
    0.036,
  );
  plate(root, [0, 0.311, -0.042], 0.15, 0.099);
  box(root, [0, 0.353, 0], [0.147, 0.004, 0.07]);
  box(root, [0, 0.279, -0.012], [0.118, 0.004, 0.052]);
  box(root, [0, 0.32, -0.017], [0.112, 0.062, 0.031], black);
  polygon(
    root,
    [
      [-0.066, 0.282],
      [0.066, 0.282],
      [0.052, 0.231],
      [-0.052, 0.231],
    ],
    0.004,
  );
  for (const side of [-1, 1]) {
    const wall = plate(root, [side * 0.076, 0.315, -0.003], 0.077, 0.075, [
      [0, 0, 0.022],
    ]);
    wall.rotation.y = Math.PI / 2;
    const ports = group(root, "side_ports_" + side, [
      side * 0.077,
      0.315,
      -0.006,
    ]);
    ports.rotation.y = (side * Math.PI) / 2;
    box(ports, [0, 0, 0], [0.029, 0.06, 0.005], black);
    for (const y of [-0.019, 0.004, 0.022]) {
      box(ports, [0, y, 0.003], [0.023, 0.014, 0.007], metal);
      box(
        ports,
        [0, y, 0.007],
        [0.018, 0.01, 0.002],
        y === 0.004 ? blue : black,
      );
    }
    for (const y of [0.346, 0.283, 0.254])
      screw(root, side * (y < 0.26 ? 0.047 : 0.069), y, 0.04, 0.0018);
  }

  const pulse = [
    [-0.058, 0.315, 0.039],
    [-0.024, 0.315, 0.039],
    [-0.015, 0.334, 0.039],
    [0, 0.291, 0.039],
    [0.011, 0.315, 0.039],
    [0.057, 0.315, 0.039],
  ];
  root.add(
    new T.Line(
      new T.BufferGeometry().setFromPoints(
        pulse.map((p) => new T.Vector3(...p)),
      ),
      new T.LineBasicMaterial({ color: 0x172623 }),
    ),
  );
  for (const side of [-1, 1]) {
    wire(root, [
      [side * 0.061, 0.34, -0.029],
      [side * 0.082, 0.3, -0.031],
      [side * 0.075, 0.27, -0.01],
    ]);
    screw(root, side * 0.067, 0.352, 0.04);
  }
  // Rear camera cable and low display, visible in the supplied rear view.
  wire(root, [
    [0.063, 0.329, -0.045],
    [0.075, 0.346, -0.074],
    [0.012, 0.311, -0.084],
    [-0.055, 0.329, -0.072],
    [-0.026, 0.387, -0.027],
  ]);
  box(root, [0, 0.247, -0.027], [0.024, 0.012, 0.003], black);
  // Bracketed head: yaw ring, U bracket, tilting camera casing.
  cylinder(root, [0, 0.371, 0], 0.016, 0.006, black).rotation.x = 0;
  joints.yaw = group(root, "PWM2_yaw", [0, 0.378, 0]);
  box(joints.yaw, [0, 0, 0], [0.049, 0.004, 0.034]);
  for (const side of [-1, 1]) {
    const bracket = plate(joints.yaw, [side * 0.029, 0.018, 0], 0.033, 0.044, [
      [0, 0.005, 0.003],
    ]);
    bracket.rotation.y = Math.PI / 2;
  }

  joints.pitch = group(joints.yaw, "PWM1_pitch", [0, 0.047, 0]);
  polygon(
    joints.pitch,
    [
      [-0.026, 0.027],
      [-0.021, 0.035],
      [0.021, 0.035],
      [0.026, 0.027],
      [0.026, -0.016],
      [0.018, -0.03],
      [-0.018, -0.03],
      [-0.026, -0.016],
    ],
    0.029,
  );
  box(joints.pitch, [0, 0.012, -0.008], [0.05, 0.043, 0.046], white);
  box(joints.pitch, [0, -0.018, -0.006], [0.037, 0.019, 0.027], black);
  for (const side of [-1, 1]) {
    const cheek = polygon(
      joints.pitch,
      [
        [-0.025, 0.035],
        [0.014, 0.035],
        [0.024, 0.023],
        [0.023, -0.019],
        [0.005, -0.024],
        [-0.006, -0.011],
        [-0.023, -0.009],
      ],
      0,
    );
    cheek.rotation.y = (side * Math.PI) / 2;
    cheek.position.x = side * 0.029;
    const rim = box(
      joints.pitch,
      [side * 0.027, 0.035, -0.002],
      [0.003, 0.01, 0.047],
    );
    rim.rotation.z = side * 0.3;
    const screwAxis = group(joints.pitch, "head_side_screws", [
      side * 0.031,
      0,
      0,
    ]);
    screwAxis.rotation.y = (side * Math.PI) / 2;
    screw(screwAxis, 0, 0.015, 0, 0.0022);
    screw(screwAxis, 0.009, -0.009, 0, 0.0022);
  }
  box(joints.pitch, [0, -0.027, 0.001], [0.05, 0.007, 0.047], white);
  cylinder(joints.pitch, [0, 0, 0.03], 0.015, 0.004, black);
  cylinder(joints.pitch, [0, 0, 0.034], 0.0105, 0.003, blue);
  cylinder(joints.pitch, [0, 0, 0.038], 0.0078, 0.001, blue);
  for (const x of [-0.02, 0.02])
    for (const y of [-0.032, 0.032]) screw(joints.pitch, x, y, 0.032, 0.0016);
  box(joints.pitch, [0, 0.022, 0.031], [0.0012, 0.025, 0.0007], metal);
  wire(joints.yaw, [
    [0.021, 0, -0.017],
    [0.031, 0.03, -0.024],
    [0.02, 0.049, -0.029],
  ]);
  joints.pitch.scale.set(0.94, 0.94, 0.94);
  const lensRing = mesh(
    joints.pitch,
    new T.TorusGeometry(0.0114, 0.0012, 12, 48),
    [0, 0, 0.039],
    metal,
  );
  const glass = mesh(
    joints.pitch,
    new T.SphereGeometry(0.0076, 24, 16),
    [0, 0, 0.038],
    new T.MeshPhysicalMaterial({
      color: "#111b25",
      metalness: 0.15,
      roughness: 0.08,
      clearcoat: 1,
    }),
  );
  glass.scale.z = 0.28;
  const reflection = mesh(
    joints.pitch,
    new T.SphereGeometry(0.0015, 12, 8),
    [-0.003, 0.003, 0.0405],
    new T.MeshBasicMaterial({ color: "#a2b6ca" }),
  );
  reflection.scale.z = 0.15;
  // Arm joints remain explicitly provisional. Thin plates and hollow grippers follow the photo.
  for (const [side, ids] of [
    [1, ["6", "7", "8"]],
    [-1, ["14", "15", "16"]],
  ]) {
    let a = group(root, "BUS_" + ids[2], [side * 0.106, 0.344, 0]);
    let b = group(a, "BUS_" + ids[1], [0, 0, 0]);
    let c = group(b, "BUS_" + ids[0], [0, -0.09, 0]);
    ids.forEach((id, i) => (joints[id] = [c, b, a][i]));
    plate(b, [0, 0, 0.026], 0.049, 0.034, [[0, 0, 0.007]]);
    plate(b, [0, 0, -0.025], 0.049, 0.034);
    box(b, [0, 0.015, 0], [0.044, 0.003, 0.051]);
    cylinder(b, [0, 0, 0.029], 0.007, 0.005, black);
    for (const x of [-0.017, 0.017]) screw(b, x, 0, 0.029, 0.002);
    servo(b, [0, -0.048, 0], 0.031, 0.044);
    plate(b, [0, -0.049, 0.024], 0.043, 0.052, [
      [0, 0.014, 0.006],
      [0, -0.014, 0.006],
    ]);
    for (const y of [-0.036, -0.062]) {
      cylinder(b, [0, y, 0.027], 0.005, 0.003, black);
      for (const x of [-0.013, 0.013]) screw(b, x, y, 0.028, 0.0018);
    }
    wire(b, [
      [side * 0.016, -0.015, -0.018],
      [side * 0.025, -0.05, -0.024],
      [side * 0.016, -0.081, -0.012],
    ]);
    cylinder(c, [0, 0, 0.022], 0.009, 0.006, black);
    plate(c, [0, -0.012, 0.022], 0.032, 0.034, [[0, 0.01, 0.006]]);
    box(c, [0, -0.038, 0], [0.027, 0.031, 0.027], black);
    // A folded palm with a side cutout and three curved finger layers.
    const palm = group(c, "palm_" + side, [0, 0, 0]);
    const wallShape = new T.Shape();
    wallShape.moveTo(-0.022, -0.026);
    wallShape.lineTo(0.022, -0.026);
    wallShape.lineTo(0.022, -0.093);
    wallShape.lineTo(0.015, -0.102);
    wallShape.lineTo(-0.022, -0.102);
    wallShape.closePath();
    const hole = new T.Path();
    hole.moveTo(-0.011, -0.057);
    hole.lineTo(0.011, -0.057);
    hole.lineTo(0.011, -0.075);
    hole.lineTo(0, -0.084);
    hole.lineTo(-0.011, -0.075);
    hole.closePath();
    wallShape.holes.push(hole);
    for (const z of [-0.006, 0.006, 0.018]) {
      const hole = new T.Path();
      hole.absarc(z, -0.094, 0.0023, 0, Math.PI * 2, true);
      wallShape.holes.push(hole);
    }
    const wall = mesh(
      palm,
      new T.ExtrudeGeometry(wallShape, {
        depth: 0.002,
        bevelEnabled: true,
        bevelSize: 0.0005,
        bevelThickness: 0.0004,
        bevelSegments: 2,
      }),
      [side * 0.014, 0, -0.001],
    );
    wall.rotation.y = (side * Math.PI) / 2;
    plate(palm, [0, -0.039, 0.023], 0.03, 0.026, [[side * 0.008, 0, 0.0014]]);
    for (const z of [-0.016, -0.002, 0.012]) {
      const shape = new T.Shape();
      const pts = [
        [-0.016, -0.061],
        [-0.02, -0.095],
        [-0.012, -0.11],
        [0.009, -0.122],
        [0.017, -0.119],
        [0.017, -0.114],
        [0.008, -0.116],
        [-0.007, -0.106],
        [-0.012, -0.093],
        [-0.009, -0.061],
      ];
      const mirror = -side;
      shape.moveTo(pts[0][0] * mirror, pts[0][1]);
      pts.slice(1).forEach((p) => shape.lineTo(p[0] * mirror, p[1]));
      shape.closePath();
      mesh(
        palm,
        new T.ExtrudeGeometry(shape, {
          depth: 0.003,
          bevelEnabled: true,
          bevelSize: 0.0008,
          bevelThickness: 0.0005,
          bevelSegments: 3,
        }),
        [0, 0, z],
      );
    }
    const thumb = polygon(
      palm,
      [
        [side * 0.013, -0.065],
        [side * -0.012, -0.08],
        [side * -0.018, -0.087],
        [side * -0.012, -0.093],
        [side * 0.015, -0.079],
      ],
      0.027,
    );
    screw(palm, 0, -0.032, 0.026, 0.0018);
  }
  // Exposed hip/knee servos and folded leg brackets, with photographed broad feet.
  for (const side of [-1, 1]) {
    let x = side * 0.043;
    let start = root.children.length;
    box(root, [x, 0.246, 0], [0.048, 0.029, 0.045], white);
    cylinder(root, [x, 0.248, 0.028], 0.007, 0.006, black);
    screw(root, x - side * 0.018, 0.248, 0.029, 0.002);
    const hipParts = root.children.slice(start);
    start = root.children.length;
    servo(root, [x, 0.209, 0.003], 0.047, 0.047);
    plate(root, [x, 0.179, 0.033], 0.055, 0.04);
    for (const side2 of [-1, 1]) {
      box(root, [x + side2 * 0.028, 0.199, 0], [0.002, 0.075, 0.06]);
      for (const y of [0.218, 0.167])
        screw(root, x + side2 * 0.022, y, 0.034, 0.0017);
    }
    box(root, [x, 0.161, 0], [0.055, 0.003, 0.061]);
    cylinder(root, [x, 0.154, 0.033], 0.01, 0.004, black);
    screw(root, x - side * 0.018, 0.154, 0.035, 0.002);
    const thighParts = root.children.slice(start);
    start = root.children.length;
    servo(root, [x, 0.116, 0.016], 0.048, 0.047);
    for (const side2 of [-1, 1])
      box(root, [x + side2 * 0.028, 0.115, 0.006], [0.002, 0.064, 0.062]);
    box(root, [x, 0.083, 0.006], [0.057, 0.002, 0.063]);
    box(root, [x, 0.075, 0], [0.055, 0.003, 0.061]);
    plate(root, [x, 0.053, 0.034], 0.053, 0.045, [[0, 0, 0.006]]);
    for (const y of [0.04, 0.066]) screw(root, x, y, 0.037, 0.0025);
    cylinder(root, [x, 0.052, 0.037], 0.006, 0.003, black);
    const shinParts = root.children.slice(start);
    start = root.children.length;
    const foot = polygon(
      root,
      [
        [-0.04, -0.045],
        [0.04, -0.045],
        [0.04, 0.032],
        [0.029, 0.051],
        [-0.029, 0.051],
        [-0.04, 0.032],
      ],
      0,
    );
    foot.rotation.x = -Math.PI / 2;
    foot.position.set(x, 0.017, 0.018);
    for (const edge of [-1, 1]) {
      box(root, [x + edge * 0.039, 0.02, 0.012], [0.0015, 0.011, 0.083]);
      screw(root, x + edge * 0.022, 0.021, 0.048, 0.0015);
    }
    servo(root, [x, 0.033, 0.009], 0.04, 0.022);
    box(root, [x, 0.01, 0.025], [0.077, 0.005, 0.098], rubber);
    const footParts = root.children.slice(start);
    const ids =
      side === 1 ? ["5", "4", "3", "2", "1"] : ["13", "12", "11", "10", "9"];
    const hinges = ids.map((id, i) => {
      const g = group(root, "BUS_" + id, [
        x,
        [0.246, 0.228, 0.154, 0.052, 0.033][i],
        0,
      ]);
      joints[id] = g;
      return g;
    });
    root.updateMatrixWorld(true);
    hipParts.forEach((m) => hinges[0].attach(m));
    thighParts.forEach((m) => hinges[1].attach(m));
    shinParts.forEach((m) => hinges[2].attach(m));
    footParts.forEach((m) => hinges[4].attach(m));
    for (let i = 4; i > 0; i--) hinges[i - 1].attach(hinges[i]);
    const rearLabel = label(
      hinges[2],
      "824HV",
      [0, -0.034, -0.021],
      0.035,
      0.022,
    );
    rearLabel.rotation.y = Math.PI;
    wire(hinges[1], [
      [0, 0, -0.025],
      [side * 0.02, -0.035, -0.037],
      [0, -0.062, -0.025],
    ]);
    wire(hinges[2], [
      [0, 0, -0.025],
      [side * 0.014, -0.035, -0.031],
      [0, -0.065, -0.025],
    ]);
  }
  return { root, joints };
}
