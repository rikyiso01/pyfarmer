#!/usr/bin/env python3
from subprocess import run
from sys import argv

# flush=

exit(run(["/usr/bin/env", "python3", "{}", argv[1]]).returncode)
