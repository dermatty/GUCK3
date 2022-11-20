import cv2
from setproctitle import setproctitle
from guck3 import mplogging
import os
import time
import signal
import numpy as np
import sys
import inspect
from threading import Thread
import threading
import time
import queue

CNAME = None
CVMAJOR = "4"

def whoami():
    outer_func_name = str(inspect.getouterframes(inspect.currentframe())[1].function)
    outer_func_linenr = str(inspect.currentframe().f_back.f_lineno)
    return outer_func_name + " " + CNAME + " / #" + outer_func_linenr + ": "


def auto_canny(image, sigma=0.33):
    v = np.median(image)
    lower = int(max(0, (1.0 - sigma) * v))
    upper = int(min(255, (1.0 + sigma) * v))
    edged = cv2.Canny(image, lower, upper)
    return edged


def overlap_rects(r1, r2):
    x11, y11, w, h = r1
    x12 = x11 + w
    y12 = y11 + h
    area1 = w * h
    x21, y21, w, h = r2
    x22 = x21 + w
    y22 = y21 + h
    area2 = w * h
    x_overlap = max(0, min(x12, x22) - max(x11, x21))
    y_overlap = max(0, min(y12, y22) - max(y11, y21))
    overlapArea = x_overlap * y_overlap
    return overlapArea, overlapArea/area1, overlapArea/area2


class SigHandler_mpcam:
    def __init__(self, event_stopped, logger):
        self.logger = logger
        self.event_stopped = event_stopped

    def sighandler_mpcam(self, a, b):
        print("GAGA")
        self.event_stopped.set()
        self.logger.debug(whoami() + "set event_stopped = True")

class Detection:
    def __init__(self, id, frame, t, rect, descr, cd, ca):
        self.id = id
        self.rect = rect
        self.class_detection = cd
        self.class_detection_lt = t
        self.class_ai = ca
        self.class_ai_lt = 0
        self.frame = frame
        self.t = t
        self.descrkp = None
        self.descrdes = None
        self.descriptor = descr
        self.calcHog_descr()

    def calcHog_descr(self):
        x, y, w, h = self.rect
        self.descrkp, self.descrdes = self.descriptor.detectAndCompute(self.frame[y:y+h, x:x+w], None)
        return


