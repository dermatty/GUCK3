import cv2
from setproctitle import setproctitle
from guck3.mplogging import whoami
from guck3 import mplogging
import os
import time


class Matcher:
    def __init__(self, cfg):
        self.SURL = cfg["stream_url"]
        self.NAME = cfg["name"]
        self.CAP = None
        self.YMAX0 = -1
        self.XMAX0 = -1

    def waitforcaption(self):
        ret = False
        for i in range(10):
            self.CAP = cv2.VideoCapture(self.SURL)
            ret, frame = self.CAP.read()
            if ret:
                self.YMAX0, self.XMAX0 = frame.shape[:2]
                break
            time.sleep(0.1)
        return ret

    def get_caption_and_process(self):
        if not self.CAP:
            self.CAP = cv2.VideoCapture(self.SURL)
        return self.CAP.read()


def run_cam(cfg, child_pipe, mp_loggerqueue):
    setproctitle("g3." + cfg["name"] + "_" + os.path.basename(__file__))

    logger = mplogging.setup_logger(mp_loggerqueue, __file__)
    logger.info(whoami() + "starting ...")

    tm = Matcher(cfg)

    # cam_is_ok = tm.waitforcaption()

    terminated = False

    while not terminated:
        cmd = child_pipe.recv()
        if cmd == "stop":
            child_pipe.send(("stopped!", None))
            break
        if cmd == "query":
            ret, frame = tm.get_caption_and_process()
            child_pipe.send((ret, frame))

    if tm.CAP:
        tm.CAP.release()

    logger.info(whoami() + "... exited!")


