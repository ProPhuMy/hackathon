import { Component, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Billboard, Environment, Html, Lightformer, useGLTF, useTexture } from '@react-three/drei';
import { Euler, MathUtils, Matrix4, Plane, Raycaster, SRGBColorSpace, Vector2, Vector3 } from 'three';
import fridgeGlbUrl from './assets/mini-fridge.glb?url';
import {
  advanceJourney,
  canPickItem,
  floatingAnchor,
  phaseFor,
  sampleJourney,
} from './spaceJourney.mjs';
import { SLOT_TO_DEMO_ID } from './itemMapping.js';
import Explosion from './space/Explosion.jsx';
import Starfield from './space/Starfield.jsx';
import Wormhole from './space/Wormhole.jsx';
import SpaceEffects from './space/SpaceEffects.jsx';

// Inverted mapping: demo item id -> GLB Food slot index (0..5)
const DEMO_ID_TO_SLOT = Object.fromEntries(
  Object.entries(SLOT_TO_DEMO_ID).map(([slot, id]) => [id, Number(slot)])
);

// Fallback slot local positions (inside fridge) if node not found
const SLOT_LOCAL_POS = {
  0: [-0.225, 1.34, 0.02],
  1: [0.205, 1.34, 0.025],
  2: [-0.23, 0.93, 0.03],
  3: [0.22, 0.93, 0.025],
  4: [-0.22, 0.52, 0.035],
  5: [0.22, 0.52, 0.015],
};

// Module-level preallocated temporaries (zero per-frame allocations)
const _vOrigin = new Vector3();
const _vTarget = new Vector3();
const _vPos = new Vector3();
const _euler = new Euler();
const _mat4 = new Matrix4();
const _camPos = new Vector3();
const _camTarget = new Vector3();
const _hit = new Vector3();
const _camDir = new Vector3();
const _ndc = new Vector2();
const _dragRay = new Raycaster();
const DRAG_THRESHOLD_PX = 6;
const MAX_DRAG = 6;

// Deterministic simple hash for item ids
function hashId(id) {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  return h;
}

const PLACEHOLDER_IMAGE = '/images/placeholder-item.svg';
const srgb = (texture) => { texture.colorSpace = SRGBColorSpace; };

// Items without a modelled food (e.g. added in Inventory) float as a camera-facing placeholder card.
function PlaceholderCard({ highlighted }) {
  const map = useTexture(PLACEHOLDER_IMAGE, srgb);
  return (
    <Billboard>
      <mesh>
        <planeGeometry args={[0.36, 0.36]} />
        <meshBasicMaterial map={map} transparent toneMapped={false} color={highlighted ? '#ffffff' : '#c9cee6'} />
      </mesh>
    </Billboard>
  );
}

// Dev-only screenshot hook (?progress=<0..1>)
function getDevProgress() {
  if (import.meta.env.DEV && typeof window !== 'undefined') {
    const pStr = new URLSearchParams(window.location.search).get('progress');
    if (pStr !== null) {
      const val = parseFloat(pStr);
      if (Number.isFinite(val)) return Math.min(1, Math.max(0, val));
    }
  }
  return null;
}

