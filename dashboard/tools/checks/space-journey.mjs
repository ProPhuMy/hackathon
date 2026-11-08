import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  advanceJourney,
  phaseFor,
  canPickItem,
  floatingAnchor,
  sampleJourney,
  JOURNEY_SECONDS,
  RETURN_SPEED,
  FRIDGE_AABB,
} from '../../src/spaceJourney.mjs';

// Verify constants
assert.equal(JOURNEY_SECONDS, 10);
assert.equal(RETURN_SPEED, 2);

// 1. advanceJourney assertions
// Exit works from any entry phase, and repeating entry never overshoots.
for (const start of [0.1, 0.35, 0.7, 1]) {
  let p = start;
  for (let i = 0; i < 400; i++) p = advanceJourney(p, false, 1 / 60);
  assert.equal(p, 0);
}

let p = 0;
for (let i = 0; i < 700; i++) p = advanceJourney(p, true, 1 / 60);
assert.equal(p, 1);

// Resume from background tab with large delta
assert.equal(advanceJourney(0.2, true, 50), 1);
assert.equal(advanceJourney(0.8, false, 50), 0);

// Negative or NaN delta treated as 0
assert.equal(advanceJourney(0.5, true, -1), 0.5);
assert.equal(advanceJourney(0.5, true, Number.NaN), 0.5);

// Reduced motion instant jumps
assert.equal(advanceJourney(0.43, true, 0.016, true), 1);
assert.equal(advanceJourney(0.43, false, 0.016, true), 0);
assert.equal(advanceJourney(0, false, 0.016, true), 0);
assert.equal(advanceJourney(1, true, 0.016, true), 1);

// Forward vs return speed
let fwdFrames = 0;
let fwdP = 0;
while (fwdP < 1) {
  fwdP = advanceJourney(fwdP, true, 1 / 60);
  fwdFrames++;
}

let revFrames = 0;
let revP = 1;
while (revP > 0) {
  revP = advanceJourney(revP, false, 1 / 60);
  revFrames++;
}

assert.ok(revFrames < fwdFrames, `Return frames (${revFrames}) must be fewer than forward (${fwdFrames})`);
assert.ok(
  Math.abs(fwdFrames / revFrames - RETURN_SPEED) < 0.1,
  `Return speed ratio should match RETURN_SPEED (${RETURN_SPEED})`
);

// 2. phaseFor assertions and exact boundaries (contract v2 timeline)
assert.equal(phaseFor(0, true), 'idle');
assert.equal(phaseFor(0, false), 'idle');
assert.equal(phaseFor(1, true), 'floating');
assert.equal(phaseFor(1, false), 'floating');

assert.equal(phaseFor(0.15, true), 'pulling');
assert.equal(phaseFor(0.289, true), 'pulling');
assert.equal(phaseFor(0.29, true), 'wormhole');
assert.equal(phaseFor(0.50, true), 'wormhole');
assert.equal(phaseFor(0.699, true), 'wormhole');
assert.equal(phaseFor(0.70, true), 'emerging');
assert.equal(phaseFor(0.85, true), 'emerging');
assert.equal(phaseFor(0.999, true), 'emerging');

// Any intermediate value while reversing is returning
assert.equal(phaseFor(0.15, false), 'returning');
assert.equal(phaseFor(0.50, false), 'returning');
assert.equal(phaseFor(0.85, false), 'returning');

// 3. canPickItem only at progress === 1
assert.equal(canPickItem(1), true);
assert.equal(canPickItem(0.999), false);
assert.equal(canPickItem(0), false);
assert.equal(canPickItem(0.5), false);

// 4. floatingAnchor pure helper: distance constraints
const aspects = [0.45, 0.56, 0.75, 1.0, 1.6, 2.4];
for (const asp of aspects) {
  for (let count = 1; count <= 8; count++) {
    const anchors = [];
    for (let i = 0; i < count; i++) {
      anchors.push(floatingAnchor(i, count, 0, asp));
    }

    // Check minimum distance between distinct anchors (>= 0.8)
    for (let i = 0; i < count; i++) {
      for (let j = i + 1; j < count; j++) {
        const d = Math.hypot(
          anchors[i][0] - anchors[j][0],
          anchors[i][1] - anchors[j][1],
          anchors[i][2] - anchors[j][2]
        );
        assert.ok(
          d >= 0.8,
          `Distance between anchors ${i} and ${j} for count ${count} at aspect ${asp} is ${d.toFixed(3)}, must be >= 0.8`
        );
      }
    }

    // Check minimum distance to fridge centre axis x=0, z=-30 (>= 0.9)
    for (let i = 0; i < count; i++) {
      const [x, , z] = anchors[i];
      const distToAxis = Math.hypot(x, z - (-30.0));
      assert.ok(
        distToAxis >= 0.9,
        `Distance from anchor ${i} to fridge center axis at aspect ${asp} is ${distToAxis.toFixed(3)}, must be >= 0.9`
      );
    }
  }
}

