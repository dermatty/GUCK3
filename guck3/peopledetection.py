import os
import queue
from setproctitle import setproctitle
from guck3.mplogging import whoami
from guck3 import mplogging, get_camera_config, mpcam, mpcommunicator
import time
import cv2
import multiprocessing as mp
import signal

TERMINATED = False


class SigHandler_pd:
    def __init__(self, mpp_cams, logger):
        self.logger = logger
        self.mpp_cams = mpp_cams

    def sighandler_pd(self, a, b):
        self.shutdown()

    def shutdown(self):
        global TERMINATED
        TERMINATED = True
        stop_cams(self.mpp_cams, self.logger)
        self.logger.debug(whoami() + "got signal, exiting ...")


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


def g3_main(cfg, mp_loggerqueue):
    global TERMINATED
    setproctitle("g3." + os.path.basename(__file__))

    logger = mplogging.setup_logger(mp_loggerqueue, __file__)
    logger.info(whoami() + "starting ...")

    mpp_cams = None
    sh = SigHandler_pd(mpp_cams, logger)
    signal.signal(signal.SIGINT, sh.sighandler_pd)
    signal.signal(signal.SIGTERM, sh.sighandler_pd)

    # spawn mpcommunicator
    pd_inqueue = mp.Queue()
    pd_outqueue = mp.Queue()
    mpp_comm = mp.Process(target=mpcommunicator.run_mpcommunicator, args=(pd_inqueue, pd_outqueue,
                                                                          cfg, mp_loggerqueue, ))
    mpp_comm.start()
    tgram_active = pd_inqueue.get()
    if tgram_active:
        logger.info(whoami() + "telegram is active")
    else:
        logger.info(whoami() + "telegram is NOT active")

    camera_config = get_camera_config(cfg)
    capture_active = False

    while not TERMINATED:

        if not capture_active:
            time.sleep(0.05)
        else:
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
                if capture_active:
                    if tgram_cmd == "exit":
                        stop_cams(mpp_cams, logger)
                        sh.mpp_cams = None
                        pd_outqueue.put(("exit", None))
                        mpp_comm.join()
                        break
                    elif tgram_cmd == "stop":
                        stop_cams(mpp_cams, logger)
                        sh.mpp_cams = None
                        destroy_all_cam_windows(mpp_cams)
                        capture_active = False
                        pd_outqueue.put(("capture_active", capture_active))
                else:
                    if tgram_cmd == "exit":
                        pd_outqueue.put(("exit", None))
                        mpp_comm.join()
                        break
                    elif tgram_cmd == "start":
                        mpp_cams = startup_cams(camera_config, mp_loggerqueue, logger)
                        sh.mpp_cams = mpp_cams
                        capture_active = True
                        pd_outqueue.put(("capture_active", capture_active))
            except (queue.Empty, EOFError):
                continue
            except Exception:
                continue

    cv2.destroyAllWindows()
    clear_all_queues([pd_inqueue, pd_outqueue], logger)
    logger.info(whoami() + "... exited!")
