# Deploying fjor-studio

Everything here is per-machine. Nothing in the repo points at anyone's home
directory: the two paths that differ come from config or the environment, and
the studio refuses to start a job rather than guess either.

---

## 1. What it needs

| | |
|---|---|
| **Python** | 3.9 or newer. Only `pyyaml` is required to run; `pytest` to test. |
| **ffmpeg** | With **libass**, or subtitles cannot be burned. See below. |
| **A delivery root** | The folder that holds the vertical folders. |
| **Keys** | `config/auth.yaml`, from `config/auth.yaml.example`. |

```bash
python3 -m venv .venv && ./.venv/bin/pip install pyyaml pytest
```

### ffmpeg, and the libass trap

Assembly needs plain `ffmpeg`; burning subtitles needs one built with libass.
On most Linux distributions the packaged build has it and there is nothing to
think about:

```bash
sudo apt install ffmpeg
```

On macOS, Homebrew's `ffmpeg` formula **does not** include libass, and the
build that does is installed alongside it, keg-only, off `PATH`:

```bash
brew install ffmpeg ffmpeg-full
```

The studio searches `PATH`, then the usual install locations, and picks the
first binary that reports `--enable-libass`. To point it at a specific one:

```bash
export FJOR_STUDIO_FFMPEG=/opt/ffmpeg/bin/ffmpeg
```

If none is found, intake fails with that message — before anything is bought,
never in the middle of a paid run. Turning `subtitles.enabled: false` off in
`config/pipeline.yaml` is the other way out.

### What the repo does not carry

The approved disclaimer overlays and the packshot are tracked, because assembly
cannot produce a deliverable cut without them. Two things are not:

| | |
|---|---|
| `assets/music bed/` | **Not in git. It travels with the folder, not with a clone.** `share_copy.sh` copies the beds across as files, so a shared folder or zip has the library even though no commit contains it — 435 MB of mp3 in a repository would sit in every clone forever. A `git clone` from GitHub gets the code and no beds; copy `assets/music bed/` into the clone by hand (minus `_to_delete/`, see below) before expecting the editor to offer any. |
| `assets/demos/` | Optional. Only used by jobs that ask for a demo insert. |

Neither stops a job: with no beds the editor's list is simply empty.

**`assets/music bed/_to_delete/` never travels.** It holds commercial
recordings kept out of the picker because they must not be used, and
`share_copy.sh` both excludes it and then refuses to finish if a copy of it
turns up anyway. If you move beds between machines by hand, exclude that folder
yourself — the picker skips it by NAME, so renaming it puts the tracks back into
circulation.

### Keeping a shared copy up to date

`scripts/share_copy.sh` rebuilds the shareable copy from the current commit:
the whole repo minus the delivery root and the internal audit, with a banner on
the README. It adds a commit to that copy rather than re-initialising it, so it
can be pushed and pulled normally, and it refuses to run against a dirty tree or
to leave an absolute home path behind.

```bash
./scripts/share_copy.sh [path]        # default: ../fjor-studio-share
```

---

## 2. Configure it

```bash
# Keys: prefer a KIT — see "Keys" below. auth.yaml still works:
cp config/auth.yaml.example config/auth.yaml   # then fill in the keys
export FJOR_STUDIO_HOME=/srv/fjor-studio       # where jobs/ and config/ live
export FJOR_STUDIO_DELIVERY_ROOT=/mnt/creative/VIDEO
```

**The easiest way is the dashboard.** Start it, and a bar at the top says there
is no delivery folder yet and offers to set one. The dialog takes the root and
the week-folder pattern, and previews exactly where a final will land as you
type — change `{week} week` to `w{week}` or `Week {week}` if your weeks are
named differently. It edits the `root:` line of `config/delivery.yaml` and
leaves the rest of the file, comments included, alone.

`FJOR_STUDIO_DELIVERY_ROOT` overrides `root:` in `config/delivery.yaml`, so one
checkout serves several machines without editing a tracked file. Set one or the
other: with neither, **intake refuses every job**. That is deliberate — delivery
runs after everything has been paid for, so a plausible-looking default would
scatter finished work somewhere nobody looks.

Check what resolved, with the keys masked:

```bash
./.venv/bin/python -m fjor_studio.cli config
```

### Walk it end to end for nothing

