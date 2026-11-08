import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { MeshSurfaceSampler } from 'three/examples/jsm/math/MeshSurfaceSampler.js'
import { PALETTE_GLSL, SIMPLEX_NOISE_3D } from './shaders.glsl'

// Stylised (toon) explosion, after the reference explosion.gif:
// white-hot pop → radial spike streaks → billowing fire puffs → puffs cool to
// charcoal smoke with ember cracks → smoke breaks apart and dissolves.
// Everything is a pure function of sample.burst, so Return home rewinds it exactly.
// Nothing idles in place: debris and sparks keep moving outward until they are gone.

const _pos = new THREE.Vector3()
const _quat = new THREE.Quaternion()
const _rotQuat = new THREE.Quaternion()
const _obj = new THREE.Object3D()
const _pGeom = new THREE.Vector3()
const _nGeom = new THREE.Vector3()
const CENTER = new THREE.Vector3(0, 0.925, 0.12)

const PUFF_COUNT = 38
const SPIKE_COUNT = 28
const SHARD_COUNT = 140
const SPARK_COUNT = 1200

function createPRNG(seed) {
  let s = seed
  return () => {
    s = (s * 16807) % 2147483647
    return (s - 1) / 2147483646
  }
}
const clamp01 = t => Math.min(1, Math.max(0, t))
const easeOutCubic = t => 1 - Math.pow(1 - clamp01(t), 3)
const easeOutExpo = t => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t))

// Random direction that never points much toward the camera (which sits along +z).
function spreadDir(prng, target) {
  target.set(prng() - 0.5, prng() - 0.5, prng() - 0.5)
  target.z = Math.min(target.z, 0.35 * Math.hypot(target.x, target.y))
  if (target.lengthSq() < 1e-4) target.set(0, 1, 0)
  return target.normalize()
}

// ── Fire / smoke puffs ────────────────────────────────────────────────
const puffVertexShader = /* glsl */`
  ${SIMPLEX_NOISE_3D}
  attribute float aSeed;
  attribute float aDelay;
  varying vec3 vNormal;
  varying vec3 vView;
  varying vec3 vLocal;
  varying float vSeed;
  varying float vDelay;
  void main() {
    vLocal = position;
    vSeed = aSeed;
    vDelay = aDelay;
    // Lumpy cauliflower surface.
    vec3 p = position * (1.0 + snoise(position * 1.8 + aSeed * 13.0) * 0.2);
    vec4 mv = modelViewMatrix * instanceMatrix * vec4(p, 1.0);
    vNormal = normalize(normalMatrix * mat3(instanceMatrix) * normal);
    vView = -mv.xyz;
    gl_Position = projectionMatrix * mv;
  }
`

const puffFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  ${SIMPLEX_NOISE_3D}
  uniform float uBurst;
  varying vec3 vNormal;
  varying vec3 vView;
  varying vec3 vLocal;
  varying float vSeed;
  varying float vDelay;
  void main() {
    float b = uBurst;
    float lump = snoise(vLocal * 2.2 + vSeed * 17.0);
    float grain = snoise(vLocal * 1.9 + vSeed * 31.0) * 0.5 + 0.5;

    // Late phase: the smoke breaks into fragments and dissolves.
    float dissolve = smoothstep(0.58, 0.97, b);
    if (grain < dissolve) discard;

    vec3 N = normalize(vNormal);
    float facing = clamp(dot(N, normalize(vView)), 0.0, 1.0);
    float rim = 1.0 - facing;
    float heat = 1.0 - smoothstep(0.05 + vDelay, 0.5 + vDelay, b); // 1 = white hot, 0 = cold smoke

    // Three-band toon lighting for the smoke body.
    float l = dot(N, normalize(vec3(0.45, 0.8, 0.4))) * 0.5 + 0.5 + lump * 0.12;
    float band = l > 0.64 ? 1.0 : (l > 0.4 ? 0.62 : 0.34);
    vec3 smoke = vec3(0.11, 0.10, 0.12) * (0.55 + band * 0.95);

    vec3 hotCore = mix(vec3(1.0, 0.45, 0.12), vec3(1.0, 0.82, 0.35), smoothstep(0.25, 0.7, facing + lump * 0.2));
    hotCore = mix(hotCore, vec3(1.0, 0.97, 0.88), smoothstep(0.82, 0.98, facing) * smoothstep(0.75, 1.0, heat));
    // While cooling, ember survives in the cracks and along the silhouette.
    float crack = smoothstep(0.5, 0.88, rim + lump * 0.4);
    vec3 col = mix(smoke, EMBER_COLOR * 1.3, crack * smoothstep(0.0, 0.55, heat + 0.12));
    // Narrow toon switch from fire to smoke (a wide blend reads as muddy khaki).
    col = mix(col, hotCore, smoothstep(0.62, 0.7, heat + lump * 0.08));

    // Glowing edge on the dissolving fragments.
    if (dissolve > 0.0) col = mix(EMBER_COLOR, col, smoothstep(dissolve, dissolve + 0.07, grain));
    gl_FragColor = vec4(col, 1.0);
  }
