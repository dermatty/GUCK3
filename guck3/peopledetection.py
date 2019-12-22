import os
import queue
from setproctitle import setproctitle
from guck3.mplogging import whoami
from guck3 import mplogging, mpcam, clear_all_queues
import time
import cv2
import multiprocessing as mp
import signal
import numpy as np
from keras_retinanet import models
from keras_retinanet.utils.image import read_image_bgr, preprocess_image, resize_image
from keras import backend as K
import sys
import logging
from datetime import datetime
from threading import Thread, Lock
from guck3.g3db import G3DB

# todo:
#    each camera own thread which gets data from camera and does peopledetection


TERMINATED = False


class SigHandler_pd:
    def __init__(self, logger):
        self.logger = logger

    def sighandler_pd(self, a, b):
        self.shutdown()

    def shutdown(self):
        global TERMINATED
        TERMINATED = True
        self.logger.debug(whoami() + "got signal, exiting ...")


class KerasRetinaNet:
    def __init__(self, dirs, db, logger):
        self.logger = logger
        self.active = False
        self.db = db
        self.dirs = dirs
        self.RETINA_PATH = self.dirs["main"] + self.db.get_options()["retinanet_model"]
        old_sys_stdout = sys.stdout
        f = open('/dev/null', 'w')
        sys.stdout = f
        try:
            self.RETINAMODEL = models.load_model(self.RETINA_PATH, backbone_name='resnet50')
            self.active = True
            self.logger.info(whoami() + "RetinaNet initialized!")
        except Exception as e:
            self.logger.error(whoami() + str(e) + ": cannot init RetinaNet!")
        sys.stdout = old_sys_stdout

    def overlap_rects(self, r1, r2):
        x11, y11, x12, y12 = r1
        w = abs(x12 - x11)
        h = abs(y12 - y11)
        area1 = w * h
        x21, y21, x22, y22 = r2
        w = abs(x22 - x21)
        h = abs(y22 - y21)
        area2 = w * h
        x_overlap = max(0, min(x12, x22) - max(x11, x21))
        y_overlap = max(0, min(y12, y22) - max(y11, y21))
        overlapArea = x_overlap * y_overlap
        return overlapArea, overlapArea/area1, overlapArea/area2

    def get_cnn_classification(self, camera):
        if not self.active or not camera.active and camera.frame is not None:
            return
        frame = camera.frame.copy()
        cnn_classified_list = []
        for x, y, w, h in camera.rects:
            found = True
            image = preprocess_image(frame)
            image, scale = resize_image(image)
            pred_boxes, pred_scores, pred_labels = self.RETINAMODEL.predict_on_batch(np.expand_dims(image, axis=0))
            pred_boxes /= scale
            found = False
            for box, score, label in zip(pred_boxes[0], pred_scores[0], pred_labels[0]):
                if label != 0 or score < 0.5:
                    continue
                b = box.astype(int)
                r1 = (b[0], b[1], b[2], b[3])
                r2 = (x, y, x + w, y + h)
                overlapArea, ratio1, ratio2 = self.overlap_rects(r1, r2)
                if (ratio1 > 0.70 or ratio2 > 0.70):
                    self.logger.info(" Human detected with score " + str(score) + " and overlap " + str(ratio1) + " / " + str(ratio2))
                    found = True
                    break
            if found:
                cnn_classified_list.append(r1)
                # cnn_classified_list.append((min(x, b[0]), min(y, b[1]), max(x + w, b[2]), max (y + h, b[3])))
                self.logger.info(whoami() + "!! CLASSIFIED !!")
        camera.cnn_classified_list = cnn_classified_list
        return


