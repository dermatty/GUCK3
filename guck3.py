#!/home/stephan/.virtualenvs/g3/bin/python

import guck3.__main__
import os
import datetime
import sys
from setproctitle import setproctitle

setproctitle("g3." + os.path.basename(__file__))

__version__ = "3.0 dev"
os.environ["GUCK3_VERSION"] = __version__

try:
    startmode = sys.argv[1]
except Exception:
    startmode = "systemd"
if startmode not in ["dev", "systemd"]:
    startmode = "dev"

exitcode = 3
while exitcode == 3:
    exitcode = guck3.__main__.run(startmode=startmode)
    if exitcode == 3:
        trstr = str(datetime.datetime.now()) + ": RESTART - "
    else:
        trstr = str(datetime.datetime.now()) + ": SHUTDOWN - "
    print(trstr + "GUCK3 exited with return code:", exitcode)
    if exitcode == 3:
        print(trstr + "Restarting GUCK3 ...")
        print()
print(trstr + "Exit GUCK3")