`

// ── Spike streaks (screen-aligned, radiating from the centre) ─────────
const spikeVertexShader = /* glsl */`
  uniform float uBurst;
  attribute vec3 aDir;
  attribute float aLen;
  attribute float aWidth;
  attribute float aDelay;
  varying float vAlong;
  varying float vFade;
  void main() {
    float t = clamp((uBurst - aDelay) / 0.24, 0.0, 1.0);
    float grow = 1.0 - pow(1.0 - t, 3.0);
    vFade = (1.0 - t) * step(0.0001, uBurst - aDelay);
    vAlong = position.y;
    vec4 c = modelViewMatrix * vec4(0.0, 0.925, 0.12, 1.0);
    vec2 d = normalize((modelViewMatrix * vec4(aDir, 0.0)).xy + 1e-5);
    vec2 side = vec2(-d.y, d.x);
    float r0 = 0.4 + 1.4 * grow;
    float r1 = r0 + aLen * (0.35 + 0.65 * grow);
    c.xy += d * mix(r0, r1, position.y) + side * position.x * aWidth * (1.0 - position.y);
    gl_Position = projectionMatrix * c;
  }
`

const spikeFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  varying float vAlong;
  varying float vFade;
  void main() {
    vec3 col = mix(vec3(1.0, 0.97, 0.86), EMBER_COLOR, vAlong);
    float a = vFade * (1.0 - vAlong * 0.5);
    gl_FragColor = vec4(col * a, a);
  }
`

// ── Pop flash: covers the cabinet → debris swap, then gets out of the way ──
const flashVertexShader = /* glsl */`
  uniform float uRadius;
  varying vec2 vUv;
  void main() {
    vUv = uv;
    vec4 mv = modelViewMatrix * vec4(0.0, 0.925, 0.12, 1.0);
    mv.xy += position.xy * uRadius * 2.0 * vec2(1.0, 1.15);
    gl_Position = projectionMatrix * mv;
  }
`

const flashFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  uniform float uBurst;
  uniform float uReduced;
  varying vec2 vUv;
  void main() {
    float d = length((vUv - 0.5) * 2.0);
    if (d > 1.0) discard;
    float intensity = (1.0 - exp(-uBurst * 160.0)) * (1.0 - smoothstep(0.03, 0.14, uBurst));
    if (uReduced > 0.5) intensity = min(intensity, 0.3);
    vec3 col = mix(EMBER_COLOR, vec3(1.0, 0.97, 0.9), smoothstep(0.9, 0.2, d)) * 1.6;
    float alpha = smoothstep(1.0, 0.25, d) * intensity;
    gl_FragColor = vec4(col * alpha, alpha);
  }
`

// ── Sparks: streak outward and burn out ───────────────────────────────
const sparkVertexShader = /* glsl */`
  uniform float uBurst;
  attribute vec3 aDir;
  attribute float aSpeed;
  attribute float aSize;
  attribute float aColorType;
  varying float vColorType;
  varying float vAlpha;
  void main() {
    vColorType = aColorType;
    if (uBurst < 0.0005) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }
    float expo = uBurst >= 1.0 ? 1.0 : 1.0 - pow(2.0, -10.0 * uBurst);
    vec3 pos = vec3(0.0, 0.925, 0.12) + aDir * aSpeed * (0.55 * expo + 0.45 * uBurst) * 5.0;
    vec4 mv = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mv;
    vAlpha = pow(1.0 - uBurst, 1.4);
    gl_PointSize = min(aSize * (115.0 / -mv.z) * vAlpha, 5.0);
  }
`

const sparkFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  varying float vColorType;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    vec3 c = vColorType < 0.7 ? EMBER_COLOR : vec3(1.0, 0.9, 0.7);
    c = mix(c, vec3(1.0), smoothstep(0.18, 0.0, d) * 0.8);
    float a = smoothstep(0.5, 0.0, d) * vAlpha;
    gl_FragColor = vec4(c * a, a);
  }
`

