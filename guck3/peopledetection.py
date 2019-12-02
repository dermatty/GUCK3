import os
import queue
from setproctitle import setproctitle
from guck3.mplogging import whoami
from guck3 import mplogging, mpcam
import time
import cv2
import multiprocessing as mp
import signal

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
            "ptz_down_url": ptz_down_url
        }
        camera_conf.append(cdata)
    if not camera_conf:
        return None
    return camera_conf


def startup_cams(camera_config, mp_loggerqueue, logger):
    mpp_cams = []
    for c in camera_config:
        if not c["active"]:
            continue
        parent_pipe, child_pipe = mp.Pipe()
        mpp_cam = mp.Process(target=mpcam.run_cam, args=(c, child_pipe, mp_loggerqueue, ))
        mpp_cams.append((c["name"], mpp_cam, parent_pipe, child_pipe))
        mpp_cam.start()
        logger.debug(whoami() + "camera " + c["name"] + " started!")
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


def run_cameras(pd_outqueue, pd_inqueue, cfg, mp_loggerqueue):
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
    pd_in_cmd, pd_in_param = pd_inqueue.get()
    if pd_in_cmd == "tgram_active":
        tgram_active = pd_in_param

    while not TERMINATED:

        time.sleep(0.05)

        # get frames from cameras
        for c in mpp_cams:
            if not c[1]:
                continue
            c[2].send("query")
            ret, frame = c[2].recv()
            if ret:
                cv2.imshow(c[0], frame)
            else:
                stop_cam(c, mpp_cams)
                cv2.destroyWindow(c[0])
                # restart / Meldung

        cv2.waitKey(1) & 0xFF

        # telegram handler
        if tgram_active:
            try:
                tgram_cmd = pd_inqueue.get_nowait()
                if tgram_cmd == "stop":
                    break
            except (queue.Empty, EOFError):
                continue
            except Exception:
                continue

    stop_cams(mpp_cams, logger)
    cv2.destroyAllWindows()
    clear_all_queues([pd_inqueue, pd_outqueue], logger)
    logger.info(whoami() + "... exited!")
