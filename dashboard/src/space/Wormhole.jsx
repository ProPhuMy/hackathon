import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { PALETTE_GLSL, SIMPLEX_NOISE_3D } from './shaders.glsl'

// Preallocated module-scope temporaries (zero allocations per frame)
const _camPos = new THREE.Vector3()
const _camDir = new THREE.Vector3()
const _portalPos = new THREE.Vector3()
const _exitPos = new THREE.Vector3()

// Deterministic PRNG for spark particles
function createPRNG(seed = 54321) {
  let s = seed
  return () => {
    s = (s * 16807 + 0) % 2147483647
    return (s - 1) / 2147483646
  }
}

// 1. Event horizon disk: opaque black void that occludes stars behind it (Correction 5)
const horizonVertexShader = /* glsl */`
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const horizonFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  uniform float uIntensity;
  varying vec2 vUv;

  void main() {
    vec2 p = vUv - vec2(0.5);
    float dist = length(p) * 2.0;
    if (dist > 1.0) discard;

    // Hot rim edge glow
    float rim = smoothstep(0.85, 1.0, dist);
    vec3 col = mix(VOID_COLOR, CYAN_COLOR * 0.8 + STAR_COLOR * 0.2, rim * 0.7);

    // Normal blending with depthWrite true occludes stars behind it
    float alpha = uIntensity;
    gl_FragColor = vec4(col, alpha);
  }
`

// 2. Accretion ring shader
const accretionVertexShader = /* glsl */`
  varying vec2 vPos;
  void main() {
    vPos = position.xy;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const accretionFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  ${SIMPLEX_NOISE_3D}

  uniform float uTime;
  uniform float uIntensity;
  uniform float uSwirl;
  uniform float uReduced;
  varying vec2 vPos;

  void main() {
    float r = length(vPos);
    float theta = atan(vPos.y, vPos.x);

    float swirlSpeed = (uReduced > 0.5) ? 0.0 : (uTime * (1.0 + 3.0 * uSwirl));
    float angle = theta + swirlSpeed - r * 2.8;

    float bands = pow(sin(angle * 4.0) * 0.5 + 0.5, 2.5);
    float noiseVal = snoise(vec3(cos(angle) * 2.5, sin(angle) * 2.5, r * 2.0 - ((uReduced > 0.5) ? 0.0 : uTime * 0.8)));
    noiseVal = smoothstep(0.15, 0.85, noiseVal);

    float pattern = bands * 0.55 + noiseVal * 0.55;

    // Radial falloff: inner edge r=0.88, outer edge r=2.4
    float ringFalloff = smoothstep(0.85, 1.05, r) * smoothstep(2.4, 1.4, r);

    // Color gradient: hot inner edge ember/white -> magenta -> violet outer
    float rNorm = clamp((r - 0.9) / 1.5, 0.0, 1.0);
    vec3 col = mix(EMBER_COLOR, MAGENTA_COLOR, smoothstep(0.0, 0.45, rNorm));
    col = mix(col, VIOLET_COLOR, smoothstep(0.45, 1.0, rNorm));

    // Hot inner core glow
    float innerGlow = pow(smoothstep(1.3, 0.9, r), 2.0);
    col = mix(col, vec3(1.0), innerGlow * 0.65);

    vec3 finalCol = col * (pattern + 0.3) * ringFalloff * uIntensity * 0.9;
    float alpha = ringFalloff * uIntensity;

    gl_FragColor = vec4(finalCol, alpha);
  }
`

// 3. Gravitational lensing illusion ring
const lensVertexShader = /* glsl */`
  varying vec2 vPos;
  void main() {
    vPos = position.xy;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const lensFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  uniform float uTime;
  uniform float uIntensity;
  uniform float uReduced;
  varying vec2 vPos;

  void main() {
    float r = length(vPos);
    float theta = atan(vPos.y, vPos.x);

    float timeVal = (uReduced > 0.5) ? 0.0 : (uTime * 1.5);
    float wave = sin(r * 12.0 - timeVal + theta * 3.0) * 0.5 + 0.5;
    float flare = pow(wave, 5.0) * smoothstep(1.05, 1.35, r) * smoothstep(3.2, 1.7, r);

    vec3 lensCol = mix(CYAN_COLOR, VIOLET_COLOR, sin(theta * 2.0) * 0.5 + 0.5);
    vec3 finalCol = lensCol * flare * uIntensity * 0.6;
    float alpha = flare * uIntensity;

    gl_FragColor = vec4(finalCol, alpha);
  }
`

