# FridgeCheck landing page

Static page (HTML, CSS, a little JS; no build step) that introduces FridgeCheck, embeds the demo video and links
to this repository. Same space theme and pixel font as the dashboard and the demo video.

## Run locally

YouTube only plays embedded videos on pages served over http(s); opening `index.html` as a file shows
"Error 153" in the player. Serve the folder instead:

```bash
cd landing
python3 -m http.server 8000   # then open http://localhost:8000
```

## Publish with GitHub Pages

Repository Settings → Pages → Source: "Deploy from a branch" → branch `main`, folder `/ (root)`, then open
`https://prophumy.github.io/hackathon/landing/`. (Or move these files to `/docs` and pick that folder.)

## Assets

- `assets/fridge-pixel.ttf`: the dashboard's display font (`dashboard/public/fonts/`)
- `assets/fridge.png`: the dashboard's fridge image with its white background removed
- `assets/og-image.jpg`: the video thumbnail, used as the link preview image
