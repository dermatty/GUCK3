from os.path import expanduser
import os
import shutil


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


# setup folders
def setup_dirs():
    install_dir = os.path.dirname(os.path.realpath(__file__))
    userhome = expanduser("~")
    maindir = userhome + "/.guck3/"
    logsdir = maindir + "logs/"
    dirs = {
        "install": install_dir,
        "home": userhome,
        "main": maindir,
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
