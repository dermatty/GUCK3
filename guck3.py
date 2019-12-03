#!/home/stephan/.virtualenvs/g3/bin/python

import guck3.__main__
import os, time
import datetime

__version__ = "3.0 dev"
os.environ["GUCK3_VERSION"] = __version__

exitcode = 3
while exitcode == 3:
    exitcode = guck3.__main__.run()
    if exitcode == 3:
        trstr = str(datetime.datetime.now()) + ": RESTART - "
    else:
        trstr = str(datetime.datetime.now()) + ": SHUTDOWN - "
    print(trstr + "GUCK3 exited with return code:", exitcode)
    if exitcode == 3:
        print(trstr + "Restarting GUCK3 ...")
        print()
print(trstr + "Exit GUCK3")