// 5. Hand-written perspective projection for floating camera NDC validation
function projectPoint(point, camPos, camTarget, fovDegrees, aspect) {
  let fx = camTarget[0] - camPos[0];
  let fy = camTarget[1] - camPos[1];
  let fz = camTarget[2] - camPos[2];
  const fLen = Math.hypot(fx, fy, fz);
  fx /= fLen;
  fy /= fLen;
  fz /= fLen;

  let rx = -fz;
  let ry = 0;
  let rz = fx;
  const rLen = Math.hypot(rx, rz);
  rx /= rLen;
  rz /= rLen;

  const ux = ry * fz - rz * fy;
  const uy = rz * fx - rx * fz;
  const uz = rx * fy - ry * fx;

  const dx = point[0] - camPos[0];
  const dy = point[1] - camPos[1];
  const dz = point[2] - camPos[2];

  const vx = dx * rx + dy * ry + dz * rz;
  const vy = dx * ux + dy * uy + dz * uz;
  const vz = dx * fx + dy * fy + dz * fz;

  assert.ok(vz > 0, `Point must be in front of camera (vz = ${vz})`);

  const fovRad = (fovDegrees * Math.PI) / 180;
  const tanHalf = Math.tan(fovRad / 2);

  const ndcY = vy / (vz * tanHalf);
  const ndcX = vx / (vz * tanHalf * aspect);

  return { ndcX, ndcY, vz };
}

// Test projection across all mandatory aspect ratios
for (const asp of aspects) {
  const pose = sampleJourney(1.0, asp);
  const cam = pose.camera;

  // Floating camera must be >= 1.0 unit outside fridge AABB (at [0, 0, -30])
  const cdx = Math.max(0, FRIDGE_AABB.min[0] - cam.position[0], cam.position[0] - FRIDGE_AABB.max[0]);
  const cdy = Math.max(0, FRIDGE_AABB.min[1] - cam.position[1], cam.position[1] - FRIDGE_AABB.max[1]);
  const cdz = Math.max(0, (FRIDGE_AABB.min[2] - 30) - cam.position[2], cam.position[2] - (FRIDGE_AABB.max[2] - 30));
  const camDistToAABB = Math.hypot(cdx, cdy, cdz);
  assert.ok(
    camDistToAABB >= 1.0,
    `Floating camera distance to fridge AABB at aspect ${asp} is ${camDistToAABB.toFixed(3)}, must be >= 1.0`
  );

  // Correction 1: Assert max |NDC| of the anchor cloud is between 0.70 and 0.85
  let maxCloudNdc = 0;
  for (let count = 1; count <= 8; count++) {
    for (let i = 0; i < count; i++) {
      const pt = floatingAnchor(i, count, 0, asp);
      const ndc = projectPoint(pt, cam.position, cam.target, cam.fov, asp);
      const m = Math.max(Math.abs(ndc.ndcX), Math.abs(ndc.ndcY));
      if (m > maxCloudNdc) maxCloudNdc = m;

      assert.ok(
        Math.abs(ndc.ndcX) <= 0.85,
        `Anchor ${i}/${count} ndcX = ${ndc.ndcX.toFixed(3)} exceeds 0.85 at aspect ${asp}`
      );
      assert.ok(
        Math.abs(ndc.ndcY) <= 0.85,
        `Anchor ${i}/${count} ndcY = ${ndc.ndcY.toFixed(3)} exceeds 0.85 at aspect ${asp}`
      );
    }
  }

  assert.ok(
    maxCloudNdc >= 0.70 && maxCloudNdc <= 0.85,
    `Max anchor cloud |NDC| at aspect ${asp} is ${maxCloudNdc.toFixed(3)}, must be between 0.70 and 0.85`
  );

  // Assert all 8 corners of the floating fridge AABB project within NDC |x|, |y| <= 0.85
  for (const cx of [FRIDGE_AABB.min[0], FRIDGE_AABB.max[0]]) {
    for (const cy of [FRIDGE_AABB.min[1], FRIDGE_AABB.max[1]]) {
      for (const cz of [FRIDGE_AABB.min[2] - 30, FRIDGE_AABB.max[2] - 30]) {
        const ndc = projectPoint([cx, cy, cz], cam.position, cam.target, cam.fov, asp);
        assert.ok(
          Math.abs(ndc.ndcX) <= 0.85,
          `Fridge corner ndcX = ${ndc.ndcX.toFixed(3)} exceeds 0.85 at aspect ${asp}`
        );
        assert.ok(
          Math.abs(ndc.ndcY) <= 0.85,
          `Fridge corner ndcY = ${ndc.ndcY.toFixed(3)} exceeds 0.85 at aspect ${asp}`
        );
      }
    }
  }
}