class Camera(Thread):
    def __init__(self, ccfg, dirs, mp_loggerqueue, logger):
        Thread.__init__(self)
        self.daemon = True
        self.ccfg = ccfg
        self.parent_pipe, self.child_pipe = mp.Pipe()
        self.mpp = None
        self.outvideo = None
        self.ymax = -1
        self.xmax = -1
        self.dirs = dirs
        self.is_recording = False
        self.recordfile = None
        self.frame = None
        self.oldframe = None
        self.rects = []
        self.tx = None
        self.shutdown_completed = False
        self.running = False
        self.newframe = False
        self.cnn_classified_list = []
        self.fpslist = []
        self.lock = Lock()

        self.logger = logger
        self.mp_loggerqueue = mp_loggerqueue

        try:
            self.isok = True
            self.cname = ccfg["name"]
            self.active = ccfg["active"]
            self.stream_url = ccfg["stream_url"]
            self.photo_url = ccfg["photo_url"]
            self.reboot_url = ccfg["reboot_url"]
            self.ptz_mode = ccfg["ptz_mode"]
            self.ptz_right_url = ccfg["ptz_right_url"]
            self.ptz_left_url = ccfg["ptz_left_url"]
            self.ptz_up_url = ccfg["ptz_up_url"]
            self.ptz_down_url = ccfg["ptz_down_url"]
            self.min_area_rect = ccfg["min_area_rect"]
            self.hog_scale = ccfg["hog_scale"]
            self.hog_thresh = ccfg["hog_thresh"]
            self.mog2_sensitivity = ccfg["mog2_sensitivity"]
        except Exception as e:
            self.logger.error(whoami() + str(e))

        try:
            self.fourcc = cv2.VideoWriter_fourcc('X', 'V', 'I', 'D')
        except Exception:
            self.logger.error(whoami() + "Cannot get fourcc, no recording possible")
            self.fourcc = None

    def get_fps(self):
        with self.lock:
            if len(self.fpslist) == 0:
                fps = 0
            else:
                fps = sum([f for f in self.fpslist]) / len(self.fpslist)
                if len(self.fpslist) > 20:
                    del self.fpslist[0]
        return fps

    def shutdown(self, iserror=False):
        self.stop_cam()
        try:
            cv2.destroyWindow(self.cname)
        except Exception:
            pass
        self.stop_recording()
        if iserror:
            self.active = False
            self.isok = False
        self.frame = None

    def stop_cam(self):
        if self.outvideo:
            self.outvideo.release()
            self.logger.debug(whoami() + "camera " + self.cname + " recording stopped")
        if not self.active or not self.isok:
            return 1
        self.parent_pipe.send("stop")
        ret, _ = self.parent_pipe.recv()
        self.mpp.join(5)
        if self.mpp.is_alive():
            os.kill(self.mpp.pid, signal.SIGKILL)
        self.mpp = None
        self.logger.debug(whoami() + "camera " + self.cname + " stopped!")
        return 1

    def startup_cam(self):
        if not self.active or not self.isok:
            return None
        self.mpp = mp.Process(target=mpcam.run_cam, args=(self.ccfg, self.child_pipe, self.mp_loggerqueue, ))
        self.mpp.start()
        try:
            self.parent_pipe.send("query_cam_status")
            self.isok, self.ymax, self.xmax = self.parent_pipe.recv()
        except Exception:
            self.isok = False
            self.active = False
        if self.isok:
            self.logger.debug(whoami() + "camera " + self.cname + " started!")
        else:
            self.logger.debug(whoami() + "camera " + self.cname + " out of function, not started!")
            self.mpp.join()
            self.mpp = None
        return self.mpp

    def stop(self):
        self.running = False
        while not self.shutdown_completed:
            time.sleep(0.1)

    def run(self):
        if not self.active or not self.isok:
            return
        self.startup_cam()
        if not self.isok or not self.active:
            return
        self.running = True
        while self.running and self.isok and self.active:
            t_query = time.time()
            try:
                self.parent_pipe.send("query")
            except Exception as e:
                self.logger.warning(whoami() + str(e) + ": error in communication with camera " + self.cname)
                self.running = False
                self.isok = False
                break
            while True:
                cond1 = self.running
                cond2 = self.parent_pipe.poll()
                if not cond1 or cond2:
                    break
                time.sleep(0.05)
            ret, frame0, rects, tx = self.parent_pipe.recv()
            self.tx = tx
            t_reply = time.time()
            with self.lock:
                self.fpslist.append(1 / (t_reply - t_query))
            if not cond1:
                break
            self.isok = ret
            if not self.isok:
                self.logger.warning(whoami() + ": error in communication with camera " + self.cname)
                self.running = False
                break
            if ret:
                if self.frame is not None:
                    self.oldframe = self.frame.copy()
                else:
                    self.oldframe = None
                self.frame = frame0.copy()
            self.newframe = False
            if self.frame is not None and self.oldframe is not None:
                if np.bitwise_xor(self.frame, self.oldframe).any():
                    self.newframe = True
            self.rects = rects
        self.shutdown()
        self.shutdown_completed = True

    def get_new_detections(self, cnn=True):
        if cnn:
            return self.cnn_classified_list
        else:
            return self.rects

    def clear_new_detections(self):
        self.cnn_classified_list = []
        self.rect = []

    def draw_detections(self, cnn=True):
        if cnn:
            rects = self.cnn_classified_list
        else:
            rects = self.rects
        if self.frame is not None:
            ymax0, xmax0 = self.frame.shape[:2]
            # draw detections
            for x, y, w, h in rects:
                x1 = max(0, x)
                y1 = max(0, y)
                x2 = min(x + w, xmax0)
                y2 = min(y + h, ymax0)
                outstr = "DETECTION!"
                cv2.rectangle(self.frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(self.frame, outstr, (x1 + 3, y2 - 10), cv2.FONT_HERSHEY_DUPLEX, 0.3, (0, 255, 0))

    def start_recording(self):
        if not self.active or not self.isok:
            return None
        if not self.fourcc:
            self.is_recording = False
            self.logger.debug(whoami() + "camera " + self.cname + " no recording possible due to missing fourcc/codec!")
        if self.outvideo:
            try:
                self.outvideo.release()
            except Exception:
                pass
        now = datetime.now()
        datestr = now.strftime("%d%m%Y-%H:%M:%S")
        self.recordfile = self.dirs["video"] + self.cname + "_" + datestr + ".avi"
        self.outvideo = cv2.VideoWriter(self.recordfile, self.fourcc, 10.0, (self.xmax, self.ymax))
        self.is_recording = True
        self.logger.debug(whoami() + "camera " + self.cname + " recording started: " + self.recordfile)

    def write_record(self):
        if not self.active or not self.isok:
            return None
        if self.outvideo and self.is_recording:
            self.outvideo.write(self.frame)

    def stop_recording(self):
        if self.outvideo:
            self.outvideo.release()
            self.outvideo = None
        self.is_recording = False
        self.logger.debug(whoami() + "camera " + self.cname + " recording stopped")


def shutdown_cams(cameras):
    for c in cameras:
        c.stop()


def startup_cams(cameras):
    for c in cameras:
        c.start()


def stop_cams(cameras):
    for c in cameras:
        c.stop()


def destroy_all_cam_windows(cameras):
    for c in cameras:
        try:
            cv2.destroyWindow(c.cname)
        except Exception:
            continue


def start_all_recordings(cameras):
    for c in cameras:
        c.start_recording()


def stop_all_recordings(cameras):
    for c in cameras:
        c.stop_recording()


def run_cameras(pd_outqueue, pd_inqueue, dirs, mplock, cfg, mp_loggerqueue):
    global TERMINATED

    K.clear_session()

    setproctitle("g3." + os.path.basename(__file__))

    # tf.get_logger().setLevel('INFO')
    # tf.autograph.set_verbosity(1)

    logger = mplogging.setup_logger(mp_loggerqueue, __file__)
    logger.info(whoami() + "starting ...")

    sh = SigHandler_pd(logger)
    signal.signal(signal.SIGINT, sh.sighandler_pd)
    signal.signal(signal.SIGTERM, sh.sighandler_pd)

    db = G3DB(mplock, cfg, dirs, logger)
    camera_config = db.get_cameras()
    options = db.get_options()
    cameras = []
    for c in camera_config:
        camera = Camera(c, dirs, mp_loggerqueue, logger)
        cameras.append(camera)

    startup_cams(cameras)

    tgram_active = False
    kbd_active = False
    pd_in_cmd, pd_in_param = pd_inqueue.get()
    if pd_in_cmd == "tgram_active":
        tgram_active = pd_in_param
    elif pd_in_cmd == "kbd_active":
        kbd_active = pd_in_param
    if not camera_config or not cameras:
        logger.error(whoami() + "cannot get correct config for cameras, exiting ...")
        pd_outqueue.put(("error:config", None))
        sys.exit()
    else:
        pd_outqueue.put(("allok", None))

    kreta = KerasRetinaNet(dirs, db, logger)
    try:
        showframes = options["showframes"]
    except Exception:
        logger.warning(whoami() + "showframes not set in config, setting to default False!")
        showframes = False

    while not TERMINATED:

        time.sleep(0.04)

        mainmsglist = []

        for c in cameras:
            mainmsg = "status"
            mainparams = (c.cname, c.frame, c.get_fps(), c.isok, c.active, c.tx)
            if c.active and c.isok:
                try:
                    if c.newframe:
                        kreta.get_cnn_classification(c)
                        c.draw_detections(cnn=True)
                        mainparams = (c.cname, c.frame, c.get_fps(), c.isok, c.active, c.tx)
                        if showframes:
                            cv2.imshow(c.cname, c.frame)
                        c.write_record()
                        new_detections = c.get_new_detections()
                        if new_detections:
                            mainmsg = "detection"
                        c.clear_new_detections()
                except Exception as e:
                    logger.warning(whoami() + str(e))
            mainmsglist.append((mainmsg, mainparams))

        # send to __main__.py
        pd_outqueue.put(mainmsglist)

        if showframes:
            cv2.waitKey(1) & 0xFF

        # telegram handler
        if tgram_active or kbd_active:
            try:
                cmd, param = pd_inqueue.get_nowait()
                logger.debug(whoami() + "received " + cmd)
                if cmd == "stop":
                    break
                elif cmd == "record on":
                    start_all_recordings(cameras)
                elif cmd == "record off":
                    stop_all_recordings(cameras)
            except (queue.Empty, EOFError):
                continue
            except Exception:
                continue

    shutdown_cams(cameras)
    clear_all_queues([pd_inqueue, pd_outqueue])
    logger.info(whoami() + "... exited!")