The mock backend runs the whole pipeline — every gate, every review file, every
forecast — for zero credits, and is deterministic. Do this first, on any new
deployment:

```bash
FJOR_STUDIO_BACKEND=mock ./.venv/bin/python -m fjor_studio.cli \
  new menopause_yoga ref.mp4 --week 34 --concept ugc --scenes 3 --run
```

```bash
./.venv/bin/python -m pytest -q
```

The suite executes the pipeline rather than reading source, so a green run on a
new machine means ffmpeg, the fonts and the assets are all genuinely working.

---

## 2a. Keys

**Preferred: a kit.** A kit is a JSON file of API keys that a producer supplies
at runtime. The studio reads it, holds it in the memory of one process, and
never writes it anywhere — restart and the keys are gone with it.

```bash
# for one command
./.venv/bin/python -m fjor_studio.cli --kit ~/keys/fjor_kit.json status LIPIL025
# for a whole shell, including the dashboard
export FJOR_STUDIO_KIT=~/keys/fjor_kit.json
```

On the dashboard, a bar at the top of the sidebar says which providers answered.
With no keys it says so and offers **Load a kit…**; the file is read straight
into the process and never touches the disk. The page is only ever told the
provider NAMES — a key that never reaches the browser cannot be copied out of it.

Two shapes are accepted:

```json
{ "kie": { "api_key": "…", "base_url": "https://api.kie.ai" },
  "gemini": "…" }
```

…and the colleague's own `📤 Экспорт настроек` **settings-kit** export, read
unchanged, so the file the team already passes around works as-is. Only its keys
are read; its style library and settings are ignored, because a kit is
credentials, not configuration.

**Legacy: `config/auth.yaml`.** Still supported and still gitignored, and a kit
overrides it. It is no longer what a new deployment is told to do: a file of
live keys sitting in the working tree is a standing invitation — to a stray
`git add -f`, to a backup, to a screen share, to a traceback that interpolates
the wrong object. This studio printed all six of its keys that last way on
2026-09-02. A key that is not on the disk cannot be printed off it.

---

## 2b. What it can make

Four things beyond a straight UGC re-creation. All of them are chosen at
**intake**, in the New-job dialog or on `cli new`, because each changes what the
job buys and none can be added cheaply later.

### The source decides the pipeline

Drop a **video** and it is a reference: analysed, planned, re-created. Drop an
**image** and it is a client banner: expanded to 9:16 without being altered,
animated with micro-motion, and cut with the usual overlays. The dialog says
which pipeline it is about to run, and for a banner how many pixels it will
paint above and below, before anything is created. A job carrying both is
refused at intake.

Banner mode skips analysis, cast and voice entirely, and its clips are silent —
so subtitles are off, because burning them would cover the client's own approved
copy. The banner itself is held to **zero changed pixels**: it is composited
back over the model's output, and then checked. The one licensed edit is the
legal small print, which runs as its own pass over a named band.

### Reference kind: UGC or replica

For a video reference, `--ref-kind replica` (or the dropdown) means *reproduce
this reference's own look* rather than re-create its idea. It asks the analysis
about the material and finish, tells the writer to name the medium first, and —
the part that actually works — **cuts three stills out of the reference and
attaches them to every plate**, ranked above the prompt.

That last part exists because words were not enough. A stylised 3D cartoon
reference whose every prompt said "3D cartoon animation style" still came back
photoreal and uncanny. A look is carried by a picture, the same way a face is.

### Motion drivers

A driver is a slice of someone else's video: its movement, timing and camera are
transferred onto our photograph. Attach one at **GATE_PLAN** — the dashboard has
a dialog there — because a driven shot's plate IS the driver's opening frame, so
attaching later means re-buying it.

Choosing **Kling Motion Control** overwrites the shot's length with the driver's
and generates it silent; our line is spoken separately and laid over. Choosing
**Seedance** keeps the planned 4–15s and the shot may speak.

### Transformation, and a text card

`--morph "what changes"` builds the creative around one shot where a person
changes on camera with no cut: two plates are bought for that shot and the video
model morphs between them. Both plates are shown side by side at the gate.

`--text-card "our words"` sets our copy the way the reference sets its own —
the manner is copied, the words are ours. It also asks the analysis about
typography.