// 6. Acceptance sampling check: step dp = 0.0025 across all aspects
function isFiniteDeep(val) {
  if (typeof val === 'number') return Number.isFinite(val);
  if (Array.isArray(val)) return val.every(isFiniteDeep);
  if (typeof val === 'object' && val !== null) {
    return Object.values(val).every(isFiniteDeep);
  }
  return false;
}

const portalPlaneZ = -3.2;
const dp = 0.0025;

for (const asp of aspects) {
  let prevSample = null;
  let prevCamSpeed = null;
  let prevFridgeSpeed = null;
  let prevFovStep = null;
  let prevCamPos = null;
  let prevFridgePos = null;

  for (let i = 0; i <= 400; i++) {
    const prog = i * dp;
    const s = sampleJourney(prog, asp);
    assert.ok(isFiniteDeep(s), `Sample at p=${prog.toFixed(4)}, asp=${asp} must be finite`);

    if (prevSample) {
      const camDist = Math.hypot(
        s.camera.position[0] - prevCamPos[0],
        s.camera.position[1] - prevCamPos[1],
        s.camera.position[2] - prevCamPos[2]
      );
      const camSpeed = camDist / dp;

      const fridgeDist = Math.hypot(
        s.fridge.position[0] - prevFridgePos[0],
        s.fridge.position[1] - prevFridgePos[1],
        s.fridge.position[2] - prevFridgePos[2]
      );
      const fridgeSpeed = fridgeDist / dp;

      // Acceptance: camera speed never changes by > 6 units/progress between consecutive samples in 0.02..0.98
      if (prog >= 0.02 + dp && prog <= 0.98) {
        const dCam = Math.abs(camSpeed - prevCamSpeed);
        assert.ok(
          dCam <= 6.001,
          `Camera speed change ${dCam.toFixed(3)} exceeds 6.0 at p=${prog.toFixed(4)}, asp=${asp}`
        );
      }

      // Acceptance: camera speed >= 6 everywhere in 0.06..0.70 (never stops)
      if (prog >= 0.06 && prog <= 0.70) {
        assert.ok(
          camSpeed >= 5.999,
          `Camera speed ${camSpeed.toFixed(2)} must be >= 6.0 at p=${prog.toFixed(4)}, asp=${asp}`
        );
      }

      // Acceptance: camera speed non-decreasing over 0.06..0.29 (accelerating dive)
      if (prog >= 0.06 + dp && prog <= 0.29) {
        assert.ok(
          camSpeed >= prevCamSpeed - 0.001,
          `Camera speed must be non-decreasing: ${camSpeed.toFixed(2)} < ${prevCamSpeed.toFixed(2)} at p=${prog.toFixed(4)}, asp=${asp}`
        );
      }

      // Correction 2: Tunnel speed >= 28 at p=0.70
      if (Math.abs(prog - 0.70) < 0.0001) {
        assert.ok(
          camSpeed >= 27.99,
          `Camera speed at p=0.70 is ${camSpeed.toFixed(2)}, must be >= 28 at asp=${asp}`
        );
      }

      // Acceptance: fridge speed changes by <= 6 between consecutive samples over 0.02..0.70
      if (prog >= 0.02 + dp && prog <= 0.70) {
        const dFridge = Math.abs(fridgeSpeed - prevFridgeSpeed);
        assert.ok(
          dFridge <= 6.001,
          `Fridge speed change ${dFridge.toFixed(3)} exceeds 6.0 at p=${prog.toFixed(4)}, asp=${asp}`
        );
      }

      // Acceptance: fov step <= 0.6 and |Δ(fov step)| <= 0.08 over 0.02..0.98
      const fovStep = Math.abs(s.camera.fov - prevSample.camera.fov);
      if (prog >= 0.02 && prog <= 0.98) {
        assert.ok(
          fovStep <= 0.601,
          `FOV step ${fovStep.toFixed(3)} exceeds 0.6 at p=${prog.toFixed(4)}, asp=${asp}`
        );
        if (prevFovStep !== null) {
          const dFovStep = Math.abs(fovStep - prevFovStep);
          assert.ok(
            dFovStep <= 0.0801,
            `FOV step change ${dFovStep.toFixed(4)} exceeds 0.08 at p=${prog.toFixed(4)}, asp=${asp}`
          );
        }
      }

      // Acceptance: camera look-direction changes <= 2.5 deg between consecutive samples
      const dirPrev = [
        prevSample.camera.target[0] - prevCamPos[0],
        prevSample.camera.target[1] - prevCamPos[1],
        prevSample.camera.target[2] - prevCamPos[2],
      ];
      const lenPrev = Math.hypot(...dirPrev);
      const dirCurr = [
        s.camera.target[0] - s.camera.position[0],
        s.camera.target[1] - s.camera.position[1],
        s.camera.target[2] - s.camera.position[2],
      ];
      const lenCurr = Math.hypot(...dirCurr);
      const dot = (dirPrev[0]*dirCurr[0] + dirPrev[1]*dirCurr[1] + dirPrev[2]*dirCurr[2]) / (lenPrev * lenCurr);
      const angleDeg = (Math.acos(Math.min(1, Math.max(-1, dot))) * 180) / Math.PI;
      if (prog >= 0.02 && prog <= 0.98) {
        assert.ok(
          angleDeg <= 2.501,
          `Camera look-direction angle change ${angleDeg.toFixed(2)} deg exceeds 2.5 deg at p=${prog.toFixed(4)}, asp=${asp}`
        );
      }

      prevCamSpeed = camSpeed;
      prevFridgeSpeed = fridgeSpeed;
      prevFovStep = fovStep;
    }

    // Tunnel timing: tunnel must be 0 whenever camera is on near side of portal plane (z > portalPlaneZ)
    if (s.camera.position[2] > portalPlaneZ) {
      assert.equal(
        s.tunnel,
        0,
        `Tunnel must be 0 when camera z (${s.camera.position[2].toFixed(3)}) is on near side of portal plane (${portalPlaneZ}) at p=${prog.toFixed(4)}`
      );
    }

    // Correction 5: camera is inside tunnel (tunnel > 0.5) when flash > 0.5, and tunnel must be 0 before charge starts (0.80)
    if (s.flash > 0.5) {
      assert.ok(
        s.tunnel >= 0.5,
        `Camera must be inside tunnel (tunnel >= 0.5, got ${s.tunnel.toFixed(3)}) when flash > 0.5 at p=${prog.toFixed(4)}`
      );
    }
    if (prog >= 0.80) {
      assert.equal(
        s.tunnel,
        0,
        `Tunnel must be 0 before charge starts (p >= 0.80), got ${s.tunnel} at p=${prog.toFixed(4)}`
      );
    }

    // Charge & burst assertions
    if (prog < 0.80) {
      assert.equal(s.charge, 0, `Charge must be 0 before p=0.80 at p=${prog.toFixed(4)}`);
    }
    if (prog >= 0.86) {
      assert.equal(s.charge, 1, `Charge must be 1 at or after p=0.86 at p=${prog.toFixed(4)}`);
    }
    if (prog < 0.86) {
      assert.equal(s.burst, 0, `Burst must be 0 before p=0.86 at p=${prog.toFixed(4)}`);
    }

    // Camera never enters fridge AABB when fridge is at home (p=0) or floating (p=1)
    if (prog === 0 || prog === 1) {
      const [fX, fY, fZ] = s.fridge.position;
      const cdx = Math.max(0, (FRIDGE_AABB.min[0] + fX) - s.camera.position[0], s.camera.position[0] - (FRIDGE_AABB.max[0] + fX));
      const cdy = Math.max(0, (FRIDGE_AABB.min[1] + fY) - s.camera.position[1], s.camera.position[1] - (FRIDGE_AABB.max[1] + fY));
      const cdz = Math.max(0, (FRIDGE_AABB.min[2] + fZ) - s.camera.position[2], s.camera.position[2] - (FRIDGE_AABB.max[2] + fZ));
      const dFridge = Math.hypot(cdx, cdy, cdz);
      assert.ok(
        dFridge > 0.5,
        `Camera must stay outside fridge AABB at p=${prog.toFixed(4)}, got distance ${dFridge.toFixed(3)}`
      );
    }

    prevSample = s;
    prevCamPos = s.camera.position;
    prevFridgePos = s.fridge.position;
  }
}

