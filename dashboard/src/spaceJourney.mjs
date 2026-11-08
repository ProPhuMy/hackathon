// Space Journey choreography playhead and math module (pure, no Three.js import).
// Timeline: 0 (idle) -> 0.30 (pulling into wormhole) -> 0.72 (tunnel travel)
//           -> 0.82..1.0 (emerging, door open, item ejection) -> 1.0 (floating)

export const JOURNEY_SECONDS = 9;
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
  if (progress < 0.30) return 'pulling';
  if (progress < 0.72) return 'wormhole';
  return 'emerging';
}

export function canPickItem(progress) {
  return progress === 1;
}

// Pure helper returning deterministic floating anchor around floating fridge [0, 0.925, -30]
// Guarantees min distance between anchors >= 0.55 and min distance to fridge AABB >= 0.35.
export function floatingAnchor(index, count = 6, seed = 0) {
  const n = Math.max(1, count);
  const baseAngle = (index / n) * Math.PI * 2 + 0.35 + (seed ? (seed % 10) * 0.05 : 0);
  
  // Elliptical distribution around fridge center [0, 0.925, -30]
  // Fridge half-extents: x=0.56, y=0.925, z=0.55.
  const rx = 1.45;
  const ry = 1.60;
  
  const x = Math.cos(baseAngle) * rx;
  const y = 0.925 + Math.sin(baseAngle) * ry;
  const z = -30 + Math.sin(baseAngle * 2 + 0.5) * 0.45;
  
  return [x, y, z];
}

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

  // 2. Camera trajectories
  const homeCamPos = mobile
    ? [lerp(1.8, 1.4, aspectFactor), lerp(2.0, 2.2, aspectFactor), lerp(5.2, 5.8, aspectFactor)]
    : [2.7, 1.6, 4.8];
  const homeTarget = mobile ? [0, 1.2, 0] : [-0.3, 0.9, 0];
  const homeFov = mobile ? lerp(36, 44, aspectFactor) : 34;

  const floatDist = lerp(8.8, 13.0, aspectFactor);
  const floatCamPos = [
    lerp(0.5, 0.0, aspectFactor),
    1.15,
    -30.0 + floatDist,
  ];
  const floatTarget = [0, 0.925, -30.0];
  const floatFov = lerp(38, 48, aspectFactor);

  let camPos = [...homeCamPos];
  let camTarget = [...homeTarget];
  let camFov = homeFov;

  if (p < 0.18) {
    const t = segment(p, 0.0, 0.18);
    camPos = lerpV(homeCamPos, [1.0, 1.5, 3.0], t);
    camTarget = lerpV(homeTarget, [-0.5, 1.1, -0.5], t);
    camFov = lerp(homeFov, 38, t);
  } else if (p < 0.29) {
    // Camera dives into the portal mouth, reaching ring center [-1.1, 1.3, -3.2] at exactly p = 0.29
    const t = segment(p, 0.18, 0.29);
    camPos = lerpV([1.0, 1.5, 3.0], portalPos, t);
    camTarget = lerpV([-0.5, 1.1, -0.5], [portalPos[0], portalPos[1], portalPos[2] - 6], t);
    camFov = lerp(38, 65, t);
  } else if (p < 0.72) {
    // Tunnel: camera traverses from portalPos [-1.1, 1.3, -3.2] to exit [-25]
    const tTunnel = (p - 0.29) / (0.72 - 0.29);
    // Align camera X & Y to tunnel centerline [0, 0.925] over 0.29..0.35
    const tAlign = segment(p, 0.29, 0.35);
    const zCam = lerp(-3.2, -25.0, tTunnel);
    camPos = [
      lerp(portalPos[0], 0, tAlign),
      lerp(portalPos[1], 0.925, tAlign),
      zCam,
    ];
    camTarget = [0, 0.925, zCam - 6.0];
    camFov = 65 + Math.sin(p * 20) * 3 * segment(p, 0.31, 0.36) * (1 - segment(p, 0.66, 0.72));
  } else if (p < 0.82) {
    const t = segment(p, 0.72, 0.82);
    camPos = lerpV([0, 0.925, -25.0], floatCamPos, t);
    camTarget = lerpV([0, 0.925, -31.0], floatTarget, t);
    camFov = lerp(65, floatFov, t);
  } else {
    camPos = [...floatCamPos];
    camTarget = [...floatTarget];
    camFov = floatFov;
  }

  // 3. Tunnel timing:
  // Tunnel must be 0 until camera crosses portal plane (z <= -3.2, which happens at p >= 0.29).
  // Ramp tunnel 0->1 over 0.29->0.32
  let tunnel = 0;
  if (p >= 0.29 && p < 0.70) {
    tunnel = segment(p, 0.29, 0.32);
  } else if (p >= 0.70 && p < 0.78) {
    tunnel = 1 - segment(p, 0.70, 0.78);
  }

  const tunnelSpeed = p < 0.29 ? 0 : (p < 0.70 ? 1 + segment(p, 0.32, 0.50) * 0.8 : (1 - segment(p, 0.70, 0.76)));
  const warp = p < 0.18 ? 0 : (p < 0.32 ? segment(p, 0.18, 0.32) : (p < 0.68 ? 1 : 1 - segment(p, 0.68, 0.76)));

  const flash = p < 0.70 ? 0 : (p < 0.74 ? segment(p, 0.70, 0.74) : (1 - segment(p, 0.74, 0.80)));
  const exitPortal = {
    position: [0, 0.925, -28],
    radius: segment(p, 0.70, 0.74) * 2.2 * (1 - segment(p, 0.76, 0.82)),
    intensity: segment(p, 0.70, 0.74) * (1 - segment(p, 0.76, 0.82)),
  };

  const nebulaHue = segment(p, 0.50, 0.76);

  // 4. Fridge trajectory
  let fridgePos = [0, 0, 0];
  let fridgeRot = [0, 0, 0];

  // Spaghettification stretch peaks at portal crossing (p = 0.24)
  const st = segment(p, 0.10, 0.24) * (1 - segment(p, 0.24, 0.31));
  const fridgeScale = [1 - 0.45 * st, 1 + 0.6 * st, 1 - 0.45 * st];

  const ROT_Y_ENTRY = 1.2 * Math.PI;
  const SPIN_END = ROT_Y_ENTRY + (0.72 - 0.29) * 22; // ~13.23 rad
  const SPIN_REST = 6 * Math.PI; // ~18.85 rad

  if (p < 0.29) {
    if (p < 0.24) {
      const tLin = clamp01(p / 0.24);
      const tAcc = tLin * tLin;
      fridgePos = [
        lerp(0, -1.1, tAcc),
        lerp(0, 0.375, tAcc),
        lerp(0, -3.2, tAcc),
      ];
    } else {
      const tLin2 = (p - 0.24) / (0.29 - 0.24);
      fridgePos = [
        -1.1,
        0.375,
        lerp(-3.2, -6.2, tLin2),
      ];
    }
    const u = clamp01(p / 0.29);
    fridgeRot = [0.35 * u, ROT_Y_ENTRY * u, 0.25 * u];
  } else if (p < 0.72) {
    const tTunnel = (p - 0.29) / (0.72 - 0.29);
    const zCam = lerp(-3.2, -25.0, tTunnel);
    const zFridge = zCam - 3.0;
    const tAlign = segment(p, 0.29, 0.35);
    fridgePos = [
      lerp(-1.1, 0, tAlign),
      lerp(0.375, 0, tAlign),
      zFridge,
    ];
    const w = segment(p, 0.29, 0.34);
    fridgeRot = [
      lerp(0.35, Math.sin(p * 38) * 0.35, w),
      ROT_Y_ENTRY + (p - 0.29) * 22,
      lerp(0.25, Math.cos(p * 32) * 0.35, w),
    ];
  } else if (p < 0.82) {
    const tSettle = segment(p, 0.72, 0.82);
    fridgePos = [0, 0, lerp(-28.0, -30.0, tSettle)];
    const t = clamp01((p - 0.72) / 0.10);
    const e = 1 - Math.pow(1 - t, 3);
    const rotX = lerp(Math.sin(0.72 * 38) * 0.35, 0, e);
    const rotY = lerp(SPIN_END, SPIN_REST, e);
    const rotZ = lerp(Math.cos(0.72 * 32) * 0.35, 0, e);
    fridgeRot = [rotX, rotY, rotZ];
  } else {
    fridgePos = [0, 0, -30.0];
    fridgeRot = [0, SPIN_REST, 0];
  }

  // 5. Door opening & interior light & release
  let door = 0;
  if (p >= 0.82) {
    door = -2.05 * segment(p, 0.82, 0.88);
  }

  const light = segment(p, 0.82, 0.88);
  const release = p < 0.86 ? 0 : segment(p, 0.86, 1.0);

  return {
    camera: { position: camPos, target: camTarget, fov: camFov },
    fridge: { position: fridgePos, rotation: fridgeRot, scale: fridgeScale },
    door,
    portal: { position: portalPos, radius: portalRadius, intensity: portalIntensity, swirl: portalSwirl },
    tunnel,
    tunnelSpeed,
    warp,
    flash,
    exitPortal,
    nebulaHue,
    light,
    release,
  };
}