// ── Pre-burst ember glow behind the fridge ────────────────────────────
const seamVertexShader = /* glsl */`
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const seamFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  uniform float uLight;
  varying vec2 vUv;
  void main() {
    vec2 p = (vUv - 0.5) * 2.0;
    p.x *= 1.35;
    float d = length(p);
    if (uLight < 0.001 || d > 1.0) discard;
    float f = pow(smoothstep(1.0, 0.0, d), 2.2);
    float alpha = f * uLight * 0.85;
    gl_FragColor = vec4(mix(EMBER_COLOR, vec3(1.0, 0.85, 0.5), f * 0.5) * alpha, alpha);
  }
`

function buildPuffs() {
  const prng = createPRNG(4242)
  const dir = new THREE.Vector3()
  const seeds = new Float32Array(PUFF_COUNT)
  const delays = new Float32Array(PUFF_COUNT)
  const puffs = []
  for (let i = 0; i < PUFF_COUNT; i++) {
    spreadDir(prng, dir)
    const r = 0.12 + 0.95 * Math.sqrt(prng())
    // Bigger puffs near the core, smaller ones at the fringe.
    const size = (0.24 + 0.3 * prng()) * (1.2 - 0.4 * r / 1.07)
    seeds[i] = prng() * 10
    delays[i] = (r / 1.07) * 0.08
    puffs.push({ dir: dir.clone(), r, size, delay: delays[i] })
  }
  const geo = new THREE.IcosahedronGeometry(1, 4)
  geo.setAttribute('aSeed', new THREE.InstancedBufferAttribute(seeds, 1))
  geo.setAttribute('aDelay', new THREE.InstancedBufferAttribute(delays, 1))
  return { geo, puffs }
}

function buildSpikes() {
  const prng = createPRNG(9191)
  const plane = new THREE.PlaneGeometry(1, 1, 1, 1)
  plane.translate(0, 0.5, 0) // y: 0 = base, 1 = tip
  const geo = new THREE.InstancedBufferGeometry()
  geo.index = plane.index
  geo.setAttribute('position', plane.getAttribute('position'))
  geo.instanceCount = SPIKE_COUNT
  const dirs = new Float32Array(SPIKE_COUNT * 3)
  const lens = new Float32Array(SPIKE_COUNT)
  const widths = new Float32Array(SPIKE_COUNT)
  const delays = new Float32Array(SPIKE_COUNT)
  const d = new THREE.Vector3()
  for (let i = 0; i < SPIKE_COUNT; i++) {
    spreadDir(prng, d)
    dirs.set([d.x, d.y, d.z], i * 3)
    lens[i] = 0.8 + prng() * 1.8
    widths[i] = 0.05 + prng() * 0.09
    delays[i] = prng() * 0.05
  }
  geo.setAttribute('aDir', new THREE.InstancedBufferAttribute(dirs, 3))
  geo.setAttribute('aLen', new THREE.InstancedBufferAttribute(lens, 1))
  geo.setAttribute('aWidth', new THREE.InstancedBufferAttribute(widths, 1))
  geo.setAttribute('aDelay', new THREE.InstancedBufferAttribute(delays, 1))
  return geo
}

function buildSparks() {
  const prng = createPRNG(3344)
  const dirs = new Float32Array(SPARK_COUNT * 3)
  const speeds = new Float32Array(SPARK_COUNT)
  const sizes = new Float32Array(SPARK_COUNT)
  const colors = new Float32Array(SPARK_COUNT)
  const d = new THREE.Vector3()
  for (let i = 0; i < SPARK_COUNT; i++) {
    spreadDir(prng, d)
    dirs.set([d.x, d.y, d.z], i * 3)
    speeds[i] = 1.0 + prng() * 2.4
    sizes[i] = 2 + prng() * 3
    colors[i] = prng()
  }
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(SPARK_COUNT * 3), 3))
  geo.setAttribute('aDir', new THREE.BufferAttribute(dirs, 3))
  geo.setAttribute('aSpeed', new THREE.BufferAttribute(speeds, 1))
  geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
  geo.setAttribute('aColorType', new THREE.BufferAttribute(colors, 1))
  return geo
}

