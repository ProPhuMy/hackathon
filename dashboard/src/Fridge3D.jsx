import { Component, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Environment, Html, Lightformer, useGLTF } from '@react-three/drei';
import { Color, Euler, MathUtils, Matrix4, Vector3 } from 'three';
import fridgeGlbUrl from './assets/mini-fridge.glb?url';
import {
  advanceJourney,
  canPickItem,
  floatingAnchor,
  phaseFor,
  sampleJourney,
} from './spaceJourney.mjs';
import { SLOT_TO_DEMO_ID } from './itemMapping.js';
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
const _glowColor = new Color('#3fd6ff');

// Deterministic simple hash for item ids
function hashId(id) {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  return h;
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
  const phaseRef = useRef('idle');
  const pickRef = useRef(false);
  const [canPick, setCanPick] = useState(false);

  // Item groups refs (one world-space group per item)
  const itemGroupRefs = useRef(new Map());

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

  // Set up model parts, materials, and hide unmapped foods
  useEffect(() => {
    parts.current.door = model.getObjectByName('DoorPivot');

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

    // 2. Fridge transform & idle/floating bob (applied on the fridge group)
    const fg = fridgeGroupRef.current;
    if (fg) {
      _vPos.set(...sample.fridge.position);
      _euler.set(...sample.fridge.rotation);

      // Idle bob/yaw (progress === 0): y bob ±0.04, yaw ±4° (±0.07 rad)
      // Floating bob/yaw (progress === 1): y bob ±0.02, yaw ±6° (±0.10 rad)
      // Fades to 0 during travel; off when reduced
      if (!r.reduced) {
        if (r.progress === 0) {
          _vPos.y += Math.sin(r.time * 0.8) * 0.04;
          _euler.y += Math.sin(r.time * 0.5) * 0.07;
        } else if (r.progress === 1) {
          _vPos.y += Math.sin(r.time * 0.6) * 0.02;
          _euler.y += Math.sin(r.time * 0.4) * 0.10;
        }
      }

      fg.position.copy(_vPos);
      fg.rotation.copy(_euler);
      fg.scale.set(...sample.fridge.scale);
      fg.updateMatrixWorld();
    }

    // 3. Door pivot rotation
    if (parts.current.door) {
      parts.current.door.rotation.y = sample.door;
    }

    // 4. Interior light
    if (lampRef.current) {
      lampRef.current.intensity = sample.light * 1.5;
    }

    // 5. Items trajectory, visibility and floating motion
    const numItems = itemVisuals.length;
    itemVisuals.forEach(({ item, index, slot, seed }) => {
      const grp = itemGroupRefs.current.get(item.id);
      if (!grp || !fg) return;

      // Staggered launch start within release (0.86 .. 1.0)
      const itemStagger = numItems > 1 ? (index / (numItems - 1)) * 0.45 : 0;
      const tLaunch =
        sample.release <= itemStagger
          ? 0
          : Math.min(1, (sample.release - itemStagger) / (1 - itemStagger));

      // Manage original food visibility inside fridge
      const origNode = slot !== undefined ? parts.current.foodNodes.get(slot) : null;
      if (origNode) {
        // Original node in fridge is visible while inside (tLaunch === 0) and hidden once released
        origNode.visible = tLaunch === 0;
      }

      // World-space ejected group visibility
      if (tLaunch === 0) {
        grp.visible = false;
        return;
      }
      grp.visible = true;

      // Launch origin: slot position in world space
      const localSlot =
        slot !== undefined && SLOT_LOCAL_POS[slot]
          ? SLOT_LOCAL_POS[slot]
          : [0, 1.0, 0.45];
      _vOrigin.set(...localSlot).applyMatrix4(fg.matrixWorld);

      // Target anchor in world space
      const anchor = floatingAnchor(index, numItems, seed);
      _vTarget.set(...anchor);

      // Interpolate with arc
      _vPos.lerpVectors(_vOrigin, _vTarget, tLaunch);
      _vPos.y += Math.sin(tLaunch * Math.PI) * 0.35;

      // When fully floating (tLaunch === 1), add slow drift & tumble (off if reduced)
      if (tLaunch === 1 && !r.reduced) {
        _vPos.x += Math.sin(r.time * 0.5 + index * 1.3) * 0.04;
        _vPos.y += Math.sin(r.time * 0.7 + index * 1.1) * 0.05;
        _vPos.z += Math.cos(r.time * 0.6 + index * 1.5) * 0.04;
        grp.rotation.set(
          Math.sin(r.time * 0.4 + index) * 0.15,
          r.time * 0.15 + index * 0.7,
          Math.cos(r.time * 0.35 + index) * 0.15
        );
      } else {
        grp.rotation.set(0, 0, 0);
      }

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
            e.stopPropagation();
            if (rig.current.progress === 0 && !travel) {
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
        {/* Door spill interior light */}
        <pointLight
          ref={lampRef}
          position={[0, 1.62, 0.13]}
          intensity={0}
          distance={2.5}
          decay={2}
          color="#e7ffd9"
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
            onClick={(e) => {
              e.stopPropagation();
              if (pickRef.current) {
                onInspect(item.id);
              }
            }}
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
            {mesh ? (
              <primitive object={mesh} />
            ) : (
              <mesh>
                <capsuleGeometry args={[0.08, 0.14, 8, 16]} />
                <meshStandardMaterial
                  color={item.color || '#3fd6ff'}
                  emissive={isHovered || isSelected ? _glowColor : '#000000'}
                  emissiveIntensity={isHovered || isSelected ? 0.35 : 0}
                  roughness={0.25}
                  metalness={0.15}
                />
              </mesh>
            )}

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
      <ambientLight intensity={0.25} color="#101530" />
      <directionalLight position={[3, 4, 4]} intensity={1.2} color="#ddc89a" />
      <directionalLight position={[-4, 2, -2]} intensity={0.9} color="#3fd6ff" />
      <Environment resolution={128}>
        <Lightformer
          intensity={2.8}
          position={[-3, 2, -2]}
          scale={[3, 6, 1]}
          color="#3fd6ff"
        />
        <Lightformer
          intensity={2.2}
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
