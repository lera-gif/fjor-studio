# Fonts

`Inter-Bold.ttf` is the subtitle face. It is **not installed system-wide** on this
machine -- `fc-match Inter` falls back to Verdana -- so libass is pointed at this
directory with `fontsdir=`. Without that the subtitles still render, in the wrong
typeface, with no error.

Shipped with the repo on purpose: a font that has to be installed separately is a
font that will be missing on the next machine.
