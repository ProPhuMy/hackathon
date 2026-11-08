import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { advanceJourney, sampleJourney, SHELVES, canPickItem } from '../../src/fridgeMotion.mjs'

// Exit works from any entry phase, and repeating entry never overshoots.
for (const start of [.1, .35, .7, 1]) {
  let p = start
  for (let i = 0; i < 300; i++) p = advanceJourney(p, false, 1 / 60)
  assert.equal(p, 0)
}
let p = 0
for (let i = 0; i < 300; i++) p = advanceJourney(p, true, 1 / 60)
assert.equal(p, 1)
assert.equal(advanceJourney(.2, true, 5), 1) // Resume from a background tab in real elapsed time.
assert.equal(advanceJourney(.43, true, .016, true), 1)
assert.equal(advanceJourney(.43, false, .016, true), 0)
assert.ok(advanceJourney(.4, false, .016) < .4)
assert.ok(advanceJourney(.4, true, .016) > .4)

// The door clears the camera before it crosses the front, on all shelves/aspects.
for (const aspect of [.5, .75, 1, 1.6, 2.4]) {
  for (const shelf of SHELVES) {
    let previous = sampleJourney(0, aspect, shelf.height)
    for (let i = 0; i <= 1000; i++) {
      const pose = sampleJourney(i / 1000, aspect, shelf.height)
      assert.ok([...pose.position, ...pose.target, pose.fov, pose.door].every(Number.isFinite))
      if (pose.position[2] < 1) assert.ok(pose.door < -1.9)
      assert.ok(Math.hypot(...pose.position.map((n, axis) => n - previous.position[axis])) < .03)
      previous = pose
    }
    const inside = sampleJourney(1, aspect, shelf.height)
    assert.equal(inside.door, -2.05)
    assert.ok(Math.abs(inside.position[1] - (shelf.height + .035)) < 1e-8)
    assert.ok(inside.position[2] < .65)
  }
}

// Production GLB includes the pivot and all six independently pickable item roots.
const file = readFileSync(new URL('../../public/models/mini-fridge.glb', import.meta.url))
assert.equal(file.toString('ascii', 0, 4), 'glTF')
const gltf = JSON.parse(file.toString('utf8', 20, 20 + file.readUInt32LE(12)))
assert.ok(gltf.nodes.find(n => n.name === 'DoorPivot')?.children.length > 0)
for (let i = 0; i < 6; i++) {
  const food = gltf.nodes.find(n => n.name === `Food_${i}`)
  assert.equal(food?.extras.itemIndex, i)
  assert.ok(food.children.length >= 3)
}
assert.equal(gltf.buffers.length, 1)
assert.ok(!gltf.buffers[0].uri, 'Model is self-contained')

// Selection filtering assertions
assert.ok(canPickItem(1, SHELVES[0].height, 0, 0)) // Matching shelf, valid item
assert.ok(!canPickItem(1, SHELVES[0].height, 0, 2)) // Matching shelf, item not on shelf
assert.ok(!canPickItem(1, SHELVES[0].height, 1, 0)) // Adjacent shelf
assert.ok(!canPickItem(1, SHELVES[0].height, 0, null)) // Invalid index
assert.ok(!canPickItem(0.99, SHELVES[0].height, 0, 0)) // Still transitioning in progress
assert.ok(!canPickItem(1, SHELVES[0].height + 0.02, 0, 0)) // Changing shelf (camera not settled)

console.log(`PASS: reversible camera path, reduced motion, door clearance, 5 aspect ratios × 3 shelves, ${gltf.nodes.length} model nodes and 6 selectable food groups`)