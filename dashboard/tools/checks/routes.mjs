import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createMemoryHistory, createRouter } from '@tanstack/react-router'
const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
try {
  const { router } = await server.ssrLoadModule('/src/router.jsx')
  for (const path of ['/', '/inventory', '/history', '/alerts', '/people', '/items/043', '/events/0934']) {
    const testRouter = createRouter({ routeTree: router.routeTree, history: createMemoryHistory({ initialEntries: [path] }), isServer: true })
    await testRouter.load()
    assert.equal(testRouter.state.location.pathname, path)
    assert.ok(testRouter.state.matches.every(m => m.status === 'success'), `Failed route ${path}`)
    assert.equal(testRouter.state.matches.length, 2)
  }
  console.log('Passed: 7 direct route loads, including item and event deep links')
} finally { await server.close() }
