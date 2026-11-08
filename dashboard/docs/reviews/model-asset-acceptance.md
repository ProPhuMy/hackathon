# Model asset release accepted

Lead reviewed actual agy changes and requested stronger production assertions.
Accepted: identical GLB moved to src/assets, explicit Vite ?url loader, matching
Blender export destination, unchanged model/motion assertions, and build artifact
verification including duplicate detection and isolated content-hash mutation.
GLB SHA256:6f339e1bf69e38bb59a154b935bd5945edd61ae4c042308f8996f0d8879ad9c4.
Blender source SHA256:fa7ed14f86038f6f28e520224ce3f17da8ee51a6b1b6cd0c28f3aac875a4a932.
Both match original baseline. No geometry, material, timing or preload changes.

Lead standard commands (not worker config-loader workaround) all passed:
npm run build; npm run lint; fridge-motion.mjs; routes.mjs; mapping.mjs;
model-asset.mjs. Build emits one assets/mini-fridge-CahHtqR_.glb, referenced by
lazy3D bundle, with matching bytes. The existing large3D chunk warning remains.
Integrated into dashboard branch; combined visual QA waits for live-data patch.
