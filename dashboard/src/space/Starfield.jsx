import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { PALETTE_GLSL, SIMPLEX_NOISE_3D } from './shaders.glsl'

// Preallocated module-scope temporary objects (zero allocations in useFrame)
const _camPos = new THREE.Vector3()
const _camDir = new THREE.Vector3()

// Deterministic PRNG so no Math.random() is called during render
function createPRNG(seed = 12345) {
  let s = seed
  return () => {
    s = (s * 16807 + 0) % 2147483647
    return (s - 1) / 2147483646
  }
}

// Star point shaders
const starVertexShader = /* glsl */`
  uniform float uTime;
  uniform float uTwinkle;
  uniform vec3 uCameraPos;
  uniform float uWrap;
  uniform float uWrapSize;

  attribute float aSize;
  attribute float aPhase;
  attribute float aSpeed;
  attribute float aTemp;

  varying float vTemp;
  varying float vAlpha;

  void main() {
    vTemp = aTemp;
    vec3 worldPos = position;

    if (uWrap > 0.5) {
      vec3 halfBox = vec3(uWrapSize * 0.5);
      vec3 rel = position - uCameraPos;
      rel = mod(rel + halfBox, uWrapSize) - halfBox;
      worldPos = uCameraPos + rel;
    }

    vec4 mvPosition = viewMatrix * vec4(worldPos, 1.0);
    gl_Position = projectionMatrix * mvPosition;

    float twinkle = mix(1.0, 0.65 + 0.35 * sin(uTime * aSpeed + aPhase), uTwinkle);
    gl_PointSize = min(aSize * twinkle * (280.0 / -mvPosition.z), 7.0);

    vAlpha = smoothstep(1.5, 4.0, -mvPosition.z);
  }
`

const starFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  varying float vTemp;
  varying float vAlpha;

  void main() {
    vec2 coord = gl_PointCoord - vec2(0.5);
    float dist = length(coord);
    if (dist > 0.5) discard;

    float core = smoothstep(0.2, 0.0, dist);
    float halo = smoothstep(0.5, 0.0, dist);

    vec3 starColor = mix(CYAN_COLOR * 0.9 + STAR_COLOR * 0.1, EMBER_COLOR * 0.8 + STAR_COLOR * 0.2, vTemp);
    vec3 finalColor = mix(starColor, vec3(1.0), core * 0.7);

    float alpha = halo * vAlpha;
    gl_FragColor = vec4(finalColor * alpha, alpha);
  }
`

const warpVertexShader = /* glsl */`
  uniform vec3 uCameraPos;
  uniform vec3 uCamDir;
  uniform float uWarp;
  uniform float uWrapSize;

  attribute vec3 aInstancePos;
  attribute float aInstanceSpeed;
  attribute float aInstanceWidth;
  attribute float aInstanceTemp;

  varying vec2 vUv;
  varying float vTemp;
  varying float vAlpha;

  void main() {
    vUv = uv;
    vTemp = aInstanceTemp;

    if (uWarp < 0.001) {
      gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
      return;
    }

    vec3 halfBox = vec3(uWrapSize * 0.5);
    vec3 rel = aInstancePos - uCameraPos;
    rel = mod(rel + halfBox, uWrapSize) - halfBox;
    vec3 starPos = uCameraPos + rel;

    float streakLen = uWarp * (6.0 + 22.0 * aInstanceSpeed);
    vec3 axis = normalize(-uCamDir);

    vec3 toCam = normalize(uCameraPos - starPos);
    vec3 side = cross(axis, toCam);
    if (dot(side, side) < 0.0001) side = vec3(1.0, 0.0, 0.0);
    else side = normalize(side);

    vec3 worldPos = starPos + axis * (streakLen * position.y) + side * (aInstanceWidth * position.x);

    vec4 mvPosition = viewMatrix * vec4(worldPos, 1.0);
    gl_Position = projectionMatrix * mvPosition;

    vAlpha = smoothstep(1.5, 4.0, -mvPosition.z) * uWarp;
  }
`

const warpFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  varying vec2 vUv;
  varying float vTemp;
  varying float vAlpha;

  void main() {
    float edgeX = abs(vUv.x - 0.5) * 2.0;
    float alphaX = smoothstep(1.0, 0.0, edgeX);

    float alphaY = smoothstep(0.0, 0.15, vUv.y) * smoothstep(1.0, 0.45, vUv.y);
    float alpha = alphaX * alphaY * vAlpha;

    vec3 streakColor = mix(CYAN_COLOR, STAR_COLOR, vTemp);
    streakColor = mix(streakColor, vec3(1.0), pow(alphaX, 3.0) * 0.6);

    gl_FragColor = vec4(streakColor * alpha, alpha);
  }
`