// 7. Correction 3: Portal crossing assertion
// At the progress where the fridge crosses the portal plane (z = -3.2), the fridge center lies within 0.6 * portal radius of portal center
let pFridgeCross = null;
let sampleFridgeCross = null;
let pCamCross = null;
let sampleCamCross = null;

for (let i = 0; i <= 2000; i++) {
  const prog = i / 2000;
  const s = sampleJourney(prog, 1.6);
  if (pFridgeCross === null && s.fridge.position[2] <= -3.2) {
    pFridgeCross = prog;
    sampleFridgeCross = s;
  }
  if (pCamCross === null && s.camera.position[2] <= -3.2) {
    pCamCross = prog;
    sampleCamCross = s;
  }
}

assert.ok(pFridgeCross !== null, 'Fridge must reach portal plane z <= -3.2');
assert.ok(pCamCross !== null, 'Camera must reach portal plane z <= -3.2');
assert.ok(
  pFridgeCross < pCamCross,
  `Fridge must cross portal plane before camera (fridge: ${pFridgeCross.toFixed(4)}, camera: ${pCamCross.toFixed(4)})`
);

const portalCenter = sampleFridgeCross.portal.position;
const portalR = sampleFridgeCross.portal.radius;
const fridgeCenterAtCross = [
  sampleFridgeCross.fridge.position[0],
  sampleFridgeCross.fridge.position[1] + 0.925 * sampleFridgeCross.fridge.scale[1],
  sampleFridgeCross.fridge.position[2],
];