### When a job stops

Preflight will not deliver over a critical clip verdict. The job goes **back to
GATE_DRAFT**, not to `failed`, and both routes out are on the page:

- **Buy it again.** `revise <id> clip --scene N` re-buys the animation;
  `revise <id> plates --scene N` re-buys the still first. Use *plates* when the
  fault is already in the photograph — the video model can only animate what it
  is given, so re-buying the clip reproduces the same fault at five times the
  price.
- **Accept and ship.** `waive <id> --scene N --note why`. The verdict is kept,
  not deleted: preflight still reports the check as failed and the finding
  travels into the delivered manifest.

---

## 3. Serving the dashboard

**Read this part.** The dashboard has no user accounts, no login, and no
per-action confirmation beyond its own dialogs. Every gate it displays can be
approved, and approving one spends real credits — GATE_PLATES on the first
production creative committed 843 credits in a single click. Its media routes
also serve unreleased client work.

**On one person's machine**, nothing has changed and nothing is required:

```bash
./scripts/dashboard.sh --port 8422        # 127.0.0.1 only
```

**Anywhere else**, a token is mandatory. `serve()` refuses to bind to a
non-loopback address without one, rather than silently publishing a spend
button:

```bash
export FJOR_STUDIO_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
./.venv/bin/python -m fjor_studio.cli dashboard --host 0.0.0.0 --port 8422
```

The token may also live in `config/auth.yaml` as `dashboard.token`; the
environment variable wins. It is masked by `cli config` like every other secret.

People get in by opening the printed link once — `http://host:8422/?token=…`.
That is exchanged for an `HttpOnly`, `SameSite=Strict` cookie and redirected
immediately, so the token stops travelling in URLs. Scripts can send it as an
`X-Studio-Token` header instead.

A shared token is a low bar, and it is deliberately a low bar: it stops an
accidental exposure, not a determined one. For anything beyond a trusted
internal network, **put a reverse proxy with real authentication and TLS in
front of it** and keep the studio itself bound to `127.0.0.1`. The token travels
in plain HTTP otherwise, and so does everything it protects.

### Running it as a service

The dashboard runs in the foreground and stops when its process does. A minimal
unit:

```ini
[Unit]
Description=FJOR Studio dashboard
After=network.target

[Service]
WorkingDirectory=/srv/fjor-studio
Environment=FJOR_STUDIO_HOME=/srv/fjor-studio
Environment=FJOR_STUDIO_DELIVERY_ROOT=/mnt/creative/VIDEO
EnvironmentFile=/etc/fjor-studio.env
ExecStart=/srv/fjor-studio/.venv/bin/python -m fjor_studio.cli dashboard --host 127.0.0.1 --port 8422
Restart=on-failure
User=fjor

[Install]
WantedBy=multi-user.target
```

Put `FJOR_STUDIO_TOKEN=…` in `/etc/fjor-studio.env`, readable only by that user,
rather than in the unit file where `systemctl show` will print it.

One worker runs one job at a time, by design — jobs do not overlap, and two
processes pointed at the same `jobs/` directory would fight over `job.json`. Run
**one** instance per studio home.

`FJOR Studio.command` is the macOS double-click launcher. It is harmless
elsewhere and does nothing useful there.

---

## 4. What must be backed up

| | |
|---|---|
| `jobs/<ID>/job.json` | The single source of truth for a run: state, ledger, spend. |
| `jobs/<ID>/` | Plates, clips, drafts, the reference. Re-buying these costs money. |
| `config/auth.yaml` | The keys. Never committed; not in this repo. |
| The delivery root | The finals themselves. |

`jobs/` and `config/auth.yaml` are gitignored and always will be. A crash mid-run
is recoverable — `run <id>` resumes from the last completed stage, and `retry
<id>` restarts a failed one — but only if `jobs/` survived.

---

## 5. Before the first paid run

- [ ] `pytest -q` is green on the target machine.
- [ ] `cli config` shows the delivery root you expect, and masked keys.
- [ ] A mock job has walked all four gates and delivered into a scratch root.
- [ ] The delivery root is the real tree, and its volume is mounted at boot.
- [ ] The dashboard is either loopback-only or behind a token **and** TLS.
- [ ] Someone other than the person who deployed it can find `jobs/` in the
      backup.
