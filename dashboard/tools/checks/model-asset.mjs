import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { existsSync, readdirSync, readFileSync, rmSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'

const rootDir = fileURLToPath(new URL('../../', import.meta.url))
const sourceGlbPath = join(rootDir, 'src/assets/mini-fridge.glb')
const publicGlbPath = join(rootDir, 'public/models/mini-fridge.glb')
const distDir = join(rootDir, 'dist')
const distAssetsDir = join(rootDir, 'dist/assets')

// Helper for recursive directory walk
function findFilesRecursive(dir) {
  const entries = readdirSync(dir, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const fullPath = join(dir, entry.name)
    if (entry.isDirectory()) {
      files.push(...findFilesRecursive(fullPath))
    } else if (entry.isFile()) {
      files.push(fullPath)
    }
  }
  return files
}

// 1. Verify source asset contract and SHA-256
assert.ok(existsSync(sourceGlbPath), 'Source GLB must exist at src/assets/mini-fridge.glb')
assert.ok(!existsSync(publicGlbPath), 'Legacy GLB must not exist at public/models/mini-fridge.glb')

const sourceBuffer = readFileSync(sourceGlbPath)
assert.equal(sourceBuffer.toString('ascii', 0, 4), 'glTF', 'Source GLB must have glTF header')
assert.ok(sourceBuffer.length > 0, 'Source GLB must not be empty')
const sourceHash = createHash('sha256').update(sourceBuffer).digest('hex')

// 2. Verify built distribution (do not skip; fail clearly if dist is missing)
assert.ok(
  existsSync(distDir) && existsSync(distAssetsDir),
  'Production build output not found. Run "npm run build" before running this check.'
)

// Recursively scan entire dist to verify exactly ONE .glb exists anywhere in the build output
const allDistFiles = findFilesRecursive(distDir)
const allDistGlbFiles = allDistFiles.filter(f => f.endsWith('.glb'))

assert.equal(
  allDistGlbFiles.length,
  1,
  `Expected exactly one .glb file across entire dist output, found ${allDistGlbFiles.length}: ${allDistGlbFiles.map(f => relative(distDir, f)).join(', ') || 'none'}`
)

const soleGlbPath = allDistGlbFiles[0]
const relativeGlbPath = relative(distDir, soleGlbPath).replace(/\\/g, '/')
const soleGlbName = basename(soleGlbPath)

assert.match(
  relativeGlbPath,
  /^assets\/mini-fridge-[A-Za-z0-9_-]+\.glb$/,
  `Expected sole .glb to be assets/mini-fridge-[hash].glb, found: ${relativeGlbPath}`
)

const builtBuffer = readFileSync(soleGlbPath)
const builtHash = createHash('sha256').update(builtBuffer).digest('hex')
assert.equal(
  builtHash,
  sourceHash,
  `Built asset SHA256 (${builtHash}) must match source asset SHA256 (${sourceHash})`
)

// Verify built JS bundle(s) actually reference the emitted hashed GLB file name
const allDistJsFiles = allDistFiles.filter(f => f.endsWith('.js'))
assert.ok(allDistJsFiles.length > 0, 'Expected at least one built JavaScript file in dist')
let referencedInJs = false
for (const jsFile of allDistJsFiles) {
  const jsContent = readFileSync(jsFile, 'utf8')
  if (jsContent.includes(soleGlbName)) {
    referencedInJs = true
    break
  }
}
assert.ok(
  referencedInJs,
  `Built JavaScript chunks must reference the exact hashed GLB filename: ${soleGlbName}`
)
console.log(`PASS: Sole built GLB in dist matches source (${relativeGlbPath}, sha256: ${sourceHash})`)

// 3. Isolated minimal Vite fixture verifying hash mutation with asset ?url and configFile: false
const fixtureDir = mkdtempSync(join(tmpdir(), 'fridge-vite-fixture-'))
try {
  const entryPath = join(fixtureDir, 'entry.js')
  const modelPath = join(fixtureDir, 'fixture-model.glb')
  writeFileSync(entryPath, "import url from './fixture-model.glb?url';\nconsole.log(url);\nexport default url;\n")

  // First build with original fixture content
  writeFileSync(modelPath, 'glTF-fixture-payload-version-1')
  await build({
    root: fixtureDir,
    configFile: false,
    logLevel: 'silent',
    build: {
      assetsInlineLimit: 0,
      outDir: join(fixtureDir, 'dist-a'),
      rollupOptions: { input: entryPath }
    }
  })

  const distAFiles = readdirSync(join(fixtureDir, 'dist-a/assets'))
  const glbA = distAFiles.find(f => /^fixture-model-[A-Za-z0-9_-]+\.glb$/.test(f))
  const jsAFile = distAFiles.find(f => f.endsWith('.js'))
  assert.ok(glbA, 'Fixture A must emit hashed GLB asset')
  assert.ok(jsAFile, 'Fixture A must emit JS bundle')
  const jsA = readFileSync(join(fixtureDir, 'dist-a/assets', jsAFile), 'utf8')
  assert.ok(jsA.includes(glbA), 'Fixture JS bundle must reference emitted hashed asset filename')

  // Second build with mutated fixture content (original source asset is never touched)
  writeFileSync(modelPath, 'glTF-fixture-payload-version-2-mutated-content')
  await build({
    root: fixtureDir,
    configFile: false,
    logLevel: 'silent',
    build: {
      assetsInlineLimit: 0,
      outDir: join(fixtureDir, 'dist-b'),
      rollupOptions: { input: entryPath }
    }
  })

  const distBFiles = readdirSync(join(fixtureDir, 'dist-b/assets'))
  const glbB = distBFiles.find(f => /^fixture-model-[A-Za-z0-9_-]+\.glb$/.test(f))
  const jsBFile = distBFiles.find(f => f.endsWith('.js'))
  assert.ok(glbB, 'Fixture B must emit hashed GLB asset')
  assert.ok(jsBFile, 'Fixture B must emit JS bundle')
  const jsB = readFileSync(join(fixtureDir, 'dist-b/assets', jsBFile), 'utf8')
  assert.ok(jsB.includes(glbB), 'Fixture JS bundle B must reference mutated hashed asset filename')

  assert.notEqual(
    glbA,
    glbB,
    `Asset content mutation must produce different hashed filenames (${glbA} vs ${glbB})`
  )
  console.log(`PASS: Hash mutation verified in isolated fixture (${glbA} -> ${glbB})`)
} finally {
  rmSync(fixtureDir, { recursive: true, force: true })
}

console.log('PASS: model-asset check passed.')
