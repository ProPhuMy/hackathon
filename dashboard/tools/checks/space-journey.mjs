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
assert.equal(JOURNEY_SECONDS, 9);
assert.equal(RETURN_SPEED, 2);

// 1. advanceJourney assertions
// Exit works from any entry phase, and repeating entry never overshoots.
for (const start of [0.1, 0.35, 0.7, 1]) {
  let p = start;
  for (let i = 0; i < 300; i++) p = advanceJourney(p, false, 1 / 60);
  assert.equal(p, 0);
}

let p = 0;
for (let i = 0; i < 600; i++) p = advanceJourney(p, true, 1 / 60);
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

// 2. phaseFor assertions and exact boundaries
assert.equal(phaseFor(0, true), 'idle');
assert.equal(phaseFor(0, false), 'idle');
assert.equal(phaseFor(1, true), 'floating');
assert.equal(phaseFor(1, false), 'floating');

assert.equal(phaseFor(0.15, true), 'pulling');
assert.equal(phaseFor(0.299, true), 'pulling');
assert.equal(phaseFor(0.30, true), 'wormhole');
assert.equal(phaseFor(0.50, true), 'wormhole');
assert.equal(phaseFor(0.719, true), 'wormhole');
assert.equal(phaseFor(0.72, true), 'emerging');
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
for (let count = 1; count <= 8; count++) {
  const anchors = [];
  for (let i = 0; i < count; i++) {
    anchors.push(floatingAnchor(i, count, 0));
  }

  // Check minimum distance between distinct anchors
  for (let i = 0; i < count; i++) {
    for (let j = i + 1; j < count; j++) {
      const d = Math.hypot(
        anchors[i][0] - anchors[j][0],
        anchors[i][1] - anchors[j][1],
        anchors[i][2] - anchors[j][2]
      );
      assert.ok(
        d >= 0.55,
        `Distance between anchors ${i} and ${j} for count ${count} is ${d.toFixed(3)}, must be >= 0.55`
      );
    }
  }

  // Check minimum distance to fridge AABB at floating position [0, 0, -30]
  // Fridge AABB: X [-0.56, 0.56], Y [0.00, 1.85], Z [-30.43, -29.33]
  for (let i = 0; i < count; i++) {
    const [x, y, z] = anchors[i];
    const dx = Math.max(0, FRIDGE_AABB.min[0] - x, x - FRIDGE_AABB.max[0]);
    const dy = Math.max(0, FRIDGE_AABB.min[1] - y, y - FRIDGE_AABB.max[1]);
    const dz = Math.max(0, (FRIDGE_AABB.min[2] - 30) - z, z - (FRIDGE_AABB.max[2] - 30));
    const distToAABB = Math.hypot(dx, dy, dz);
    assert.ok(
      distToAABB >= 0.35,
      `Distance from anchor ${i} to fridge AABB is ${distToAABB.toFixed(3)}, must be >= 0.35`
    );
  }
}

// 5. Hand-written perspective projection for floating camera NDC validation
function projectPoint(point, camPos, camTarget, fovDegrees, aspect) {
  // forward vector
  let fx = camTarget[0] - camPos[0];
  let fy = camTarget[1] - camPos[1];
  let fz = camTarget[2] - camPos[2];
  const fLen = Math.hypot(fx, fy, fz);
  fx /= fLen;
  fy /= fLen;
  fz /= fLen;

  // right vector = normalize(cross(forward, [0, 1, 0]))
  let rx = -fz;
  let ry = 0;
  let rz = fx;
  const rLen = Math.hypot(rx, rz);
  rx /= rLen;
  rz /= rLen;

  // up vector = cross(right, forward)
  const ux = ry * fz - rz * fy;
  const uy = rz * fx - rx * fz;
  const uz = rx * fy - ry * fx;

  // point relative to camera
  const dx = point[0] - camPos[0];
  const dy = point[1] - camPos[1];
  const dz = point[2] - camPos[2];

  // Camera space coordinates
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
const aspects = [0.45, 0.56, 0.75, 1.0, 1.6, 2.4];
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

  // Assert all anchors for counts 1..8 fall inside NDC |x|, |y| <= 0.9
  for (let count = 1; count <= 8; count++) {
    for (let i = 0; i < count; i++) {
      const pt = floatingAnchor(i, count, 0);
      const ndc = projectPoint(pt, cam.position, cam.target, cam.fov, asp);
      assert.ok(
        Math.abs(ndc.ndcX) <= 0.9,
        `Anchor ${i}/${count} ndcX = ${ndc.ndcX.toFixed(3)} exceeds 0.9 at aspect ${asp}`
      );
      assert.ok(
        Math.abs(ndc.ndcY) <= 0.9,
        `Anchor ${i}/${count} ndcY = ${ndc.ndcY.toFixed(3)} exceeds 0.9 at aspect ${asp}`
      );
    }
  }

  // Assert all 8 corners of the floating fridge AABB also project within NDC |x|, |y| <= 0.9
  for (const cx of [FRIDGE_AABB.min[0], FRIDGE_AABB.max[0]]) {
    for (const cy of [FRIDGE_AABB.min[1], FRIDGE_AABB.max[1]]) {
      for (const cz of [FRIDGE_AABB.min[2] - 30, FRIDGE_AABB.max[2] - 30]) {
        const ndc = projectPoint([cx, cy, cz], cam.position, cam.target, cam.fov, asp);
        assert.ok(
          Math.abs(ndc.ndcX) <= 0.9,
          `Fridge corner ndcX = ${ndc.ndcX.toFixed(3)} exceeds 0.9 at aspect ${asp}`
        );
        assert.ok(
          Math.abs(ndc.ndcY) <= 0.9,
          `Fridge corner ndcY = ${ndc.ndcY.toFixed(3)} exceeds 0.9 at aspect ${asp}`
        );
      }
    }
  }
}