function buildShardGeometry() {
  const shape = new THREE.Shape(
    [[0, 0.62], [0.38, 0.12], [0.22, -0.5], [-0.18, -0.38], [-0.42, 0.05]].map(([x, y]) => new THREE.Vector2(x, y)),
  )
  const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.08, bevelEnabled: false })
  geo.center()
  return geo
}

const additive = { transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }

export default function Explosion({ rig, model }) {
  const puffsRef = useRef(null)
  const spikesRef = useRef(null)
  const flashRef = useRef(null)
  const sparksRef = useRef(null)
  const shardsRef = useRef(null)
  const seamRef = useRef(null)

  const assets = useMemo(() => {
    const { geo: puffGeo, puffs } = buildPuffs()
    return {
      puffs,
      puffGeo,
      puffMat: new THREE.ShaderMaterial({ vertexShader: puffVertexShader, fragmentShader: puffFragmentShader, uniforms: { uBurst: { value: 0 } } }),
      spikeGeo: buildSpikes(),
      spikeMat: new THREE.ShaderMaterial({ vertexShader: spikeVertexShader, fragmentShader: spikeFragmentShader, uniforms: { uBurst: { value: 0 } }, side: THREE.DoubleSide, depthTest: false, ...additive }),
      quadGeo: new THREE.PlaneGeometry(1, 1),
      flashMat: new THREE.ShaderMaterial({ vertexShader: flashVertexShader, fragmentShader: flashFragmentShader, uniforms: { uBurst: { value: 0 }, uRadius: { value: 1.3 }, uReduced: { value: 0 } }, depthTest: false, ...additive }),
      sparkGeo: buildSparks(),
      sparkMat: new THREE.ShaderMaterial({ vertexShader: sparkVertexShader, fragmentShader: sparkFragmentShader, uniforms: { uBurst: { value: 0 } }, ...additive }),
      shardGeo: buildShardGeometry(),
      shardMat: new THREE.MeshStandardMaterial({ metalness: 0.6, roughness: 0.45, side: THREE.DoubleSide }),
      seamGeo: new THREE.PlaneGeometry(2.4, 3.2),
      seamMat: new THREE.ShaderMaterial({ vertexShader: seamVertexShader, fragmentShader: seamFragmentShader, uniforms: { uLight: { value: 0 } }, ...additive }),
    }
  }, [])

  useEffect(() => () => {
    for (const asset of Object.values(assets)) asset.dispose?.()
  }, [assets])

  // Charred fridge debris, sampled on the cabinet/door surfaces (fridge-local space).
  const shards = useMemo(() => {
    if (!model) return []
    model.updateMatrixWorld(true)
    const toLocal = model.matrixWorld.clone().invert()
    const isFood = node => { for (let n = node; n; n = n.parent) if (n.name?.startsWith('Food_')) return true; return false }
    const sources = []
    model.traverse(node => {
      if (!node.isMesh || isFood(node)) return
      const sampler = new MeshSurfaceSampler(node).build()
      const color = (node.material?.color?.clone() ?? new THREE.Color('#b8bcc8')).multiplyScalar(0.45)
      sources.push({ sampler, area: sampler.distribution.at(-1) || 1, matrix: toLocal.clone().multiply(node.matrixWorld), color })
    })
    if (!sources.length) return []
    const total = sources.reduce((sum, s) => sum + s.area, 0)
    const prng = createPRNG(77712)
    const zAxis = new THREE.Vector3(0, 0, 1)
    return Array.from({ length: SHARD_COUNT }, () => {
      let r = prng() * total
      const src = sources.find(s => (r -= s.area) <= 0) ?? sources[0]
      src.sampler.sample(_pGeom, _nGeom)
      const origin = _pGeom.clone().applyMatrix4(src.matrix)
      const normal = _nGeom.clone().transformDirection(src.matrix)
      const size = 0.06 + prng() * 0.1
      return {
        origin,
        baseQuat: new THREE.Quaternion().setFromAxisAngle(normal, prng() * Math.PI * 2).multiply(new THREE.Quaternion().setFromUnitVectors(zAxis, normal)),
        dir: spreadDir(prng, new THREE.Vector3()),
        distance: 6 + prng() * 8,
        scale: new THREE.Vector3(size * (0.7 + prng() * 0.6), size * (0.7 + prng() * 0.6), size),
        rotAxis: new THREE.Vector3(prng() - 0.5, prng() - 0.5, prng() - 0.5).normalize(),
        rotAngle: (1 + prng() * 3) * Math.PI * 2,
        color: src.color,
      }
    })
  }, [model])

  useEffect(() => {
    const mesh = shardsRef.current
    if (!mesh || !shards.length) return
    shards.forEach((s, i) => mesh.setColorAt(i, s.color))
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  }, [shards])

  useFrame(() => {
    const state = rig?.current
    if (!state) return
    const burst = state.sample?.burst ?? 0
    const light = state.sample?.light ?? 0
    const live = burst >= 0.0005 && burst < 0.999

    const puffs = puffsRef.current
    if (puffs) {
      puffs.visible = live
      if (live) {
        puffs.material.uniforms.uBurst.value = burst
        const spread = 0.3 + 0.7 * easeOutCubic(burst / 0.35)
        for (let i = 0; i < assets.puffs.length; i++) {
          const p = assets.puffs[i]
          // Billow out fast, keep drifting outward, never settle.
          _obj.position.copy(CENTER).addScaledVector(p.dir, p.r * spread + 0.5 * burst)
          const grow = easeOutCubic((burst - p.delay * 0.5) / 0.09)
          _obj.scale.setScalar(p.size * grow * (1 - 0.35 * THREE.MathUtils.smoothstep(burst, 0.6, 1)))
          _obj.quaternion.identity()
          _obj.updateMatrix()
          puffs.setMatrixAt(i, _obj.matrix)
        }
        puffs.instanceMatrix.needsUpdate = true
      }
    }

    const spikes = spikesRef.current
    if (spikes) {
      spikes.visible = burst >= 0.0005 && burst < 0.35
      if (spikes.visible) spikes.material.uniforms.uBurst.value = burst
    }

    const flash = flashRef.current
    if (flash) {
      flash.visible = burst >= 0.0005 && burst < 0.15
      if (flash.visible) {
        const u = flash.material.uniforms
        u.uBurst.value = burst
        u.uRadius.value = 1.3 + 0.6 * easeOutCubic(burst / 0.14)
        u.uReduced.value = state.reduced ? 1 : 0
      }
    }

    const sparks = sparksRef.current
    if (sparks) {
      sparks.visible = live
      if (live) sparks.material.uniforms.uBurst.value = burst
    }

    const shardMesh = shardsRef.current
    if (shardMesh) {
      shardMesh.visible = burst >= 0.02 && burst < 0.999 && shards.length > 0
      if (shardMesh.visible) {
        const b = (burst - 0.02) / 0.98
        const dist = 0.4 * easeOutExpo(b) + 0.6 * b
        const shrink = 1 - THREE.MathUtils.smoothstep(b, 0.5, 0.95)
        for (let i = 0; i < shards.length; i++) {
          const s = shards[i]
          _pos.copy(s.origin).addScaledVector(s.dir, s.distance * dist)
          _rotQuat.setFromAxisAngle(s.rotAxis, s.rotAngle * b)
          _quat.copy(s.baseQuat).multiply(_rotQuat)
          _obj.position.copy(_pos)
          _obj.quaternion.copy(_quat)
          _obj.scale.copy(s.scale).multiplyScalar(shrink)
          _obj.updateMatrix()
          shardMesh.setMatrixAt(i, _obj.matrix)
        }
        shardMesh.instanceMatrix.needsUpdate = true
      }
    }

    const seam = seamRef.current
    if (seam) {
      seam.visible = light >= 0.001 && burst < 0.16
      if (seam.visible) seam.material.uniforms.uLight.value = light
    }
  })

  return <>
    <instancedMesh ref={shardsRef} args={[assets.shardGeo, assets.shardMat, SHARD_COUNT]} visible={false} frustumCulled={false} />
    <instancedMesh ref={puffsRef} args={[assets.puffGeo, assets.puffMat, PUFF_COUNT]} visible={false} frustumCulled={false} renderOrder={30} />
    <mesh ref={spikesRef} geometry={assets.spikeGeo} material={assets.spikeMat} visible={false} frustumCulled={false} renderOrder={44} />
    <points ref={sparksRef} geometry={assets.sparkGeo} material={assets.sparkMat} visible={false} frustumCulled={false} renderOrder={46} />
    <mesh ref={flashRef} geometry={assets.quadGeo} material={assets.flashMat} visible={false} frustumCulled={false} renderOrder={48} />
    <mesh ref={seamRef} geometry={assets.seamGeo} material={assets.seamMat} position={[0, 0.925, -0.05]} visible={false} frustumCulled={false} renderOrder={35} />
  </>
}