function FridgeWorld({
  travel,
  items = [],
  selectedId,
  onTravel,
  onInspect,
  onPhase,
  onReady,
  onHoverChange,
  hoveredId,
}) {
  const { scene } = useGLTF(fridgeGlbUrl);
  const model = useMemo(() => scene.clone(true), [scene]);

  const devFrozenProgress = useMemo(() => getDevProgress(), []);

  // Rig ref updated at top of useFrame before any child reads it
  const rig = useRef({
    progress: devFrozenProgress !== null ? devFrozenProgress : 0,
    sample: sampleJourney(devFrozenProgress !== null ? devFrozenProgress : 0),
    time: 0,
    reduced: false,
  });

  const fridgeGroupRef = useRef(null);
  const lampRef = useRef(null);
  const parts = useRef({
    door: null,
    foodNodes: new Map(), // slot -> original food node in fridge model
  });
  const cabinetMeshesRef = useRef([]);
  const lastCabinetVisibleRef = useRef(true);
  const phaseRef = useRef('idle');
  const pickRef = useRef(false);
  const [canPick, setCanPick] = useState(false);

  // Item groups refs (one world-space group per item)
  const itemGroupRefs = useRef(new Map());
  // Drag: per-item world offsets on top of the floating pose, plus the active gesture.
  const dragOffsets = useRef(new Map());
  const basePositions = useRef(new Map());
  const drag = useRef({ id: null, plane: new Plane(), grab: new Vector3(), x: 0, y: 0, moved: false });
  const getThree = useThree((state) => state.get);

  // Press an item to drag it on a camera-facing plane; a press without movement is a click.
  // Window listeners keep the drag alive even when the cursor leaves the item.
  function startDrag(e, id) {
    if (!pickRef.current) return;
    e.stopPropagation();
    const grp = itemGroupRefs.current.get(id);
    const d = drag.current;
    e.camera.getWorldDirection(_camDir);
    d.plane.setFromNormalAndCoplanarPoint(_camDir, grp.position);
    if (!e.ray.intersectPlane(d.plane, _hit)) return;
    d.grab.copy(_hit).sub(grp.position);
    Object.assign(d, { id, x: e.clientX, y: e.clientY, moved: false });
    const canvas = getThree().gl.domElement;
    const move = (ev) => {
      if (!d.moved && Math.hypot(ev.clientX - d.x, ev.clientY - d.y) < DRAG_THRESHOLD_PX) return;
      d.moved = true;
      canvas.style.cursor = 'grabbing';
      const base = basePositions.current.get(id);
      const rect = canvas.getBoundingClientRect();
      _ndc.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
      _dragRay.setFromCamera(_ndc, getThree().camera);
      if (!base || !_dragRay.ray.intersectPlane(d.plane, _hit)) return;
      const offset = dragOffsets.current.get(id) ?? new Vector3();
      offset.copy(_hit).sub(d.grab).sub(base).clampLength(0, MAX_DRAG);
      dragOffsets.current.set(id, offset);
    };
    const end = (ev) => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
      canvas.style.cursor = '';
      d.id = null;
      if (ev.type === 'pointerup' && !d.moved && pickRef.current) onInspect(id);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
  }

  // Listen for prefers-reduced-motion
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => {
      rig.current.reduced = media.matches;
    };
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  // Set up model parts, materials, cached cabinet meshes, and hide unmapped foods
  useEffect(() => {
    parts.current.door = model.getObjectByName('DoorPivot');

    // Cache cabinet + door meshes (every node not under Food_*), for detonation swap at burst=0.02
    const cabinetMeshes = [];
    model.traverse((child) => {
      if (child.isMesh) {
        let isFood = false;
        let p = child;
        while (p) {
          if (p.name && p.name.startsWith('Food_')) {
            isFood = true;
            break;
          }
          p = p.parent;
        }
        if (!isFood) {
          cabinetMeshes.push(child);
        }
      }
    });
    cabinetMeshesRef.current = cabinetMeshes;
    lastCabinetVisibleRef.current = true;

    const validSlots = new Set(
      items
        .map((it) => DEMO_ID_TO_SLOT[it.id])
        .filter((slot) => slot !== undefined)
    );

    for (let slot = 0; slot < 6; slot++) {
      const foodNode = model.getObjectByName(`Food_${slot}`);
      if (foodNode) {
        parts.current.foodNodes.set(slot, foodNode);
        // Slots whose demo ID is not in items stay hidden from the start
        if (!validSlots.has(slot)) {
          foodNode.visible = false;
        }
      }
    }

    onReady();
  }, [model, items, onReady]);

  // Memoize cloned food visuals for each item in props.items
  const itemVisuals = useMemo(() => {
    return items.map((item, index) => {
      const slot = DEMO_ID_TO_SLOT[item.id];
      const origNode = slot !== undefined ? model.getObjectByName(`Food_${slot}`) : null;
      let mesh = null;
      if (origNode) {
        mesh = origNode.clone(true);
        // Reset local position since the item group will be positioned in world space
        mesh.position.set(0, 0, 0);
      }
      return { item, index, slot, mesh, seed: hashId(item.id) };
    });
  }, [items, model]);

  // Single useFrame: updates rig FIRST, then animates camera, fridge, door, items
  useFrame(({ camera, size, clock }, delta) => {
    const r = rig.current;
    r.time = clock.elapsedTime;

    // Advance journey progress (or keep frozen in dev mode)
    if (devFrozenProgress !== null) {
      r.progress = devFrozenProgress;
    } else {
      r.progress = advanceJourney(r.progress, travel, delta, r.reduced);
    }

    const aspect = size.width / size.height;
    r.sample = sampleJourney(r.progress, aspect);
    const sample = r.sample;

    // Phase change callback (only when phase changes)
    const currentPhase = phaseFor(r.progress, travel);
    if (currentPhase !== phaseRef.current) {
      phaseRef.current = currentPhase;
      onPhase(currentPhase);
    }

    // Pickable state update (only on boundary change)
    const isPickable = canPickItem(r.progress);
    if (isPickable !== pickRef.current) {
      pickRef.current = isPickable;
      setCanPick(isPickable);
    }

    // 1. Camera transform
    _camPos.set(...sample.camera.position);
    _camTarget.set(...sample.camera.target);
    camera.position.copy(_camPos);
    camera.lookAt(_camTarget);
    if (Math.abs(camera.fov - sample.camera.fov) > 0.001) {
      camera.fov = sample.camera.fov;
      camera.updateProjectionMatrix();
    }

    // Detonation swap: Cabinet + DoorPivot meshes visible iff burst < 0.02
    const cabinetVisible = sample.burst < 0.02;
    if (cabinetVisible !== lastCabinetVisibleRef.current) {
      lastCabinetVisibleRef.current = cabinetVisible;
      for (let i = 0; i < cabinetMeshesRef.current.length; i++) {
        cabinetMeshesRef.current[i].visible = cabinetVisible;
      }
    }

    // 2. Fridge transform & idle/floating bob & charge tremble/swell
    const fg = fridgeGroupRef.current;
    if (fg) {
      _vPos.set(...sample.fridge.position);
      _euler.set(...sample.fridge.rotation);

      if (!r.reduced) {
        if (r.progress === 0) {
          _vPos.y += Math.sin(r.time * 0.8) * 0.04;
          _euler.y += Math.sin(r.time * 0.5) * 0.07;
        } else if (r.progress === 1) {
          _vPos.y += Math.sin(r.time * 0.6) * 0.02;
          _euler.y += Math.sin(r.time * 0.4) * 0.10;
        }

        // Charge tremble (amplitude 0.035*charge pos, 0.04*charge rad rot)
        if (sample.charge > 0) {
          const c = sample.charge;
          _vPos.x += (Math.sin(r.time * 53.0) + Math.sin(r.time * 79.0) * 0.5) / 1.5 * 0.035 * c;
          _vPos.y += (Math.sin(r.time * 61.0) + Math.sin(r.time * 83.0) * 0.5) / 1.5 * 0.035 * c;
          _vPos.z += (Math.sin(r.time * 67.0) + Math.sin(r.time * 71.0) * 0.5) / 1.5 * 0.035 * c;

          _euler.x += (Math.sin(r.time * 47.0) + Math.sin(r.time * 67.0) * 0.5) / 1.5 * 0.04 * c;
          _euler.y += (Math.sin(r.time * 59.0) + Math.sin(r.time * 73.0) * 0.5) / 1.5 * 0.04 * c;
          _euler.z += (Math.sin(r.time * 43.0) + Math.sin(r.time * 89.0) * 0.5) / 1.5 * 0.04 * c;
        }
      }

      fg.position.copy(_vPos);
      fg.rotation.copy(_euler);

      // Swell scale 1 + 0.05*charge (off when reduced)
      const swell = !r.reduced && sample.charge > 0 ? 1 + 0.05 * sample.charge : 1.0;
      fg.scale.set(
        sample.fridge.scale[0] * swell,
        sample.fridge.scale[1] * swell,
        sample.fridge.scale[2] * swell
      );
      fg.updateMatrixWorld();
    }

    // 3. Ember seam light (replaces interior light)
    if (lampRef.current) {
      lampRef.current.intensity = sample.light * 4;
    }

    // 4. Items trajectory, visibility and floating motion
    const numItems = itemVisuals.length;
    itemVisuals.forEach(({ item, index, slot, seed }) => {
      const grp = itemGroupRefs.current.get(item.id);
      if (!grp || !fg) return;

      // Tiny stagger <= 0.05 of burst
      const itemStagger = numItems > 1 ? (index / (numItems - 1)) * 0.05 : 0;
      const burstPrime =
        sample.burst <= itemStagger
          ? 0
          : Math.min(1, (sample.burst - itemStagger) / (1 - itemStagger));

      // Manage original food visibility inside fridge
      const origNode = slot !== undefined ? parts.current.foodNodes.get(slot) : null;
      if (origNode) {
        origNode.visible = sample.burst < 0.02 && burstPrime === 0;
      }

      if (sample.burst === 0) {
        grp.visible = false;
        dragOffsets.current.delete(item.id); // back in the fridge: next trip starts fresh
        return;
      }
      grp.visible = true;

      // Launch origin: slot position in world space
      const localSlot =
        slot !== undefined && SLOT_LOCAL_POS[slot]
          ? SLOT_LOCAL_POS[slot]
          : [0, 1.0, 0.45];
      _vOrigin.set(...localSlot).applyMatrix4(fg.matrixWorld);

      // Target anchor in world space (aspect-aware ellipsoid shell)
      const anchor = floatingAnchor(index, numItems, seed, aspect);
      _vTarget.set(...anchor);

      // Interpolate with easeOutExpo-ish trajectory
      const easedBurst = r.reduced
        ? (sample.burst > 0 ? 1 : 0)
        : (burstPrime === 1 ? 1 : 1 - Math.pow(2, -10 * burstPrime));

      _vPos.lerpVectors(_vOrigin, _vTarget, easedBurst);

      // Tumble rotation proportional to eased burst (1.5–3 turns, per-item axis from seed)
      const turns = 1.5 + (seed % 10) * 0.15;
      const tumbleAngle = easedBurst * turns * Math.PI * 2;
      const ax = Math.sin(seed * 1.1);
      const ay = Math.cos(seed * 2.3);
      const az = Math.sin(seed * 3.7);
      const aLen = Math.hypot(ax, ay, az) || 1;

      if (!r.reduced) {
        grp.rotation.set(
          (ax / aLen) * tumbleAngle,
          (ay / aLen) * tumbleAngle,
          (az / aLen) * tumbleAngle
        );
      } else {
        grp.rotation.set(0, 0, 0);
      }

      // Floating drift faded in by smoothstep(0.9, 1, burst)
      const driftFactor = Math.min(1, Math.max(0, (sample.burst - 0.9) / 0.1));
      const driftSmooth = driftFactor * driftFactor * (3 - 2 * driftFactor);
      if (driftSmooth > 0 && !r.reduced) {
        _vPos.x += Math.sin(r.time * 0.5 + index * 1.3) * 0.04 * driftSmooth;
        _vPos.y += Math.sin(r.time * 0.7 + index * 1.1) * 0.05 * driftSmooth;
        _vPos.z += Math.cos(r.time * 0.6 + index * 1.5) * 0.04 * driftSmooth;
        grp.rotation.x += Math.sin(r.time * 0.4 + index) * 0.15 * driftSmooth;
        grp.rotation.y += (r.time * 0.15 + index * 0.7) * driftSmooth;
        grp.rotation.z += Math.cos(r.time * 0.35 + index) * 0.15 * driftSmooth;
      }

      // Dragged items keep their offset while floating; it fades out as they fly home.
      const base = basePositions.current.get(item.id);
      if (base) base.copy(_vPos);
      else basePositions.current.set(item.id, _vPos.clone());
      const offset = dragOffsets.current.get(item.id);
      if (offset) _vPos.addScaledVector(offset, driftSmooth);
      grp.position.copy(_vPos);

      // Hover / Selection scale animation (1.08 on hover)
      const isHighlighted = hoveredId === item.id || selectedId === item.id;
      const targetScale = isHighlighted ? 1.08 : 1.0;
      const currentScale = grp.scale.x;
      const newScale = r.reduced
        ? targetScale
        : MathUtils.damp(currentScale, targetScale, 10, Math.min(delta, 0.05));
      grp.scale.setScalar(newScale);
    });
  });

  return (
    <>
      {/* Fridge model group */}
      <group ref={fridgeGroupRef}>
        <primitive
          object={model}
          onClick={(e) => {
            if (rig.current.progress === 0 && !travel) {
              e.stopPropagation();
              onTravel();
            }
          }}
          onPointerOver={(e) => {
            if (rig.current.progress === 0 && !travel) {
              e.stopPropagation();
              onHoverChange('__fridge__');
            }
          }}
          onPointerOut={() => {
            onHoverChange(null);
          }}
        />
        {/* Explosion component (owned by FX, mounted right after primitive) */}
        <Explosion rig={rig} model={model} />
        {/* Ember seam point light */}
        <pointLight
          ref={lampRef}
          position={[0, 1.0, 0]}
          intensity={0}
          distance={3}
          decay={2}
          color="#ff8a4c"
        />
      </group>

      {/* World-space ejected items */}
      {itemVisuals.map(({ item, mesh }) => {
        const isHovered = hoveredId === item.id;
        const isSelected = selectedId === item.id;

        return (
          <group
            key={item.id}
            ref={(node) => {
              if (node) itemGroupRefs.current.set(item.id, node);
              else itemGroupRefs.current.delete(item.id);
            }}
            visible={false}
            onPointerDown={(e) => startDrag(e, item.id)}
            onPointerOver={(e) => {
              e.stopPropagation();
              if (pickRef.current) {
                onHoverChange(item.id);
              }
            }}
            onPointerOut={() => {
              onHoverChange(null);
            }}
          >
            {mesh ? <primitive object={mesh} /> : <PlaceholderCard highlighted={isHovered || isSelected} />}

            {/* Floating name tag when hovered or selected */}
            {(isHovered || isSelected) && canPick && (
              <Html
                position={[0, 0.35, 0]}
                center
                style={{ pointerEvents: 'none', userSelect: 'none' }}
              >
                <div
                  style={{
                    background: 'rgba(10, 14, 39, 0.90)',
                    border: '1px solid rgba(63, 214, 255, 0.45)',
                    backdropFilter: 'blur(8px)',
                    padding: '5px 9px',
                    borderRadius: '4px',
                    color: '#eef1ff',
                    fontFamily: 'monospace',
                    fontSize: '11px',
                    lineHeight: '1.25',
                    whiteSpace: 'nowrap',
                    boxShadow: '0 4px 16px rgba(0, 0, 0, 0.5)',
                    textAlign: 'center',
                  }}
                >
                  <div style={{ fontWeight: 'bold' }}>{item.name}</div>
                  <div style={{ fontSize: '9px', color: '#8d95bd' }}>{item.owner}’s</div>
                </div>
              </Html>
            )}
          </group>
        );
      })}

      {/* Image-based lighting and space lights */}
      <ambientLight intensity={0.6} color="#5a6290" />
      <directionalLight position={[3, 4, 4]} intensity={2.4} color="#f4f6ff" />
      <directionalLight position={[-4, 2, -2]} intensity={1.5} color="#3fd6ff" />
      <Environment resolution={128}>
        <Lightformer
          intensity={4}
          position={[-3, 2, -2]}
          scale={[3, 6, 1]}
          color="#3fd6ff"
        />
        <Lightformer
          intensity={3.5}
          position={[3, 3, 2]}
          scale={[2, 5, 1]}
          color="#ddc89a"
        />
        <Lightformer
          intensity={1.2}
          position={[0, 5, -2]}
          rotation={[Math.PI / 2, 0, 0]}
          scale={5}
          color="#6a2fd1"
        />
      </Environment>

      {/* FX worker components mounted inside Canvas, SpaceEffects last */}
      <Starfield rig={rig} />
      <Wormhole rig={rig} />
      <SpaceEffects rig={rig} />
    </>
  );
}

class ModelBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onFailure();
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export default function Fridge3D({
  travel = false,
  items = [],
  selectedId = null,
  onTravel = () => {},
  onInspect = () => {},
  onPhase = () => {},
  onReady = () => {},
  onFailure = () => {},
}) {
  const [hoveredId, setHoveredId] = useState(null);

  const fallback = (
    <img
      className="model-fallback"
      src="/images/fridge-front.png"
      alt="Silver mini fridge. The interactive model is unavailable; inventory is available from the navigation."
    />
  );

  const isClickable = hoveredId !== null || (!travel && hoveredId === '__fridge__');

  return (
    <div className={`model-view ${isClickable ? 'model-clickable' : ''}`}>
      <ModelBoundary fallback={fallback} onFailure={onFailure}>
        <Canvas
          dpr={[1, 1.5]}
          camera={{
            position: [2.7, 1.6, 4.8],
            near: 0.008,
            far: 200,
            fov: 34,
          }}
          fallback={<span aria-hidden="true">3D rendering is unavailable.</span>}
          gl={{ antialias: true, alpha: true }}
        >
          <Suspense fallback={null}>
            <FridgeWorld
              travel={travel}
              items={items}
              selectedId={selectedId}
              onTravel={onTravel}
              onInspect={onInspect}
              onPhase={onPhase}
              onReady={onReady}
              onHoverChange={setHoveredId}
              hoveredId={hoveredId}
            />
          </Suspense>
        </Canvas>
      </ModelBoundary>
    </div>
  );
}