// 6. 1001-sample check across aspect ratios: continuity, finite values, timing
function isFiniteDeep(val) {
  if (typeof val === 'number') return Number.isFinite(val);
  if (Array.isArray(val)) return val.every(isFiniteDeep);
  if (typeof val === 'object' && val !== null) {
    return Object.values(val).every(isFiniteDeep);
  }
  return false;
}

const portalPlaneZ = -3.2;

for (const asp of aspects) {
  let prevSample = sampleJourney(0, asp);
  assert.ok(isFiniteDeep(prevSample), `Sample at p=0, asp=${asp} must have all finite numbers`);

  for (let i = 0; i <= 1000; i++) {
    const prog = i / 1000;
    const s = sampleJourney(prog, asp);
    assert.ok(isFiniteDeep(s), `Sample at p=${prog}, asp=${asp} must be finite`);

    // Camera continuity: no excessive jump between consecutive samples (step=0.001)
    const camJump = Math.hypot(
      s.camera.position[0] - prevSample.camera.position[0],
      s.camera.position[1] - prevSample.camera.position[1],
      s.camera.position[2] - prevSample.camera.position[2]
    );
    assert.ok(
      camJump < 0.15,
      `Camera jump ${camJump.toFixed(4)} at p=${prog}, asp=${asp} exceeds 0.15`
    );

    // Tunnel timing: tunnel must be 0 whenever camera is on near side of portal plane (z > portalPlaneZ)
    if (s.camera.position[2] > portalPlaneZ) {
      assert.equal(
        s.tunnel,
        0,
        `Tunnel must be 0 when camera z (${s.camera.position[2].toFixed(3)}) is on near side of portal plane (${portalPlaneZ}) at p=${prog}`
      );
    }

    // Tunnel tumble window [0.31, 0.70]: fridge distance ahead of camera within [2.4, 3.6]
    if (prog >= 0.31 && prog <= 0.70) {
      const dCamFridge = Math.hypot(
        s.fridge.position[0] - s.camera.position[0],
        s.fridge.position[1] - s.camera.position[1],
        s.fridge.position[2] - s.camera.position[2]
      );
      assert.ok(
        dCamFridge >= 2.4 && dCamFridge <= 3.6,
        `Distance between camera and fridge in tunnel (${dCamFridge.toFixed(3)}) must be in [2.4, 3.6] at p=${prog}`
      );
    }

    // Door timing: door stays closed (|door| < 0.05) before 0.80 and fully open (-2.05) by 0.88
    if (prog < 0.80) {
      assert.ok(
        Math.abs(s.door) < 0.05,
        `Door must stay closed (|door| < 0.05) before p=0.80, got ${s.door} at p=${prog}`
      );
    }
    if (prog >= 0.88) {
      assert.ok(
        Math.abs(s.door - (-2.05)) < 0.01,
        `Door must be fully open (-2.05) by p=0.88, got ${s.door} at p=${prog}`
      );
    }

    // Release timing: release === 0 before 0.86
    if (prog < 0.86) {
      assert.equal(
        s.release,
        0,
        `Release must be 0 before p=0.86, got ${s.release} at p=${prog}`
      );
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
        `Camera must stay outside fridge AABB at p=${prog}, got distance ${dFridge.toFixed(3)}`
      );
    }

    prevSample = s;
  }
}

// 7. GLB asset assertions carried over from fridge-motion.mjs
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

console.log('PASS: space-journey checks passed (advance, phase, projection, tunnel timing, door, release, GLB).');
