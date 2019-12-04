import os
import queue
from setproctitle import setproctitle
from guck3.mplogging import whoami
from guck3 import mplogging, mpcam
import time
import cv2
import multiprocessing as mp
import signal
import numpy as np
import keras
from keras_retinanet import models
from keras_retinanet.utils.image import read_image_bgr, preprocess_image, resize_image
# import tensorflow as tf
from keras.utils import np_utils


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
    def __init__(self, dirs, cfg, logger):
        self.logger = logger
        self.active = False
        self.cfg = cfg
        self.dirs = dirs
        self.RETINA_PATH = self.dirs["main"] + self.cfg["OPTIONS"]["RETINANET_MODEL"]
        print(self.RETINA_PATH)
        try:
            # self.RETINAMODEL = models.load_model(self.RETINA_PATH, backbone_name='resnet50')
            self.RETINAMODEL = models.load_model('/home/stephan/.guck3/resnet50_coco_best_v2.1.0.h5', backbone_name='resnet50')
            print("-----------")
            self.active = True
            self.logger.info(whoami() + "RetinaNet initialized!")
        except Exception as e:
            self.logger.error(whoami() + str(e) + ": cannot init RetinaNet!")

    def overlap_rects(r1, r2):
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

    def get_cnn_classification(self, frame, objlist):
        if not self.active:
            return
        objlist_ret = []
        for o in objlist:
            id, rect, class_ai, class_ai_lt = o
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
                x, y, w, h = rect
                r2 = (x, y, x + w, y + h)
                overlapArea, ratio1, ratio2 = self.overlap_rects(r1, r2)
                if (ratio1 > 0.70 or ratio2 > 0.70):
                    self.logger.info(" Human detected with score " + str(score) + " and overlap " + str(ratio1) + " / " + str(ratio2))
                    found = True
                    break
            if found:
                class_ai_lt = time.time()
                class_ai += 1
                self.logger.info(whoami() + "!! CLASSIFIED !!")
            objlist_ret.append(id, rect, class_ai, class_ai_lt)
        return objlist_ret


# read camera data from config
def get_camera_config(cfg):
    snr = 0
    idx = 0
    camera_conf = []
    while idx < 99:
        idx += 1
        try:
            snr += 1
            snrstr = "CAMERA" + str(snr)
            active = True if cfg[snrstr]["ACTIVE"].lower() == "yes" else False
            camera_name = cfg[snrstr]["NAME"]
            stream_url = cfg[snrstr]["STREAM_URL"]
            photo_url = cfg[snrstr]["PHOTO_URL"]
            reboot_url = cfg[snrstr]["REBOOT_URL"]
            ptz_mode = cfg[snrstr]["PTZ_MODE"].lower()
            if ptz_mode not in ["start", "startstop", "none"]:
                ptz_mode = "none"
            ptz_right_url = cfg[snrstr]["PTZ_RIGHT_URL"]
            ptz_left_url = cfg[snrstr]["PTZ_LEFT_URL"]
            ptz_up_url = cfg[snrstr]["PTZ_UP_URL"]
            ptz_down_url = cfg[snrstr]["PTZ_DOWN_URL"]
            min_area_rect = int(cfg[snrstr]["MIN_AREA_RECT"])
            hog_scale = float(cfg[snrstr]["HOG_SCALE"])
            hog_thresh = float(cfg[snrstr]["HOG_THRESH"])
            mog2_sensitivity = float(cfg[snrstr]["MOG2_SENSITIVITY"])
            scanrate = float(cfg[snrstr]["SCANRATE"])
        except Exception:
            continue
        cdata = {
            "name": camera_name,
            "active": active,
            "stream_url": stream_url,
            "photo_url": photo_url,
            "reboot_url": reboot_url,
            "ptz_mode": ptz_mode,
            "ptz_right_url": ptz_right_url,
            "ptz_left_url": ptz_left_url,
            "ptz_up_url": ptz_up_url,
            "ptz_down_url": ptz_down_url,
            "min_area_rect": min_area_rect,
            "hog_scale": hog_scale,
            "hog_thresh": hog_thresh,
            "mog2_sensitivity": mog2_sensitivity,
            "scanrate": scanrate
        }
        camera_conf.append(cdata)
    if not camera_conf:
        return None
    return camera_conf


