#!/bin/bash
# Double-click to stop whatever FJOR Studio is running and start a fresh one.
#
# The same launcher, told not to reuse what is already there. Use it when the
# dashboard is behaving oddly, or after the code changes -- the server reads
# the config on every request but imports the code once, at startup.
cd "$(dirname "$0")"
FJOR_STUDIO_RESTART=1 exec "./FJOR Studio.command"