const nebulaVertexShader = /* glsl */`
  varying vec3 vWorldDir;
  void main() {
    vWorldDir = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const nebulaFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  ${SIMPLEX_NOISE_3D}

  uniform float uTime;
  uniform float uNebulaHue;
  varying vec3 vWorldDir;

  void main() {
    vec3 dir = normalize(vWorldDir);

    float n1 = fbm3(dir * 2.2 + vec3(0.0, uTime * 0.015, 0.0));
    float n2 = fbm3(dir * 4.5 - vec3(uTime * 0.01, 0.0, 0.0));
    float nebulaNoise = smoothstep(0.15, 0.85, n1 * 0.7 + n2 * 0.3);

    vec3 homeCol = mix(DEEP_COLOR * 0.5, VIOLET_COLOR, nebulaNoise);
    vec3 destCol = mix(MAGENTA_COLOR, CYAN_COLOR, smoothstep(0.2, 0.7, n2));
    destCol = mix(destCol, EMBER_COLOR, smoothstep(0.6, 0.95, n1));

    vec3 finalCol = mix(homeCol, destCol, uNebulaHue);
    float alpha = (0.04 + 0.10 * nebulaNoise);
    gl_FragColor = vec4(finalCol * alpha, alpha);
  }
`

function buildShellGeometry(count, radiusMin, radiusMax, seed) {
  const prng = createPRNG(seed)
  const positions = new Float32Array(count * 3)
  const sizes = new Float32Array(count)
  const phases = new Float32Array(count)
  const speeds = new Float32Array(count)
  const temps = new Float32Array(count)

  for (let i = 0; i < count; i++) {
    const u = prng()
    const v = prng()
    const theta = u * 2.0 * Math.PI
    const phi = Math.acos(2.0 * v - 1.0)
    const r = radiusMin + prng() * (radiusMax - radiusMin)

    positions[i * 3 + 0] = r * Math.sin(phi) * Math.cos(theta)
    positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
    positions[i * 3 + 2] = r * Math.cos(phi)

    sizes[i] = 1.0 + prng() * 2.2
    phases[i] = prng() * Math.PI * 2
    speeds[i] = 1.5 + prng() * 3.5
    temps[i] = prng()
  }

  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
  geo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
  geo.setAttribute('aSpeed', new THREE.BufferAttribute(speeds, 1))
  geo.setAttribute('aTemp', new THREE.BufferAttribute(temps, 1))
  return geo
}

function buildBoxGeometry(count, boxSize, seed) {
  const prng = createPRNG(seed)
  const positions = new Float32Array(count * 3)
  const sizes = new Float32Array(count)
  const phases = new Float32Array(count)
  const speeds = new Float32Array(count)
  const temps = new Float32Array(count)

  for (let i = 0; i < count; i++) {
    positions[i * 3 + 0] = (prng() - 0.5) * boxSize
    positions[i * 3 + 1] = (prng() - 0.5) * boxSize
    positions[i * 3 + 2] = (prng() - 0.5) * boxSize

    sizes[i] = 1.5 + prng() * 2.8
    phases[i] = prng() * Math.PI * 2
    speeds[i] = 2.0 + prng() * 4.0
    temps[i] = prng()
  }

  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
  geo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
  geo.setAttribute('aSpeed', new THREE.BufferAttribute(speeds, 1))
  geo.setAttribute('aTemp', new THREE.BufferAttribute(temps, 1))
  return geo
}

function buildWarpGeometry(count, boxSize, seed) {
  const prng = createPRNG(seed)
  const baseGeo = new THREE.InstancedBufferGeometry()
  const vertices = new Float32Array([
    -0.5, 0.0, 0.0,
     0.5, 0.0, 0.0,
    -0.5, 1.0, 0.0,
     0.5, 1.0, 0.0,
  ])
  const uvs = new Float32Array([
    0, 0,
    1, 0,
    0, 1,
    1, 1,
  ])
  const indices = [0, 1, 2, 2, 1, 3]

  baseGeo.setAttribute('position', new THREE.BufferAttribute(vertices, 3))
  baseGeo.setAttribute('uv', new THREE.BufferAttribute(uvs, 2))
  baseGeo.setIndex(indices)

  const instancePositions = new Float32Array(count * 3)
  const instanceSpeeds = new Float32Array(count)
  const instanceWidths = new Float32Array(count)
  const instanceTemps = new Float32Array(count)

  for (let i = 0; i < count; i++) {
    instancePositions[i * 3 + 0] = (prng() - 0.5) * boxSize
    instancePositions[i * 3 + 1] = (prng() - 0.5) * boxSize
    instancePositions[i * 3 + 2] = (prng() - 0.5) * boxSize

    instanceSpeeds[i] = 0.5 + prng() * 1.5
    instanceWidths[i] = 0.06 + prng() * 0.08
    instanceTemps[i] = prng()
  }

  baseGeo.setAttribute('aInstancePos', new THREE.InstancedBufferAttribute(instancePositions, 3))
  baseGeo.setAttribute('aInstanceSpeed', new THREE.InstancedBufferAttribute(instanceSpeeds, 1))
  baseGeo.setAttribute('aInstanceWidth', new THREE.InstancedBufferAttribute(instanceWidths, 1))
  baseGeo.setAttribute('aInstanceTemp', new THREE.InstancedBufferAttribute(instanceTemps, 1))
  return baseGeo
}

