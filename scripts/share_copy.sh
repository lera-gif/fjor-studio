#!/bin/bash
# Update the shareable copy of this studio from the current commit.
#
# The copy is this repo minus the things that are true only here: the delivery
# root, and an audit of one machine's week folders. It keeps its own git history
# so it can be pushed and pulled normally -- this script adds a commit to it, it
# does not re-initialise it.
#
# Run it after committing here. It refuses a dirty tree, because a copy built
# from uncommitted work is a copy nobody can trace back.
set -euo pipefail

cd "$(dirname "$0")/.."
SRC="$PWD"
DST="${1:-$(cd .. && pwd)/fjor-studio-share}"

if [ -n "$(git status --porcelain)" ]; then
  echo "refusing: this repo has uncommitted changes. Commit them first, so the"
  echo "copy corresponds to a commit that exists." >&2
  exit 1
fi

REV="$(git rev-parse --short HEAD)"
SUBJECT="$(git log -1 --format=%s)"

if [ ! -d "$DST/.git" ]; then
  echo "creating $DST"
  mkdir -p "$DST"
  git -C "$DST" init -q
fi

# everything except the copy's own history, so a file deleted here is deleted
# there -- `git add -A` at the end then records the removal
find "$DST" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
git archive HEAD | tar -x -C "$DST"

python3 - "$DST" <<'PY'
import pathlib, sys
dst = pathlib.Path(sys.argv[1])

# 1. no delivery root: whoever deploys it sets their own, and intake refuses
#    every job until they do
p = dst / "config" / "delivery.yaml"
s = p.read_text()
import re
new = re.sub(r'^root: ".*"$',
             '# e.g. "/mnt/creative/VIDEO", or "~/Desktop/FJOR CREATIVE FACTORY/VIDEO".\n'
             '# Left empty on purpose: intake refuses every job until this is set, which is\n'
             '# better than a run being paid for and delivered somewhere nobody looks.\n'
             'root: ""', s, count=1, flags=re.M)
assert new != s, "delivery.yaml: no root line to blank -- has the format changed?"
p.write_text(new)

# 2. the pixel-format audit is an inventory of one machine's delivery tree
audit = dst / "docs" / "PIXFMT_AUDIT.md"
if audit.exists():
    audit.unlink()

# 3. say plainly that nothing is configured yet
p = dst / "README.md"
s = p.read_text()
title = "# fjor-studio\n"
assert s.startswith(title), "README.md: unexpected first line"
p.write_text("""# fjor-studio

> **First run on a new machine?** Read [`docs/DEPLOY.md`](docs/DEPLOY.md) first.
> Nothing is configured out of the box: there is no delivery root and no keys,
> and the studio refuses to start a job rather than guess either.
""" + s[len(title):])
PY

# The music beds, which git does not carry and should not: 435 MB of mp3 would
# sit in every clone of both repositories forever, and git stores audio no more
# cleverly than a copy does. They ride along as FILES -- the share copy's own
# .gitignore (which travels with it) leaves them untracked, so they reach the
# team in the folder and in any zip of it without entering either history.
#
# `_to_delete` NEVER travels. It holds commercial recordings -- One Direction,
# Carly Rae Jepsen, Glass Animals, Hans Zimmer -- quarantined out of the picker
# because they must not be used, and redistributing them to a team would be a
# different and worse problem than using them. The exclusion is enforced below
# rather than trusted.
BEDS="assets/music bed"
if [ -d "$SRC/$BEDS" ]; then
  mkdir -p "$DST/$BEDS"
  rsync -a --delete --exclude "_to_delete" --exclude ".DS_Store"         "$SRC/$BEDS/" "$DST/$BEDS/"
  if [ -e "$DST/$BEDS/_to_delete" ]; then
    echo "refusing: the quarantined tracks reached the share copy" >&2
    exit 1
  fi
  echo "music beds: $(find "$DST/$BEDS" -type f | wc -l | tr -d ' ') files, $(du -sh "$DST/$BEDS" | cut -f1) (quarantine excluded)"
fi

# The check that matters: no home directory survived the transforms. The needle
# is assembled rather than written out, or this line matches its own guard --
# which is exactly what happened the first time it ran.
NEEDLE="$(printf '/%s/|/%s/' Users home)"
if grep -rElI --exclude-dir=.git --exclude-dir=.venv \
     --exclude-dir="music bed" "$NEEDLE" "$DST" \
     | grep -v "config/delivery.yaml" | grep . ; then
  echo "refusing: the files above still carry an absolute home path" >&2
  exit 1
fi

cd "$DST"
git add -A
if git diff --cached --quiet; then
  echo "already up to date with $REV"
  exit 0
fi
git -c user.name="FJOR" -c user.email="lera@fjor.health" \
    commit -q -m "Update from fjor-studio $REV

$SUBJECT"
echo "committed to $DST:"
git log --oneline -1
