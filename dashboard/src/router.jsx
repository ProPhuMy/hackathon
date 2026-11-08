import { createRootRoute, createRoute, createRouter, Link } from '@tanstack/react-router'
import App from './App.jsx'

const rootRoute = createRootRoute({
  component: App,
  notFoundComponent: () => <div className="route-not-found"><h2>Nothing on this shelf.</h2><Link to="/">Return to the fridge</Link></div>,
})
const paths = ['/', '/inventory', '/history', '/alerts', '/people', '/items/$itemId', '/events/$eventId']
const routes = paths.map(path => createRoute({ getParentRoute: () => rootRoute, path, component: () => null }))
export const router = createRouter({ routeTree: rootRoute.addChildren(routes), defaultPreload: 'intent' })