def startup_cams(camera_config, mp_loggerqueue, logger):
    mpp_cams = []
    for i, c in enumerate(camera_config):
        if not c["active"]:
            continue
        parent_pipe, child_pipe = mp.Pipe()
        mpp_cam = mp.Process(target=mpcam.run_cam, args=(c, child_pipe, mp_loggerqueue, ))
        mpp_cam.start()
        try:
            parent_pipe.send("query_cam_status")
            camstatus = parent_pipe.recv()
        except Exception:
            camstatus = False
        if camstatus:
            mpp_cams.append((c["name"], mpp_cam, parent_pipe, child_pipe))
            logger.debug(whoami() + "camera " + c["name"] + " started!")
        else:
            logger.debug(whoami() + "camera " + c["name"] + " out of function, not started!")
            mpp_cam.join()
            camera_config[i]["active"] = False
    return mpp_cams


def stop_cams(mpp_cams, logger):
    if not mpp_cams:
        return
    for c in mpp_cams:
        stop_cam(c, mpp_cams, logger)
    mpp_cams = None


def stop_cam(c, mpp_cams, logger):
    try:
        i = mpp_cams.index(c)
    except Exception as e:
        logger.warning(whoami() + str(e) + "cannot stop cam!")
        return -1
    cname, mpp_cam, parent_pipe, child_pipe = c
    parent_pipe.send("stop")
    ret, _ = parent_pipe.recv()
    mpp_cam.join(5)
    if mpp_cam.is_alive():
        os.kill(mpp_cam.pid, signal.SIGKILL)
    mpp_cams[i] = cname, None, parent_pipe, child_pipe
    logger.debug(whoami() + "camera " + cname + " stopped!")
    return 1


def destroy_all_cam_windows(mpp_cams):
    for cname, _, _, _ in mpp_cams:
        cv2.destroyWindow(cname)


def clear_all_queues(queuelist, logger):
    for q in queuelist:
        while True:
            try:
                q.get_nowait()
            except (queue.Empty, EOFError):
                break
    logger.debug(whoami() + "all queues cleared")


def run_cameras(pd_outqueue, pd_inqueue, dirs, cfg, mp_loggerqueue):
    global TERMINATED
    setproctitle("g3." + os.path.basename(__file__))

    logger = mplogging.setup_logger(mp_loggerqueue, __file__)
    logger.info(whoami() + "starting ...")

    camera_config = get_camera_config(cfg)
    mpp_cams = startup_cams(camera_config, mp_loggerqueue, logger)

    sh = SigHandler_pd(logger)
    signal.signal(signal.SIGINT, sh.sighandler_pd)
    signal.signal(signal.SIGTERM, sh.sighandler_pd)

    tgram_active = False
    kbd_active = False
    pd_in_cmd, pd_in_param = pd_inqueue.get()
    if pd_in_cmd == "tgram_active":
        tgram_active = pd_in_param
    elif pd_in_cmd == "kbd_active":
        kbd_active = pd_in_param

    # kreta = KerasRetinaNet(dirs, cfg, logger)

    while not TERMINATED:

        time.sleep(0.05)

        # get frames from cameras
        camlist = []
        for i, c in enumerate(mpp_cams):
            camlist.append((None, None, None, None, None))
            if not c[1]:
                camlist[i] = (c[0], None, None, None, None)
                continue
            c[2].send("query")
        for i, c in enumerate(mpp_cams):
            if not c[1]:
                continue
            ret, frame0, objlist, tx = c[2].recv()
            if ret:
                cv2.imshow(c[0], frame0)
            else:
                stop_cam(c, mpp_cams)
                cv2.destroyWindow(c[0])
                # restart / Meldung

        cv2.waitKey(1) & 0xFF

        # telegram handler
        if tgram_active or kbd_active:
            try:
                cmd = pd_inqueue.get_nowait()
                logger.debug(whoami() + "received " + cmd)
                if cmd == "stop":
                    break
            except (queue.Empty, EOFError):
                continue
            except Exception:
                continue

    stop_cams(mpp_cams, logger)
    cv2.destroyAllWindows()
    clear_all_queues([pd_inqueue, pd_outqueue], logger)
    logger.info(whoami() + "... exited!")
