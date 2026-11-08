import { Component, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { Environment, Lightformer, useGLTF } from '@react-three/drei'
import { MathUtils } from 'three'
import { advanceJourney, sampleJourney, SHELVES, canPickItem } from './fridgeMotion.mjs'

function itemIndex(object) {
  for (let node = object; node; node = node.parent) {
    if (Number.isInteger(node.userData?.itemIndex)) return node.userData.itemIndex
  }
  return null
}

function FridgeWorld({ enter, shelf, onEnter, onInspect, onPhase, onReady, onHover }) {
  const { scene } = useGLTF('/models/mini-fridge.glb?v=3')
  const model = useMemo(() => scene.clone(true), [scene])
  const rig = useRef({ progress: 0, height: SHELVES[0].height, reduced: false, phase: 'outside', hover: null })
  const lamp = useRef(null)
  const parts = useRef({ door: null, foods: [] })
  useEffect(() => {
    parts.current = { door: model.getObjectByName('DoorPivot'), foods: SHELVES.flatMap(s => s.items).map(i => model.getObjectByName(`Food_${i}`)) }
    model.traverse(node => {
      if (node.isMesh) {
        node.castShadow = !node.material.transparent
        node.receiveShadow = true
      }
    })
    onReady()
  }, [model, onReady])
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => { rig.current.reduced = media.matches }
    update(); media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  useFrame(({ camera, size, pointer }, delta) => {
    const state = rig.current
    state.progress = advanceJourney(state.progress, enter, delta, state.reduced)
    const phase = state.progress === 1 ? 'inside' : state.progress === 0 ? 'outside' : enter ? 'entering' : 'leaving'
    if (phase !== state.phase) { state.phase = phase; onPhase(phase) }
    state.height = state.reduced ? SHELVES[shelf].height : MathUtils.damp(state.height, SHELVES[shelf].height, 4, Math.min(delta, .05))
    const pose = sampleJourney(state.progress, size.width / size.height, state.height)
    const parallax = phase === 'inside' && !state.reduced ? .012 : 0
    camera.position.set(pose.position[0] + pointer.x * parallax, pose.position[1] + pointer.y * parallax, pose.position[2])
    camera.lookAt(...pose.target)
    if (Math.abs(camera.fov - pose.fov) > .001) { camera.fov = pose.fov; camera.updateProjectionMatrix() }
    if (parts.current.door) parts.current.door.rotation.y = pose.door
    if (lamp.current) lamp.current.intensity = pose.light * 1.2
    parts.current.foods.forEach((food, i) => {
      if (!food) return
      const isPickable = canPickItem(state.progress, state.height, shelf, i)
      if (!isPickable && state.hover === i) { state.hover = null; onHover(null); }
      const target = isPickable && state.hover === i ? 1.035 : 1
      const scale = state.reduced ? target : MathUtils.damp(food.scale.x, target, 8, Math.min(delta, .05))
      food.scale.setScalar(scale)
    })
  })
  return <>
    <primitive object={model} onClick={event => {
      event.stopPropagation()
      if (!enter) { onEnter(); return }
      const index = itemIndex(event.object)
      if (canPickItem(rig.current.progress, rig.current.height, shelf, index)) onInspect(index)
    }} onPointerMove={event => {
      event.stopPropagation()
      let index = itemIndex(event.object)
      if (!canPickItem(rig.current.progress, rig.current.height, shelf, index)) index = null
      if (rig.current.hover !== index) { rig.current.hover = index; onHover(index) }
    }} onPointerOut={() => { rig.current.hover = null; onHover(null) }}/>
    <pointLight ref={lamp} position={[0, 1.62, .13]} intensity={0} distance={2.1} decay={2} color="#e7ffd9"/>
    <pointLight position={[0, .75, .24]} intensity={enter ? .28 : 0} distance={1.2} color="#eaffdf"/>
  </>
}


class ModelBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch() { this.props.onFailure() }
  render() { return this.state.failed ? this.props.fallback : this.props.children }
}
export default function Fridge3D({ enter, shelf, onEnter, onInspect, onPhase, onFailure, onReady }) {
  const [hovered, setHovered] = useState(null)
  const fallback = <img className="model-fallback" src="/images/fridge-front.png" alt="Silver mini fridge. The interactive model is unavailable; inventory is available from the navigation." />
  return <div className={`model-view ${hovered !== null || !enter ? 'model-clickable' : ''}`}>
    <ModelBoundary fallback={fallback} onFailure={onFailure}>
      <Canvas shadows dpr={[1, 1.5]} camera={{ position: [2.7, 1.95, 4.8], near: .008, far: 40, fov: 34 }} fallback={<span aria-hidden="true">3D rendering is unavailable.</span>} gl={{ antialias: true, alpha: true }}>
        <ambientLight intensity={.65}/>
        <directionalLight position={[2, 5, 4]} intensity={2.3} castShadow shadow-mapSize={[1024, 1024]} shadow-bias={-.0002} shadow-normalBias={.012}/>
        <Environment resolution={128}>
          <Lightformer intensity={3} position={[-3, 2, 3]} scale={[2, 5, 1]}/>
          <Lightformer intensity={2} position={[3, 3, 1]} scale={[2, 4, 1]}/>
          <Lightformer intensity={1} position={[0, 5, -2]} rotation={[Math.PI / 2, 0, 0]} scale={5}/>
        </Environment>
        <Suspense fallback={null}><FridgeWorld enter={enter} shelf={shelf} onEnter={onEnter} onInspect={onInspect} onPhase={onPhase} onReady={onReady} onHover={setHovered}/></Suspense>
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -.008, 0]} receiveShadow><planeGeometry args={[200, 200]}/><shadowMaterial transparent opacity={.17}/></mesh>
      </Canvas>
    </ModelBoundary>
  </div>
}