// 4. GPU-animated sparks (100% vertex shader animation, Correction 1)
const sparkVertexShader = /* glsl */`
  uniform float uTime;
  uniform float uIntensity;
  uniform float uSwirl;
  uniform float uReduced;

  attribute float aAngle;
  attribute float aRadius;
  attribute float aZOffset;
  attribute float aSpeed;
  attribute float aSize;
  attribute float aPhase;

  varying float vLife;
  varying float vPhase;

  void main() {
    if (uIntensity < 0.001) {
      gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
      return;
    }

    float t = (uReduced > 0.5) ? aPhase : fract(uTime * aSpeed * 0.45 + aPhase);
    vLife = t;
    vPhase = aPhase;

    float r = mix(aRadius, 0.78, t);
    float spin = (uReduced > 0.5) ? 0.0 : (t * 7.0 * (1.0 + 2.0 * uSwirl) + (1.2 / (r + 0.1)));
    float angle = aAngle + spin;

    vec3 localPos = vec3(cos(angle) * r, sin(angle) * r, aZOffset * (1.0 - t));
    vec4 mvPosition = modelViewMatrix * vec4(localPos, 1.0);
    gl_Position = projectionMatrix * mvPosition;

    float sizeFade = smoothstep(0.0, 0.2, t) * smoothstep(1.0, 0.75, t);
    gl_PointSize = min(aSize * sizeFade * uIntensity * (110.0 / -mvPosition.z), 9.0);
  }
`

const sparkFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  varying float vLife;
  varying float vPhase;

  void main() {
    vec2 coord = gl_PointCoord - vec2(0.5);
    float dist = length(coord);
    if (dist > 0.5) discard;

    float halo = smoothstep(0.5, 0.0, dist);
    float core = smoothstep(0.18, 0.0, dist);

    vec3 outerCol = mix(CYAN_COLOR, MAGENTA_COLOR, vPhase);
    vec3 sparkCol = mix(outerCol, EMBER_COLOR, vLife);
    sparkCol = mix(sparkCol, vec3(1.0), core * 0.75);

    float alpha = halo * smoothstep(0.0, 0.15, vLife) * smoothstep(1.0, 0.8, vLife);
    gl_FragColor = vec4(sparkCol * alpha, alpha);
  }
