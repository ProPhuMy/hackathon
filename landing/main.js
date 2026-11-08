// FridgeCheck landing page: drifting starfield, scroll reveals and count-up numbers. The page reads fine without it.
document.documentElement.classList.add("js");
const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Starfield: three parallax layers drifting left, like the dashboard and the demo video.
const canvas = document.getElementById("stars");
const ctx = canvas.getContext("2d");
let stars = [];
const resize = () => {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = innerWidth * dpr;
  canvas.height = innerHeight * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const count = Math.round((innerWidth * innerHeight) / 6500);
  stars = Array.from({ length: count }, (_, i) => {
    const layer = i % 3;
    return { x: Math.random() * innerWidth, y: Math.random() * innerHeight, layer, phase: Math.random() * 6.28 };
  });
};
const LAYERS = [
  { size: 0.9, speed: 0.06, alpha: 0.45 },
  { size: 1.5, speed: 0.18, alpha: 0.7 },
  { size: 2.2, speed: 0.4, alpha: 0.95 },
];
const draw = (t) => {
  ctx.clearRect(0, 0, innerWidth, innerHeight);
  for (const s of stars) {
    const l = LAYERS[s.layer];
    if (!reduced) s.x = (s.x - l.speed + innerWidth) % innerWidth;
    ctx.globalAlpha = l.alpha * (0.6 + 0.4 * Math.sin(t / 600 + s.phase));
    ctx.fillStyle = "#fff";
    ctx.beginPath();
    ctx.arc(s.x, s.y, l.size, 0, Math.PI * 2);
    ctx.fill();
  }
  if (!reduced) requestAnimationFrame(draw);
};
resize();
addEventListener("resize", resize);
requestAnimationFrame(draw);

// Count numbers up from 0 when they scroll into view.
const countUp = (el) => {
  const to = Number(el.dataset.to);
  if (reduced) return (el.textContent = to);
  const start = performance.now();
  const tick = (now) => {
    const p = Math.min(1, (now - start) / 1200);
    el.textContent = Math.round(to * (1 - (1 - p) ** 3));
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
};

const seen = new IntersectionObserver(
  (entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("in");
      e.target.querySelectorAll(".count").forEach(countUp);
      if (e.target.classList.contains("count")) countUp(e.target);
      seen.unobserve(e.target);
    }
  },
  { threshold: 0.15 },
);
document.querySelectorAll(".reveal").forEach((el) => seen.observe(el));
