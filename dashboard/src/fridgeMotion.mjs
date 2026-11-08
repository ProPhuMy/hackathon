// One reversible playhead keeps orbit, door and dolly synchronized even when
// Escape is pressed halfway through entry. Values are in GLTF world coordinates.
export const ENTRY_SECONDS = 3.8
export const SHELVES = [
  { name: 'Top shelf', note: 'THE DAILY ESSENTIALS', height: 1.48, items: [0, 1] },
  { name: 'Middle shelf', note: 'A LITTLE PICK-ME-UP', height: 1.08, items: [2, 3] },
  { name: 'Lower shelf', note: 'SOMETHING FRESH', height: .68, items: [4, 5] },
]
const mix = (a, b, t) => a + (b - a) * t
const ease = t => { const n = Math.min(1, Math.max(0, t)); return n * n * (3 - 2 * n) }
const segment = (t, start, end) => ease((t - start) / (end - start))
export function sampleJourney(progress, aspect = 1.6, shelfHeight = SHELVES[0].height) {
  const mobile = aspect < .8
  const orbit = segment(progress, 0, .43)
  const dolly = segment(progress, .46, 1)
  const home = mobile ? [2.3, 2.2, 5.5] : [2.7, 1.95, 4.8]
  const homeTarget = mobile ? [-.12, 1.62, 0] : [-.95, 1.02, 0]
  const position = home.map((value, i) => mix(value, [-.16, 1.42, 3.55][i], orbit))
  const target = homeTarget.map((value, i) => mix(value, [0, 1.05, 0][i], orbit))
  // Portrait keeps a little more distance so both items remain visible.
  const inside = [0, shelfHeight + .035, mobile ? .64 : .34]
  for (let i = 0; i < 3; i++) {
    position[i] = mix(position[i], inside[i], dolly)
    target[i] = mix(target[i], [0, shelfHeight - .035, -.25][i], dolly)
  }
  return { position, target, fov: mix(mobile ? 36 : 34, mobile ? 91 : 78, dolly), door: -2.05 * segment(progress, .22, .59), light: segment(progress, .25, .65) }
}
export function advanceJourney(value, enter, delta, reduced = false) {
  if (reduced) return enter ? 1 : 0
  return Math.min(1, Math.max(0, value + (enter ? 1 : -1) * Math.max(0, delta) / ENTRY_SECONDS))
}
export function canPickItem(progress, rigHeight, shelfIndex, itemIndex) {
  if (progress !== 1 || itemIndex === null || itemIndex === undefined) return false
  const shelf = SHELVES[shelfIndex]
  if (!shelf) return false
  if (Math.abs(rigHeight - shelf.height) > 0.01) return false
  return shelf.items.includes(itemIndex)
}
