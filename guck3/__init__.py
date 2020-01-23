import ftplib
from os.path import expanduser
import os
import shutil
import queue


class ConfigReader:
    def __init__(self, cfg):
        self.cfg = cfg

    def get_cameras(self):
        camera_conf = []
        # CAMERA
        idx = 1
        while True:
            str0 = "CAMERA" + str(idx)
            try:
                assert self.cfg[str0]["NAME"]
                active = True if self.cfg[str0]["ACTIVE"].lower() == "yes" else False
                camera_name = self.cfg[str0]["NAME"]
                stream_url = self.cfg[str0]["STREAM_URL"]
                photo_url = self.cfg[str0]["PHOTO_URL"]
                reboot_url = self.cfg[str0]["REBOOT_URL"]
                ptz_mode = self.cfg[str0]["PTZ_MODE"].lower()
                if ptz_mode not in ["start", "startstop", "none"]:
                    ptz_mode = "none"
                ptz_right_url = self.cfg[str0]["PTZ_RIGHT_URL"]
                ptz_left_url = self.cfg[str0]["PTZ_LEFT_URL"]
                ptz_up_url = self.cfg[str0]["PTZ_UP_URL"]
                ptz_down_url = self.cfg[str0]["PTZ_DOWN_URL"]
                min_area_rect = int(self.cfg[str0]["MIN_AREA_RECT"])
                hog_scale = float(self.cfg[str0]["HOG_SCALE"])
                hog_thresh = float(self.cfg[str0]["HOG_THRESH"])
                mog2_sensitivity = float(self.cfg[str0]["MOG2_SENSITIVITY"])
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
                    }
                camera_conf.append(cdata)
            except Exception:
                break
            idx += 1
        return camera_conf

    def get_options(self):
        return self.cfg["OPTIONS"]

    def get_telegram(self):
        return self.cfg["TELEGRAM"]


# setup folders
def setup_dirs():
    install_dir = os.path.dirname(os.path.realpath(__file__))
    userhome = expanduser("~")
    maindir = userhome + "/.guck3/"
    logsdir = maindir + "logs/"
    videodir = maindir + "video/"
    photodir = maindir + "photo/"
    dirs = {
        "install": install_dir,
        "home": userhome,
        "main": maindir,
        "video": videodir,
        "photo": photodir,
        "logs": logsdir
    }

    # check for maindir
    if not os.path.exists(maindir):
        try:
            os.mkdir(maindir)
        except Exception as e:
            return -1, str(e)

    # check for logsdir
    if not os.path.exists(logsdir):
        try:
            os.mkdir(logsdir)
        except Exception as e:
            return -1, str(e) + ": cannot create logs directory!", None, None, None, None, None

    # check for videodir
    if not os.path.exists(videodir):
        try:
            os.mkdir(videodir)
        except Exception as e:
            return -1, str(e) + ": cannot create video directory!", None, None, None, None, None

    # check for photodir
    if not os.path.exists(photodir):
        try:
            os.mkdir(photodir)
        except Exception as e:
            return -1, str(e) + ": cannot create photo directory!", None, None, None, None, None

    # check for configfile
    if not os.path.isfile(maindir + "guck3.config"):
        config_template = "/etc/default/guck3.config"
        if os.path.isfile(config_template):
            try:
                shutil.copy(config_template, maindir + "guck3.config")
            except Exception as e:
                return -1, str(e) + ": cannot initialize guck3.config file!"
        else:
            try:
                shutil.copy(install_dir + "/data/guck3.config", maindir + "guck3.config")
            except Exception as e:
                return -1, str(e) + ": cannot initialize guck3.config file!"

    return 1, dirs


# clear all queues
def clear_all_queues(queuelist):
    for q in queuelist:
        while True:
            try:
                q.get_nowait()
            except (queue.Empty, EOFError):
                break
