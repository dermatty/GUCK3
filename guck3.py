#!/home/stephan/.virtualenvs/g3/bin/python

import guck.__main__

exitcode = guck.__main__.run()
print("guck exited with return code:", exitcode)

