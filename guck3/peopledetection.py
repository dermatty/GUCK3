import os
from setproctitle import setproctitle
from guck3.mplogging import whoami
from guck3 import mplogging, get_camera_config, mpcam
import time
import cv2
import multiprocessing as mp
import signal


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
    for c in mpp_cams:
        stop_cam(c, mpp_cams, logger)


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


def g3_main(cfg, mp_loggerqueue):
    setproctitle("g3." + os.path.basename(__file__))

    logger = mplogging.setup_logger(mp_loggerqueue, __file__)
    logger.info(whoami() + "starting ...")

    camera_config = get_camera_config(cfg)

    print("Press")
    print("    q to quit")
    print("    s to start video capture")
    print("    e to end video capture")
    capture_active = False
    mpp_cams = None

    while True:

        if capture_active:
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
        else:
            image = cv2.imread(os.getcwd() + "/guck3/data/messi.jpg")
            cv2.imshow("Messi", image)

        ch = cv2.waitKey(1) & 0xFF

        if capture_active:
            if ch == 27 or ch == ord("q"):
                stop_cams(mpp_cams, logger)
                break
            elif ch == ord("e"):
                stop_cams(mpp_cams, logger)
                destroy_all_cam_windows(mpp_cams)
                capture_active = False
        else:
            if ch == ord("q"):
                break
            elif ch == ord("s"):
                cv2.destroyWindow("Messi")
                mpp_cams = startup_cams(camera_config, mp_loggerqueue, logger)
                capture_active = True

        time.sleep(0.05)

    cv2.destroyAllWindows()
    logger.info(whoami() + "... exited!")