const distFridgeToPortalCenter = Math.hypot(
  fridgeCenterAtCross[0] - portalCenter[0],
  fridgeCenterAtCross[1] - portalCenter[1],
  fridgeCenterAtCross[2] - portalCenter[2]
);
assert.ok(
  distFridgeToPortalCenter <= 0.6 * portalR,
  `Fridge center distance to portal center at crossing is ${distFridgeToPortalCenter.toFixed(3)}, must be <= ${(0.6 * portalR).toFixed(3)}`
);

// Camera at 0.29 is within 0.6 * portal radius of portal center (in fact at the center)
const distCamToPortalCenter = Math.hypot(
  sampleCamCross.camera.position[0] - portalCenter[0],
  sampleCamCross.camera.position[1] - portalCenter[1],
  sampleCamCross.camera.position[2] - portalCenter[2]
);
assert.ok(
  distCamToPortalCenter <= 0.6 * portalR,
  `Camera distance to portal center at crossing is ${distCamToPortalCenter.toFixed(3)}, must be <= ${(0.6 * portalR).toFixed(3)}`
);

// 8. GLB asset assertions
const file = readFileSync(new URL('../../src/assets/mini-fridge.glb', import.meta.url));
assert.equal(file.toString('ascii', 0, 4), 'glTF');
const gltf = JSON.parse(file.toString('utf8', 20, 20 + file.readUInt32LE(12)));
assert.ok(gltf.nodes.find(n => n.name === 'DoorPivot')?.children.length > 0);
for (let i = 0; i < 6; i++) {
  const food = gltf.nodes.find(n => n.name === `Food_${i}`);
  assert.equal(food?.extras.itemIndex, i);
  assert.ok(food.children.length >= 3);
}
assert.equal(gltf.buffers.length, 1);
assert.ok(!gltf.buffers[0].uri, 'Model is self-contained');

// 9. Compact speed table for 0.14–0.37 (like speed-before.txt)
console.log('p      camSpeed fridgeSpeed fov tunnel portalI');
for (let i = Math.round(0.14 / dp); i <= Math.round(0.37 / dp); i++) {
  const prog = i * dp;
  const sPrev = sampleJourney(prog - dp, 1.6);
  const sCurr = sampleJourney(prog, 1.6);
  const cSpeed = Math.hypot(
    sCurr.camera.position[0] - sPrev.camera.position[0],
    sCurr.camera.position[1] - sPrev.camera.position[1],
    sCurr.camera.position[2] - sPrev.camera.position[2]
  ) / dp;
  const fSpeed = Math.hypot(
    sCurr.fridge.position[0] - sPrev.fridge.position[0],
    sCurr.fridge.position[1] - sPrev.fridge.position[1],
    sCurr.fridge.position[2] - sPrev.fridge.position[2]
  ) / dp;
  console.log(
    `${prog.toFixed(4)}  ${cSpeed.toFixed(1).padStart(4, ' ')}  ${fSpeed.toFixed(1).padStart(4, ' ')}  ${sCurr.camera.fov.toFixed(1).padStart(4, ' ')}  ${sCurr.tunnel.toFixed(2)}  ${sCurr.portal.intensity.toFixed(2)}`
  );
}

console.log('PASS: space-journey checks passed (advance, phase, projection, tunnel timing, charge/burst, portal crossing, GLB).');