`

// 5. Tunnel shader: scrolling energy rings, twisted streaks, chromatic aberration, core glow, edge darkening (Correction 4)
const tunnelVertexShader = /* glsl */`
  varying vec3 vLocalPos;
  varying vec2 vUv;

  void main() {
    vLocalPos = position;
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

const tunnelFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  ${SIMPLEX_NOISE_3D}

  uniform float uTime;
  uniform float uTunnel;
  uniform float uTunnelSpeed;
  uniform float uWarp;
  uniform float uReduced;
  #define TUNNEL_AHEAD 90.0

  varying vec3 vLocalPos;
  varying vec2 vUv;

  float calcPattern(float angle, float zCoord, float timeVal, float speedVal, float warpVal, float radialOffset) {
    float twist = zCoord * 0.12 * (1.0 + 3.5 * warpVal);
    float theta = angle + radialOffset + twist;

    float zScroll = zCoord * 0.35 + timeVal * speedVal * 2.6;
    float rings = sin(zScroll * 6.28318);
    rings = pow(rings * 0.5 + 0.5, 4.0);

    float streaks = snoise(vec3(cos(theta) * 2.8, sin(theta) * 2.8, zCoord * 0.18 + timeVal * speedVal * 1.6));
    streaks = smoothstep(0.25, 0.8, streaks);

    return rings * 0.7 + streaks * 0.55;
  }

  void main() {
    if (uTunnel < 0.001) {
      discard;
    }

    float zCoord = TUNNEL_AHEAD - vLocalPos.z; // distance ahead of the camera
    float zNorm = clamp(zCoord / 200.0, 0.0, 1.0);

    float angle = atan(vLocalPos.y, vLocalPos.x);

    float effSpeed = (uReduced > 0.5) ? 0.0 : uTunnelSpeed;
    float effWarp  = (uReduced > 0.5) ? 0.0 : uWarp;

    // Fake chromatic aberration: 3 radial offsets scaled by warp
    float aberration = effWarp * 0.055;
    float patR = calcPattern(angle, zCoord, uTime, effSpeed, effWarp, -aberration);
    float patG = calcPattern(angle, zCoord, uTime, effSpeed, effWarp, 0.0);
    float patB = calcPattern(angle, zCoord, uTime, effSpeed, effWarp, aberration);

    float hue = fract(zNorm * 0.5 + uTime * effSpeed * 0.06);
    vec3 baseCol = (hue < 0.33) ? mix(VIOLET_COLOR, MAGENTA_COLOR, hue * 3.0) :
                   (hue < 0.66) ? mix(MAGENTA_COLOR, CYAN_COLOR, (hue - 0.33) * 3.0) :
                                  mix(CYAN_COLOR, VIOLET_COLOR, (hue - 0.66) * 3.0);

    vec3 col = vec3(
      baseCol.r * patR,
      baseCol.g * patG,
      baseCol.b * patB
    );

    // Bright core glow down center far end
    float farGlow = smoothstep(0.35, 1.0, zNorm);
    col += mix(CYAN_COLOR, vec3(1.0), 0.75) * (farGlow * 0.9);

    // Edge darkening near camera end
    float entranceFade = smoothstep(0.0, 0.03, zNorm);
    float exitFade = smoothstep(1.0, 0.94, zNorm);
    col *= (entranceFade * exitFade);

    col *= uTunnel;

    float alpha = clamp(max(max(col.r, col.g), col.b), 0.0, 1.0);
    gl_FragColor = vec4(col, alpha);
  }
`

// 6. Camera flash plane shader
const flashVertexShader = /* glsl */`
  void main() {
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`

const flashFragmentShader = /* glsl */`
  ${PALETTE_GLSL}
  uniform float uFlash;

  void main() {
    if (uFlash < 0.001) discard;
    float f = uFlash * uFlash * 0.8;
    vec3 col = mix(vec3(1.0), CYAN_COLOR, 0.35) * f;
    gl_FragColor = vec4(col, f);
  }
`

function buildSparkGeometry(count, seed) {
  const prng = createPRNG(seed)
  const geo = new THREE.BufferGeometry()
  const angles = new Float32Array(count)
  const radii = new Float32Array(count)
  const zOffsets = new Float32Array(count)
  const speeds = new Float32Array(count)
  const sizes = new Float32Array(count)
  const phases = new Float32Array(count)

  for (let i = 0; i < count; i++) {
    angles[i] = prng() * Math.PI * 2
    radii[i] = 1.1 + prng() * 2.5
    zOffsets[i] = (prng() - 0.5) * 0.6
    speeds[i] = 0.8 + prng() * 1.5
    sizes[i] = 2.0 + prng() * 3.5
    phases[i] = prng()
  }

  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3))
  geo.setAttribute('aAngle', new THREE.BufferAttribute(angles, 1))
  geo.setAttribute('aRadius', new THREE.BufferAttribute(radii, 1))
  geo.setAttribute('aZOffset', new THREE.BufferAttribute(zOffsets, 1))
  geo.setAttribute('aSpeed', new THREE.BufferAttribute(speeds, 1))
  geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
  geo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
  return geo
}

export default function Wormhole({ rig }) {
  const portalGroupRef = useRef(null)
  const exitGroupRef = useRef(null)
  const horizonMeshRef = useRef(null)
  const accretionMeshRef = useRef(null)
  const lensMeshRef = useRef(null)
  const sparkMeshRef = useRef(null)
  const exitHorizonMeshRef = useRef(null)
  const exitAccretionMeshRef = useRef(null)
  const tunnelMeshRef = useRef(null)
  const flashMeshRef = useRef(null)

  const geometries = useMemo(() => {
    const tGeo = new THREE.CylinderGeometry(7.0, 7.0, 220, 64, 64, true)
    tGeo.rotateX(Math.PI / 2)

    return {
      horizon: new THREE.CircleGeometry(1.0, 48),
      ring: new THREE.RingGeometry(0.85, 2.4, 64, 16),
      lens: new THREE.RingGeometry(1.05, 3.2, 64, 16),
      spark: buildSparkGeometry(1200, 501),
      tunnel: tGeo,
      flash: new THREE.PlaneGeometry(2, 2),
    }
  }, [])

  useEffect(() => {
    const geo = geometries
    return () => {
      geo.horizon.dispose()
      geo.ring.dispose()
      geo.lens.dispose()
      geo.spark.dispose()
      geo.tunnel.dispose()
      geo.flash.dispose()
    }
  }, [geometries])

  useFrame(({ camera }) => {
    const rigState = rig?.current
    if (!rigState) return

    const { sample, time, reduced } = rigState
    const reducedVal = reduced ? 1.0 : 0.0

    camera.getWorldPosition(_camPos)
    camera.getWorldDirection(_camDir)

    // 1. Entry Portal Mouth
    if (portalGroupRef.current && sample?.portal) {
      const pIntensity = sample.portal.intensity ?? 0
      const pRadius = sample.portal.radius ?? 1
      const pSwirl = sample.portal.swirl ?? 0

      if (pIntensity > 0.0001) {
        portalGroupRef.current.visible = true
        _portalPos.fromArray(sample.portal.position)
        portalGroupRef.current.position.copy(_portalPos)
        portalGroupRef.current.lookAt(_camPos)
        portalGroupRef.current.scale.setScalar(pRadius)

        if (horizonMeshRef.current?.material?.uniforms) {
          horizonMeshRef.current.material.uniforms.uIntensity.value = pIntensity
        }
        // Fade the glowing parts as the camera nears the mouth so the dive reads as falling into darkness, not a white-out.
        const glow = pIntensity * THREE.MathUtils.smoothstep(_camPos.distanceTo(_portalPos), pRadius * 0.9, pRadius * 3.5)
        if (accretionMeshRef.current?.material?.uniforms) {
          accretionMeshRef.current.material.uniforms.uTime.value = time
          accretionMeshRef.current.material.uniforms.uIntensity.value = glow
          accretionMeshRef.current.material.uniforms.uSwirl.value = pSwirl
          accretionMeshRef.current.material.uniforms.uReduced.value = reducedVal
        }
        if (lensMeshRef.current?.material?.uniforms) {
          lensMeshRef.current.material.uniforms.uTime.value = time
          lensMeshRef.current.material.uniforms.uIntensity.value = glow
          lensMeshRef.current.material.uniforms.uReduced.value = reducedVal
        }
        if (sparkMeshRef.current?.material?.uniforms) {
          sparkMeshRef.current.material.uniforms.uTime.value = time
          sparkMeshRef.current.material.uniforms.uIntensity.value = glow
          sparkMeshRef.current.material.uniforms.uSwirl.value = pSwirl
          sparkMeshRef.current.material.uniforms.uReduced.value = reducedVal
        }
      } else {
        portalGroupRef.current.visible = false
      }
    }

    // 2. Tunnel
    if (tunnelMeshRef.current) {
      const tunnelVal = sample?.tunnel ?? 0
      if (tunnelVal > 0.0001) {
        tunnelMeshRef.current.visible = true
        tunnelMeshRef.current.position.copy(_camPos)
        tunnelMeshRef.current.position.addScaledVector(_camDir, 90.0) // must match TUNNEL_AHEAD in the shader
        tunnelMeshRef.current.quaternion.copy(camera.quaternion)

        if (tunnelMeshRef.current.material?.uniforms) {
          tunnelMeshRef.current.material.uniforms.uTime.value = time
          tunnelMeshRef.current.material.uniforms.uTunnel.value = tunnelVal
          tunnelMeshRef.current.material.uniforms.uTunnelSpeed.value = sample?.tunnelSpeed ?? 1.0
          tunnelMeshRef.current.material.uniforms.uWarp.value = sample?.warp ?? 0.0
          tunnelMeshRef.current.material.uniforms.uReduced.value = reducedVal
        }
      } else {
        tunnelMeshRef.current.visible = false
      }
    }

    // 3. Exit Portal
    if (exitGroupRef.current && sample?.exitPortal) {
      const eIntensity = sample.exitPortal.intensity ?? 0
      const eRadius = sample.exitPortal.radius ?? 1

      if (eIntensity > 0.0001) {
        exitGroupRef.current.visible = true
        _exitPos.fromArray(sample.exitPortal.position)
        exitGroupRef.current.position.copy(_exitPos)
        exitGroupRef.current.lookAt(_camPos)
        exitGroupRef.current.scale.setScalar(eRadius)

        if (exitHorizonMeshRef.current?.material?.uniforms) {
          exitHorizonMeshRef.current.material.uniforms.uIntensity.value = eIntensity
        }
        if (exitAccretionMeshRef.current?.material?.uniforms) {
          exitAccretionMeshRef.current.material.uniforms.uTime.value = time
          exitAccretionMeshRef.current.material.uniforms.uIntensity.value = eIntensity
          exitAccretionMeshRef.current.material.uniforms.uReduced.value = reducedVal
        }
      } else {
        exitGroupRef.current.visible = false
      }
    }

    // 4. Flash Plane
    if (flashMeshRef.current?.material?.uniforms) {
      const rawFlash = sample?.flash ?? 0
      const flashVal = reduced ? Math.min(rawFlash, 0.3) : rawFlash
      flashMeshRef.current.material.uniforms.uFlash.value = flashVal
    }
  })

  return (
    <>
      {/* Entry Portal */}
      <group ref={portalGroupRef} visible={false}>
        <mesh ref={horizonMeshRef} geometry={geometries.horizon} renderOrder={10}>
          <shaderMaterial
            vertexShader={horizonVertexShader}
            fragmentShader={horizonFragmentShader}
            uniforms={{
              uIntensity: { value: 0 },
            }}
            transparent
            depthWrite
            blending={THREE.NormalBlending}
            side={THREE.DoubleSide}
          />
        </mesh>
        <mesh ref={accretionMeshRef} geometry={geometries.ring} renderOrder={20}>
          <shaderMaterial
            vertexShader={accretionVertexShader}
            fragmentShader={accretionFragmentShader}
            uniforms={{
              uTime: { value: 0 },
              uIntensity: { value: 0 },
              uSwirl: { value: 0 },
              uReduced: { value: 0 },
            }}
            transparent
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            side={THREE.DoubleSide}
          />
        </mesh>
        <mesh ref={lensMeshRef} geometry={geometries.lens} renderOrder={25}>
          <shaderMaterial
            vertexShader={lensVertexShader}
            fragmentShader={lensFragmentShader}
            uniforms={{
              uTime: { value: 0 },
              uIntensity: { value: 0 },
              uReduced: { value: 0 },
            }}
            transparent
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            side={THREE.DoubleSide}
          />
        </mesh>
        <points ref={sparkMeshRef} geometry={geometries.spark} renderOrder={30}>
          <shaderMaterial
            vertexShader={sparkVertexShader}
            fragmentShader={sparkFragmentShader}
            uniforms={{
              uTime: { value: 0 },
              uIntensity: { value: 0 },
              uSwirl: { value: 0 },
              uReduced: { value: 0 },
            }}
            transparent
            depthWrite={false}
            blending={THREE.AdditiveBlending}
          />
        </points>
      </group>

      {/* Wormhole Tunnel */}
      <mesh ref={tunnelMeshRef} geometry={geometries.tunnel} visible={false} frustumCulled={false}>
        <shaderMaterial
          vertexShader={tunnelVertexShader}
          fragmentShader={tunnelFragmentShader}
          uniforms={{
            uTime: { value: 0 },
            uTunnel: { value: 0 },
            uTunnelSpeed: { value: 1.0 },
            uWarp: { value: 0 },
            uReduced: { value: 0 },
          }}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          side={THREE.BackSide}
        />
      </mesh>

      {/* Exit Portal */}
      <group ref={exitGroupRef} visible={false}>
        <mesh ref={exitHorizonMeshRef} geometry={geometries.horizon} renderOrder={10}>
          <shaderMaterial
            vertexShader={horizonVertexShader}
            fragmentShader={horizonFragmentShader}
            uniforms={{
              uIntensity: { value: 0 },
            }}
            transparent
            depthWrite
            blending={THREE.NormalBlending}
            side={THREE.DoubleSide}
          />
        </mesh>
        <mesh ref={exitAccretionMeshRef} geometry={geometries.ring} renderOrder={20}>
          <shaderMaterial
            vertexShader={accretionVertexShader}
            fragmentShader={accretionFragmentShader}
            uniforms={{
              uTime: { value: 0 },
              uIntensity: { value: 0 },
              uSwirl: { value: 1.0 },
              uReduced: { value: 0 },
            }}
            transparent
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            side={THREE.DoubleSide}
          />
        </mesh>
      </group>

      {/* Flash plane: camera-facing additive plane, depthTest false, renderOrder 999 */}
      <mesh ref={flashMeshRef} geometry={geometries.flash} renderOrder={999} frustumCulled={false}>
        <shaderMaterial
          vertexShader={flashVertexShader}
          fragmentShader={flashFragmentShader}
          uniforms={{
            uFlash: { value: 0 },
          }}
          transparent
          depthWrite={false}
          depthTest={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
    </>
  )
}
