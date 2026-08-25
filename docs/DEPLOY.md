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
| `assets/music bed/` | Optional. The editor's bed list is empty until `.mp3` files are dropped in. |
| `assets/demos/` | Optional. Only used by jobs that ask for a demo insert. |

Neither stops a job. Copy them across from an existing studio if the team wants
the same library.

---

## 2. Configure it

```bash
cp config/auth.yaml.example config/auth.yaml   # then fill in the keys
export FJOR_STUDIO_HOME=/srv/fjor-studio       # where jobs/ and config/ live
export FJOR_STUDIO_DELIVERY_ROOT=/mnt/creative/VIDEO
```

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
