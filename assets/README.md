# Asset library

Drop a file in a folder and it becomes selectable. Nothing here is generated.

- **packshots/** — the product shot that closes the ad. `<name>_916.mp4` plus an
  optional `<name>_45.mp4` twin; without the twin the 4:5 export is centre-cropped
  from the 9:16. Selected with `--packshot <name>` (the stem before `_916`).
- **demos/** — a product-demo sequence stitched in immediately before the packshot.
- **music bed/** — background music.
- **disclaimers/** — the approved burnt-in overlays, 1080x1920 and 1080x1350
  transparent PNGs. `disclaimer*` runs the whole length; `cwaDisclaimer*`
  ("Created with AI") covers the first three seconds only.

Copied from fjor-video 2026-08-18; the disclaimer PNGs came from the VIDEOTOOL
kit export and carry the text in config/standards.yaml verbatim. **They are
approved compliance assets — do not regenerate or re-typeset them.**

## What is in the repo, and what is not

`disclaimers/` and `packshots/` are tracked: assembly cannot produce a
deliverable cut without them, and together they are under a megabyte.

`music bed/` and `demos/` are not — 35M of optional media. A checkout without
them works; the editor's bed list is simply empty until files are dropped in.
Any `.mp3` in `music bed/` and any `.mp4` in `demos/` is picked up by name.
