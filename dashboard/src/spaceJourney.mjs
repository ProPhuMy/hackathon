// Space Journey choreography playhead and math module (pure, no Three.js import).
// Timeline: 0 (idle) -> 0.29 (pulling into wormhole) -> 0.70 (tunnel travel)
//           -> 0.70..0.80 (emerging / settling) -> 0.80..0.86 (charge)
//           -> 0.86..1.00 (burst / explosion) -> 1.0 (floating)

export const JOURNEY_SECONDS = 10;
export const RETURN_SPEED = 2;

// GLB dimensions: fridge is ~1.85 tall, body centered around [0, 0.925, 0], closed AABB:
// min: [-0.56, 0.00, -0.43], max: [0.56, 1.85, 0.67]
export const FRIDGE_AABB = {
  min: [-0.56, 0.0, -0.43],
  max: [0.56, 1.85, 0.67],
};

function clamp01(t) {
  return Math.min(1, Math.max(0, t));
}

function smoothstep(t) {
  const x = clamp01(t);
  return x * x * (3 - 2 * x);
}

function segment(t, start, end) {
  if (start === end) return t >= end ? 1 : 0;
  return smoothstep((t - start) / (end - start));
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function lerpV(a, b, t) {
  return [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
}

export function hermite(p, p0, p1, P0, P1, V0, V1) {
  const h = p1 - p0;
  if (h === 0) return [...P0];
  const t = (p - p0) / h;
  const t2 = t * t;
  const t3 = t2 * t;
  const h00 = 2 * t3 - 3 * t2 + 1;
  const h10 = t3 - 2 * t2 + t;
  const h01 = -2 * t3 + 3 * t2;
  const h11 = t3 - t2;
  return [
    h00 * P0[0] + h10 * h * V0[0] + h01 * P1[0] + h11 * h * V1[0],
    h00 * P0[1] + h10 * h * V0[1] + h01 * P1[1] + h11 * h * V1[1],
    h00 * P0[2] + h10 * h * V0[2] + h01 * P1[2] + h11 * h * V1[2],
  ];
}

export function advanceJourney(progress, travel, delta, reduced = false) {
  if (reduced) return travel ? 1 : 0;
  const dt = Math.max(0, Number.isFinite(delta) ? delta : 0);
  const speed = travel ? 1 / JOURNEY_SECONDS : -RETURN_SPEED / JOURNEY_SECONDS;
  return clamp01(progress + speed * dt);
}

export function phaseFor(progress, travel) {
  if (progress === 0) return 'idle';
  if (progress === 1) return 'floating';
  if (!travel) return 'returning';
  if (progress < 0.29) return 'pulling';
  if (progress < 0.70) return 'wormhole';
  return 'emerging';
}

export function canPickItem(progress) {
  return progress === 1;
}

// Pure helper returning deterministic floating anchor around floating fridge [0, 0.925, -30]
// Generates a 3D ellipsoid shell around destination center with aspect adaptation.
// Guarantees min distance between anchors >= 0.8 and min distance to fridge center axis >= 0.9.
export function floatingAnchor(index, count = 6, seed = 0, aspect = 1.6) {
  const n = Math.max(1, count);
  const tAsp = clamp01((aspect - 0.45) / (1.6 - 0.45));
  const rx = lerp(1.7, 3.2, tAsp);
  const ry = lerp(3.0, 1.9, tAsp);
  const rz = 1.4;

  const phi = Math.PI * (3 - Math.sqrt(5)); // Golden angle ~2.39996 rad
  const yNorm = n === 1 ? 0 : -0.72 + (index / (n - 1)) * 1.44;
  const rHorizontal = Math.sqrt(Math.max(0.1, 1 - yNorm * yNorm));
  const theta = index * phi + (seed ? (seed % 10) * 0.1 : 0);

  const x = rx * rHorizontal * Math.cos(theta);
  const y = 0.925 + ry * yNorm;
  const z = -30.0 + rz * rHorizontal * Math.sin(theta);

  return [x, y, z];
}

// Tunnel velocity constants
const V_TUNNEL = 50.7; // dz/dp along tunnel branch
const V_70 = 28.0;     // camera dz/dp at p=0.70 (>= 28)
const Z_64 = -3.2 - V_TUNNEL * (0.64 - 0.29); // -20.945
const DELTA_Z_64_70 = -0.06 * (V_TUNNEL + V_70) / 2; // -2.361
const Z_70 = Z_64 + DELTA_Z_64_70; // -23.306

export function sampleJourney(progress, aspect = 1.6) {
  const p = clamp01(progress);
  const mobile = aspect < 0.8;
  const aspectFactor = clamp01((1.2 - aspect) / 0.75); // 0 at landscape >=1.2, 1 at narrow portrait <=0.45

  // 1. Portal placement and metrics
  // Portal mouth is behind and to the left/up of fridge
  const portalPos = [-1.1, 1.3, -3.2];
  let portalRadius = 0;
  if (p < 0.15) {
    portalRadius = segment(p, 0.0, 0.15) * 1.8;
  } else if (p < 0.31) {
    portalRadius = 1.8;
  } else {
    portalRadius = (1 - segment(p, 0.31, 0.36)) * 1.8;
  }

  const portalIntensity = (p < 0.20)
    ? segment(p, 0.0, 0.20)
    : (p <= 0.31 ? 1 : (1 - segment(p, 0.31, 0.36)));

  const portalSwirl = segment(p, 0.0, 0.25);

  // 2. Camera framing poses
  const homeCamPos = mobile
    ? [lerp(1.8, 1.4, aspectFactor), lerp(2.0, 2.2, aspectFactor), lerp(5.2, 5.8, aspectFactor)]
    : [2.7, 1.6, 4.8];
  const homeTarget = mobile ? [0, 1.2, 0] : [-0.3, 0.9, 0];
  const homeFov = mobile ? lerp(36, 44, aspectFactor) : 34;

  // Re-fitted floating camera: fov <= 46 landscape (aspect >= 1.2), <= 54 portrait
  // Anchor cloud max |NDC| fits between 0.70 and 0.85 across all test aspects
  const tFov = clamp01((1.2 - aspect) / (1.2 - 0.45));
  const floatFov = lerp(44, 54, tFov);
  const tDist1 = clamp01((1.6 - aspect) / (1.6 - 0.45));
  const distBase = lerp(6.2, 8.8, Math.pow(tDist1, 1.15));
  const floatDist = aspect > 1.6 ? lerp(6.2, 5.2, clamp01((aspect - 1.6) / (2.4 - 1.6))) : distBase;
  const floatCamPos = [
    lerp(0.2, 0.0, aspectFactor),
    0.925,
    -30.0 + floatDist,
  ];
  const floatTarget = [0, 0.925, -30.0];

  let camPos = [...homeCamPos];
  let camTarget = [...homeTarget];
  let camFov = homeFov;

  // Camera trajectories
  if (p < 0.29) {
    // Hermite accelerating dive from home pose to portal mouth [-1.1, 1.3, -3.2]
    // Knot K0: p=0, homeCamPos, velocity [0, 0, 0]
    // Knot K1: intermediate point curving toward portal, monotonically increasing speed
    // Knot K2: p=0.29, portalPos, velocity [0, 0, -V_TUNNEL]
    const p1 = lerp(0.14, 0.13, aspectFactor);
    const s1 = lerp(29.0, 28.0, aspectFactor);
    const fBlend = lerp(0.28, 0.26, aspectFactor);

    const P0_cam = homeCamPos;
    const P2_cam = portalPos;
    const V0_cam = [0, 0, 0];
    const V2_cam = [0, 0, -V_TUNNEL];

    const P1_cam = [
      lerp(P0_cam[0], P2_cam[0], fBlend),
      lerp(P0_cam[1], P2_cam[1], fBlend),
      lerp(P0_cam[2], P2_cam[2], fBlend),
    ];
    const dir1 = [P2_cam[0] - P0_cam[0], P2_cam[1] - P0_cam[1], P2_cam[2] - P0_cam[2]];
    const len1 = Math.hypot(...dir1);
    const V1_cam = [dir1[0] / len1 * s1, dir1[1] / len1 * s1, dir1[2] / len1 * s1];

    if (p < p1) {
      camPos = hermite(p, 0, p1, P0_cam, P1_cam, V0_cam, V1_cam);
    } else {
      camPos = hermite(p, p1, 0.29, P1_cam, P2_cam, V1_cam, V2_cam);
    }

    const tTarget = segment(p, 0, 0.29);
    camTarget = lerpV(homeTarget, [portalPos[0], portalPos[1], portalPos[2] - 6.0], tTarget);

    const tFovEntry = smoothstep(p / 0.29);
    camFov = homeFov + (65 - homeFov) * tFovEntry;
  } else if (p < 0.64) {
    // Tunnel cruising at full speed (dz/dp = 50.7)
    // Lateral alignment starts with zero lateral velocity at 0.29 and smoothly aligns to centerline
    const tAlign = segment(p, 0.29, 0.35);
    const zCam = -3.2 - V_TUNNEL * (p - 0.29);
    camPos = [
      lerp(portalPos[0], 0, tAlign),
      lerp(portalPos[1], 0.925, tAlign),
      zCam,
    ];
    camTarget = [lerp(portalPos[0], 0, tAlign), lerp(portalPos[1], 0.925, tAlign), zCam - 6.0];
    if (p < 0.62) {
      camFov = 65 + Math.sin(p * 20) * 3 * segment(p, 0.31, 0.36) * (1 - segment(p, 0.56, 0.62));
    } else {
      const t = smoothstep((p - 0.62) / (0.80 - 0.62));
      camFov = 65 + (floatFov - 65) * t;
    }
  } else if (p < 0.70) {
    // C1 tunnel deceleration from 50.7 to >= 28.0 at p = 0.70
    const u = (p - 0.64) / 0.06;
    const intSmooth = (u * u * u - 0.5 * u * u * u * u) * 0.06;
    const zCam = Z_64 - (V_TUNNEL * (p - 0.64) - (V_TUNNEL - V_70) * intSmooth);
    camPos = [0, 0.925, zCam];
    camTarget = [0, 0.925, zCam - 6.0];

    const t = smoothstep((p - 0.62) / (0.80 - 0.62));
    camFov = 65 + (floatFov - 65) * t;
  } else if (p < 0.80) {
    // Hermite ease from tunnel exit [0, 0.925, Z_70] (vel [0, 0, -V_70]) to floatCamPos (vel [0, 0, 0])
    const P_70 = [0, 0.925, Z_70];
    const V_70_vec = [0, 0, -V_70];
    const V_80_vec = [0, 0, 0];
    camPos = hermite(p, 0.70, 0.80, P_70, floatCamPos, V_70_vec, V_80_vec);

    const t = segment(p, 0.70, 0.80);
    camTarget = lerpV([0, 0.925, Z_70 - 6.0], floatTarget, t);

    const tFovExit = smoothstep((p - 0.62) / (0.80 - 0.62));
    camFov = 65 + (floatFov - 65) * tFovExit;
  } else {
    camPos = [...floatCamPos];
    camTarget = [...floatTarget];
    camFov = floatFov;
  }

  // 3. Tunnel timing:
  // Tunnel must be 0 until camera crosses portal plane (z <= -3.2, which happens at p >= 0.29).
  // Ramp tunnel 0->1 over 0.29->0.32, fade out 0.75->0.79 (tunnel > 0.5 when flash > 0.5, 0 before 0.80)
  let tunnel = 0;
  if (p >= 0.29 && p < 0.75) {
    tunnel = segment(p, 0.29, 0.32);
  } else if (p >= 0.75 && p < 0.79) {
    tunnel = 1 - segment(p, 0.75, 0.79);
  }

  const tunnelSpeed = p < 0.29 ? 0 : (p < 0.70 ? 1 + segment(p, 0.32, 0.50) * 0.8 : (1 - segment(p, 0.70, 0.76)));
  const warp = p < 0.18 ? 0 : (p < 0.32 ? segment(p, 0.18, 0.32) : (p < 0.68 ? 1 : 1 - segment(p, 0.68, 0.76)));

  const flash = p < 0.70 ? 0 : (p < 0.74 ? segment(p, 0.70, 0.74) : (1 - segment(p, 0.74, 0.80)));
  const exitPortal = {
    position: [0, 0.925, -28],
    radius: segment(p, 0.70, 0.74) * 2.2 * (1 - segment(p, 0.76, 0.80)),
    intensity: segment(p, 0.70, 0.74) * (1 - segment(p, 0.76, 0.80)),
  };

  const nebulaHue = segment(p, 0.50, 0.76);

  // 4. Fridge trajectory
  let fridgePos = [0, 0, 0];
  let fridgeRot = [0, 0, 0];

  // Spaghettification stretch peaks at portal crossing (p ~ 0.22)
  const st = segment(p, 0.10, 0.22) * (1 - segment(p, 0.22, 0.29));
  const fridgeScale = [1 - 0.45 * st, 1 + 0.6 * st, 1 - 0.45 * st];

  const ROT_Y_ENTRY = 1.2 * Math.PI;
  const SPIN_END = ROT_Y_ENTRY + (0.70 - 0.29) * 22;
  const SPIN_REST = 6 * Math.PI;

  const P0_f = [0, 0, 0];
  const V0_f = [0, 0, 0];
  const P1_f = [-1.1, -0.15, -6.2];
  const V1_f = [0, 0, -V_TUNNEL];

  if (p < 0.29) {
    fridgePos = hermite(p, 0, 0.29, P0_f, P1_f, V0_f, V1_f);
    const u = clamp01(p / 0.29);
    fridgeRot = [0.35 * u, ROT_Y_ENTRY * u, 0.25 * u];
  } else if (p < 0.70) {
    const tAlign = segment(p, 0.29, 0.35);
    fridgePos = [
      lerp(-1.1, 0, tAlign),
      lerp(-0.15, 0, tAlign),
      camPos[2] - 3.0,
    ];
    const w = segment(p, 0.29, 0.34);
    fridgeRot = [
      lerp(0.35, Math.sin(p * 38) * 0.35, w),
      ROT_Y_ENTRY + (p - 0.29) * 22,
      lerp(0.25, Math.cos(p * 32) * 0.35, w),
    ];
  } else if (p < 0.80) {
    const t = clamp01((p - 0.70) / 0.10);
    const e = 1 - Math.pow(1 - t, 3);
    fridgePos = [0, 0, lerp(Z_70 - 3.0, -30.0, e)];
    const rotX = lerp(Math.sin(0.70 * 38) * 0.35, 0, e);
    const rotY = lerp(SPIN_END, SPIN_REST, e);
    const rotZ = lerp(Math.cos(0.70 * 32) * 0.35, 0, e);
    fridgeRot = [rotX, rotY, rotZ];
  } else {
    fridgePos = [0, 0, -30.0];
    fridgeRot = [0, SPIN_REST, 0];
  }

  // 5. Charge and burst timeline (replaces door and release)
  const charge = p < 0.80 ? 0 : (p < 0.86 ? segment(p, 0.80, 0.86) : 1);
  const burst = p < 0.86 ? 0 : clamp01((p - 0.86) / 0.14);
  const light = charge * (1 - segment(burst, 0.0, 0.15));

  return {
    camera: { position: camPos, target: camTarget, fov: camFov },
    fridge: { position: fridgePos, rotation: fridgeRot, scale: fridgeScale },
    portal: { position: portalPos, radius: portalRadius, intensity: portalIntensity, swirl: portalSwirl },
    tunnel,
    tunnelSpeed,
    warp,
    flash,
    exitPortal,
    nebulaHue,
    light,
    charge,
    burst,
  };
}
