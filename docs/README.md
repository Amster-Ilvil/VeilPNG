# VeilPNG Web — local redaction preview

This independent static web workspace processes PNG and JPEG files in the browser. It supports a multi-image queue, inclusive rectangular masks, freehand brush and eraser, undo/redo, black/white opaque redaction, PNG export and a stored ZIP of marked pages. Output names are generic numbered names. Transparent source areas are flattened onto white. Unmarked or empty masks are not exported. There are no accounts, analytics, remote scripts, network APIs, uploads or default persistent browser storage. A restrictive CSP blocks network requests by the application. The hosting provider may still record ordinary page visits; browser extensions and the operating system are outside the application's control.

This is a preview, not desktop/CLI parity. It does not implement encrypted containers, hidden-layer reconstruction, non-rigid registration, full desktop synchronization or desktop project compatibility. It uses browser decoding and encoding, so do not assume desktop byte parity. A reloaded page discards in-memory work unless an explicit local backup was enabled or the project record was saved. No sample images or user data are included.

## Run locally

From repository root: `python -m http.server 8000 --directory docs`, then open `http://localhost:8000`. Test core algorithms: `node docs/core.test.mjs`. The browser must support ES modules, Canvas, createImageBitmap and pointer events.

## GitHub Pages

In Settings → Pages select Deploy from a branch, branch main and folder /docs after merging this change. Only the static docs directory is intended to be hosted. Verify that the published URL loads before advertising it. No additional server or API keys are required.

## Publishing checklist

Only commit source, documentation and synthetic numerical tests. Never commit actual input/output images, projects, personal filenames, credentials, environment paths, browser data or logs. No third-party CDN is needed. Browser UI and actual hosted deployment must be tested separately; passing the core tests is not a claim of complete browser validation.

## Local AI return workflow
1. Import the original locally, mark protected regions, and save the local mask JSON.
2. Export the public-only PNG. Keep the original and JSON private.
3. After an authorized external edit, import the returned PNG/JPEG in the same workspace. After reopening, import the exact original first, then its local mask record.
4. The record checks SHA-256 and source dimensions. Returned images with different dimensions can be similarity-registered locally; uncertain matches and detected cropping are rejected.
5. Preview the restored image and export an ordinary PNG: protected pixels come from the original, all other pixels from the returned image (both flattened on white).
6. Pair each returned file with its selected original page and check the two-pane comparison. The review checkbox is required for export. Switching pages preserves the pairing in memory and recreates the preview; mask or shade changes invalidate it. Export the current approved PNG or a ZIP containing only approved pages. No image or record is uploaded by VeilPNG Web.
The JSON is sensitive local selection metadata, not encrypted storage or the desktop project format. Use the desktop A1/A2 workflows for encrypted containers. Test: `node docs/return-core.test.mjs`.

## Multi-page return review
Queue indicators: ○ unmarked, ● marked, ◐ paired but unreviewed, ✓ reviewed. Pairing is manual: equal dimensions are not proof of registration. The return-file queue is limited to 80 MB, the restored ZIP to 128 MB, and output names are generic numbered PNGs. The two comparison panes share zoom and scroll positions. Test queue state with `node docs/pairing.test.mjs`. Refresh discards paired files and reviews.

## Web 0.3.0
Top-level workflow buttons import originals, export public PNGs, import external returned files locally, and export approved pages. Chinese/Japanese are local queue labels; users may copy masks after automatic similarity registration and manual review. Review the target after copying. Batch return import accepts exact numbered names like 0001_redacted.png or 0001_returned.jpg; arbitrary names require manual pairing. Matching by number is not automatic image registration; approval remains mandatory.
Save a whole-project JSON and retain all original files; reload originals and open the JSON to match hashes and restore order, language labels and masks. Optional browser IndexedDB checkpoint stores original files and masks unencrypted on the current origin, only after explicit opt-in; use private devices only. Resume manually after refresh, or delete the checkpoint. Return files and approvals are not saved. A browser backup may be lost if storage is cleared or evicted; the portable JSON and original files are the durable backup. Do not send project records or originals to external services. Run `node docs/project.test.mjs` for synthetic project tests.

## Web 0.4.0 registration
Select the original source page and target page, click automatic registration, inspect the cyan/magenta overlay, then transfer the selected region and review the target. Uses local grayscale corner features, normalized patch matching and robust similarity fitting (scale, rotation and translation). It is not a projective or nonrigid warp; curved pages or low-confidence matches require separate selection. Rectangle mapping uses a bounding box; brush/eraser transfer is approximate and must be reviewed. The transformed selections are saved by the existing project record; registration itself can be recalculated. Differently sized returned files are registered against the public preview and warped to original dimensions; cropped or low-confidence results are rejected. Same-size returns continue to use original coordinates and require manual review. All image processing stays local.

## Web 0.5.0
Return images are matched against the local public preview even at equal dimensions. Native return dimensions are retained, with only the projected mask replaced. Whole-page corner cropping is no longer a rejection by itself; a clipped protected pixel is rejected. Global similarity alignment is still approximate; the user must inspect each restored region. Batch return import matches image content regardless of name; select the source language group when multiple editions are similar. Ambiguous matches fail closed. Existing original files plus solid rectangular redacted PNGs (or flat PNG ZIPs, stored/deflated, CRC checked) can reconstruct masks locally. Difference-based reconstruction is not a substitute for a verified project record: original solid pixels can be ambiguous, brush masks and non-rectangular/mixed-color masks may be rejected. Review each reconstructed region and save a separate project JSON; never include private metadata or originals in the public ZIP. Browser backups retain their existing opt-in policy. No network processing.

## Web 0.6.0 simplified workspace
The top bar separates Chinese/Japanese import, public export, and local returned-image review. Advanced tools remain accessible under expandable sections. Same-page candidate search uses the existing registration and ambiguity check; no mask is transferred until the user reviews the overlay and explicitly confirms. The batch public export requests a separate private project JSON download if the current revision has not already requested a save; the public ZIP contains only redacted PNGs. Browser multiple-download permissions may require allowing or manually saving the private JSON; verify both files. No automatic upload to any external service. The guided review button confirms only the visible page and navigates to the next unreviewed pair. Existing opt-in browser backups and old PNG/ZIP mask reconstruction remain available. This release does not add nonrigid registration or guarantee correct geometry for distorted pages.
