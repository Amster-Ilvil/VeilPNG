# VeilPNG Web — local redaction preview

This independent static web workspace processes PNG and JPEG files in the browser. It supports a multi-image queue, inclusive rectangular masks, freehand brush and eraser, undo/redo, black/white opaque redaction, PNG export and a stored ZIP of marked pages. Output names are generic numbered names. Transparent source areas are flattened onto white. Unmarked or empty masks are not exported. There are no accounts, analytics, remote scripts, network APIs, uploads or persistent browser storage. A restrictive CSP blocks network requests by the application. The hosting provider may still record ordinary page visits; browser extensions and the operating system are outside the application's control.

This is a preview, not desktop/CLI parity. It does not implement encrypted containers, hidden-layer reconstruction, external AI round trips, automatic registration, dual-page synchronization or desktop project compatibility. It uses browser decoding and encoding, so do not assume desktop byte parity. A reloaded page discards in-memory work. No sample images or user data are included.

## Run locally

From repository root: `python -m http.server 8000 --directory docs`, then open `http://localhost:8000`. Test core algorithms: `node docs/core.test.mjs`. The browser must support ES modules, Canvas, createImageBitmap and pointer events.

## GitHub Pages

In Settings → Pages select Deploy from a branch, branch main and folder /docs after merging this change. Only the static docs directory is intended to be hosted. Verify that the published URL loads before advertising it. No additional server or API keys are required.

## Publishing checklist

Only commit source, documentation and synthetic numerical tests. Never commit actual input/output images, projects, personal filenames, credentials, environment paths, browser data or logs. No third-party CDN is needed. Browser UI and actual hosted deployment must be tested separately; passing the core tests is not a claim of complete browser validation.
