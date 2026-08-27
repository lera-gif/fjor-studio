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

### The bed library

`music bed/` is filed by mood, one level deep, and a bed's name carries its
folder: `Calm/Kyoto Stillness`. A bare name still resolves, so jobs recorded
before the library was filed keep their music when they are re-cut.

`_to_delete/` is out of circulation and invisible to the picker — it holds
commercial masters that were in the library by accident. A recognisable
record in a Meta ad gets the video muted or claimed, so they are kept out of
reach rather than left one click away in a dropdown.

The rest of `Stock library/` is the YouTube Audio Library roster. "Free" there
means free ON YOUTUBE: several tracks want attribution and the licence does not
automatically cover a paid placement. Check before shipping one. Everything
under the other folders is Suno-generated and therefore yours.

`music bed/` and `demos/` are not — 35M of optional media. A checkout without
them works; the editor's bed list is simply empty until files are dropped in.
Any `.mp3` in `music bed/` and any `.mp4` in `demos/` is picked up by name.
