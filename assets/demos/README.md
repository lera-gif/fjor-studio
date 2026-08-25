# Product demo sequences

Drop a clip in here and it becomes selectable per job — dashboard "Product demo"
dropdown, or `fjor-video new --demo <name>`. It is stitched into the body of the
creative **immediately before the CTA packshot**.

- `mp4 / mov / m4v / webm`, or a still (`png / jpg`), which holds for 4 s.
- The option is named after the file stem: `app_tour.mp4` → `app_tour`.
- For a dedicated 4:5 cut, add a `_45` twin (`app_tour_916.mp4` + `app_tour_45.mp4`);
  without one, the 4:5 export is centre-cropped from the 9:16, as CTA cards are.
- The demo's length is added to the runtime, so preflight's survivor runtime band
  (total ≤20 s, or 30-60 s) is measured WITH it. Trim the demo (`--demo-s`, or
  "Demo trim s" on the dashboard) or shorten `--chrono` to make room.

`Comp 1.mp4` is 12.0 s, which at full length puts every ordinary chrono in the
20-30 s dead zone (10 + 12 + 3 = 25 s). Either trim it — 5 s gives 10 + 5 + 3 =
18 s — or run a longer montage: chrono 15 lands at 30 s, the bottom of the upper
band. Its own audio track is dropped; the music bed plays across it, as for
video CTA cards.