class NewMatcherThread(Thread):
    def __init__(self, cfg, logger):
        Thread.__init__(self)
        self.lock = threading.Lock()
        self.logger = logger
        self.SURL = cfg["stream_url"]
        self.NAME = cfg["name"]
        self.YMAX0 = self.XMAX0 = None
        self.MINAREA = cfg["min_area_rect"]
        self.CAP = None
        self.MOG2SENS = cfg["mog2_sensitivity"]
        self.HIST = 800 + (5 - self.MOG2SENS) * 199
        self.KERNEL2 = cv2.getStructuringElement(cv2.MORPH_RECT, (24, 24))
        self.NIGHTMODE = False
        self.setFGBGMOG2()
        self.running = False
        self.startup = True
        self.ret = False
        self.frame = None
        self.queue = queue.Queue()

    def OpenVideoCapture(self):
        ret = False
        self.startup = True
        self.CAP = None
        for i in range(10):
            if not self.CAP:
               try:
                  self.CAP = cv2.VideoCapture(self.SURL, cv2.CAP_FFMPEG)
                  self.YMAX0, self.XMAX0 = frame.shape[:2]
               except:
                  pass
            if self.CAP.isOpened():
                ret = True
                break
            time.sleep(0.1)
        self.startup = False
        return ret


    def run(self):
        ret = self.OpenVideoCapture()
        self.running = True
        if not ret:
            self.CAP = None
            self.running = False
        while self.running:
            if not self.startup:
                try:
                    with self.lock:
                        ret, frame = self.CAP.read()
                    if ret:
                        self.queue.put(frame)
                except Exception as e:
                    self.logger.error(whoami() + "Cannot grab frame for " + self.NAME + ": " + str(e))
                    ret = False
                if not ret:
                    self.running = False
                                        
    def stop(self):
        self.running = False
        self.startup = True
        with self.lock:
            if self.CAP:
                self.CAP.release()    

    def setFGBGMOG2(self):
        ms = self.MOG2SENS
        if not self.NIGHTMODE:
            hist = int(800 + (5 - ms) * 100)
            vart = int(1500 + (5 - ms) * 250)
        else:
            hist = int(500 + (5 - ms) * 70)
            vart = int(400 + (5 - ms) * 60)
        self.logger.debug(whoami() + "Creating BackgroundSubtractorKNN(history=" + str(hist) + ", dist2Threshold=" + str(vart) + ", detectShadows=True)")
        self.FGBG = cv2.createBackgroundSubtractorKNN(history=hist, dist2Threshold=vart, detectShadows=True)
        return


    def get_caption_and_process(self):
        frame = None
        ret = False
        while True and self.running:
            try:
                frame = self.queue.get_nowait()
                ret = True
            except queue.Empty:
                if ret:
                    break
            time.sleep(0.01)

        if not ret:
            return False, None, None, time.time()
        try:
           gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
           fggray = self.FGBG.apply(gray, 1 / self.HIST)
           fggray = cv2.medianBlur(fggray, 5)
           edged = auto_canny(fggray)
           closed = cv2.morphologyEx(edged, cv2.MORPH_CLOSE, self.KERNEL2)
           if CVMAJOR == "4":
              cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
           else:
              _, cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
           cnts0 = [cv2.boundingRect(c) for c in cnts]
           rects = [(x, y, w, h) for x, y, w, h in cnts0 if w * h > self.MINAREA]
           return ret, rects, frame, time.time()
        except Exception:
           return False, None, None, time.time()
        
def run_cam(cfg, child_pipe, mp_loggerqueue):
    global CNAME
    global CVMAJOR

    cv2.setNumThreads(1)

    CVMAJOR = cv2.__version__.split(".")[0]
    CNAME = cfg["name"]

    setproctitle("g3." + cfg["name"] + "_" + os.path.basename(__file__))

    logger = mplogging.setup_logger(mp_loggerqueue, __file__)
    logger.info(whoami() + "starting ...")

    event_stopped = threading.Event()
    sh = SigHandler_mpcam(event_stopped, logger)
    signal.signal(signal.SIGINT, sh.sighandler_mpcam)
    signal.signal(signal.SIGTERM, sh.sighandler_mpcam)

    tm = NewMatcherThread(cfg, logger)
    tm.start()
    while tm.startup:
        time.sleep(0.03)
    child_pipe.recv()
    child_pipe.send((tm.running, tm.YMAX0, tm.XMAX0))
    if not tm.running:
        logger.error(whoami() + "cam is not working, aborting ...")
        sys.exit()

    waitnext = 0.005
    oldt = time.time()
    MAXFPS = 8

    while not event_stopped.is_set():
        try:
            cmd = child_pipe.recv()
            if cmd == "stop":
                child_pipe.send(("stopped!", None))
                break
            if cmd == "query":
                ret, rects, frame, t0 = tm.get_caption_and_process()
                if ret:
                    exp0 = (ret, frame, rects, t0)
                    child_pipe.send(exp0)
                    fps = 1 / (t0 - oldt)
                    if fps > MAXFPS:
                        waitnext += 0.005
                    elif fps < MAXFPS and waitnext > 0.005:
                        waitnext -= 0.005
                    oldt = t0
                    time.sleep(waitnext)
                    # print(fps, waitnext)
                else:
                    logger.error(whoami() + "Couldn't capture frame in main loop!")
                    exp0 = (ret, None, [], None)
                    child_pipe.send(exp0)
                    continue
        except Exception as e:
            logger.error(whoami() + str(e))
            exp0 = (False, None, [], None)
            child_pipe.send(exp0)

    tm.stop()
    tm.join()

    logger.info(whoami() + tm.NAME + " exited!")
