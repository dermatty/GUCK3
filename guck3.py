#!/home/stephan/.virtualenvs/g3/bin/python

import guck3.__main__
import os

__version__ = "3.0 dev"
os.environ["GUCK3_VERSION"] = __version__

exitcode = guck3.__main__.run()
print("guck3 exited with return code:", exitcode)