export default function Starfield({ rig }) {
  const groupRef = useRef(null)
  const farMeshRef = useRef(null)
  const midMeshRef = useRef(null)
  const nearMeshRef = useRef(null)
  const warpMeshRef = useRef(null)
  const nebulaMeshRef = useRef(null)

  const geometries = useMemo(() => {
    return {
      far: buildShellGeometry(3500, 100, 150, 101),
      mid: buildShellGeometry(2500, 50, 85, 202),
      near: buildBoxGeometry(1500, 60.0, 303),
      warp: buildWarpGeometry(1500, 60.0, 404),
      nebula: new THREE.SphereGeometry(150, 32, 24),
    }
  }, [])

  useEffect(() => {
    const geo = geometries
    return () => {
      geo.far.dispose()
      geo.mid.dispose()
      geo.near.dispose()
      geo.warp.dispose()
      geo.nebula.dispose()
    }
  }, [geometries])

  useFrame(({ camera }) => {
    const rigState = rig?.current
    if (!rigState) return

    const { sample, time, reduced } = rigState

    camera.getWorldPosition(_camPos)
    camera.getWorldDirection(_camDir)

    if (groupRef.current) {
      groupRef.current.position.copy(_camPos)
    }

    const twinkleVal = reduced ? 0.0 : 1.0

    if (farMeshRef.current?.material?.uniforms) {
      farMeshRef.current.material.uniforms.uTime.value = time
      farMeshRef.current.material.uniforms.uTwinkle.value = twinkleVal
    }

    if (midMeshRef.current?.material?.uniforms) {
      midMeshRef.current.material.uniforms.uTime.value = time
      midMeshRef.current.material.uniforms.uTwinkle.value = twinkleVal
    }

    if (nearMeshRef.current?.material?.uniforms) {
      nearMeshRef.current.material.uniforms.uTime.value = time
      nearMeshRef.current.material.uniforms.uTwinkle.value = twinkleVal
      nearMeshRef.current.material.uniforms.uCameraPos.value.copy(_camPos)
    }

    if (warpMeshRef.current?.material?.uniforms) {
      warpMeshRef.current.material.uniforms.uWarp.value = reduced ? 0.0 : (sample?.warp ?? 0.0)
      warpMeshRef.current.material.uniforms.uCameraPos.value.copy(_camPos)
      warpMeshRef.current.material.uniforms.uCamDir.value.copy(_camDir)
    }

    if (nebulaMeshRef.current?.material?.uniforms) {
      nebulaMeshRef.current.material.uniforms.uTime.value = time
      nebulaMeshRef.current.material.uniforms.uNebulaHue.value = sample?.nebulaHue ?? 0.0
    }
  })

  return (
    <>
      <group ref={groupRef}>
        <points ref={farMeshRef} geometry={geometries.far} frustumCulled={false}>
          <shaderMaterial
            vertexShader={starVertexShader}
            fragmentShader={starFragmentShader}
            uniforms={{
              uTime: { value: 0 },
              uTwinkle: { value: 1.0 },
              uCameraPos: { value: new THREE.Vector3() },
              uWrap: { value: 0.0 },
              uWrapSize: { value: 60.0 },
            }}
            transparent
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </points>
        <points ref={midMeshRef} geometry={geometries.mid} frustumCulled={false}>
          <shaderMaterial
            vertexShader={starVertexShader}
            fragmentShader={starFragmentShader}
            uniforms={{
              uTime: { value: 0 },
              uTwinkle: { value: 1.0 },
              uCameraPos: { value: new THREE.Vector3() },
              uWrap: { value: 0.0 },
              uWrapSize: { value: 60.0 },
            }}
            transparent
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </points>
        <mesh ref={nebulaMeshRef} geometry={geometries.nebula} frustumCulled={false}>
          <shaderMaterial
            vertexShader={nebulaVertexShader}
            fragmentShader={nebulaFragmentShader}
            uniforms={{
              uTime: { value: 0 },
              uNebulaHue: { value: 0.0 },
            }}
            transparent
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            side={THREE.BackSide}
          />
        </mesh>
      </group>
      <points ref={nearMeshRef} geometry={geometries.near} frustumCulled={false}>
        <shaderMaterial
          vertexShader={starVertexShader}
          fragmentShader={starFragmentShader}
          uniforms={{
            uTime: { value: 0 },
            uTwinkle: { value: 1.0 },
            uCameraPos: { value: new THREE.Vector3() },
            uWrap: { value: 1.0 },
            uWrapSize: { value: 60.0 },
          }}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </points>
      <mesh ref={warpMeshRef} geometry={geometries.warp} frustumCulled={false}>
        <shaderMaterial
          vertexShader={warpVertexShader}
          fragmentShader={warpFragmentShader}
          uniforms={{
            uCameraPos: { value: new THREE.Vector3() },
            uCamDir: { value: new THREE.Vector3(0, 0, -1) },
            uWarp: { value: 0.0 },
            uWrapSize: { value: 60.0 },
          }}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          side={THREE.DoubleSide}
        />
      </mesh>
    </>
  )
}
