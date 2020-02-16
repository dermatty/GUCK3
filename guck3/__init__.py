import configparser
from os.path import expanduser
import os
import shutil
import queue
import json
import subprocess
import requests


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
    logsdir = "/media/cifs/dokumente/g3logs/"
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


def check_cfg_file(cfgfile):
    try:
        cfg = configparser.ConfigParser()
        cfg.read(cfgfile)
    except Exception:
        return "error in reading config file!", False
    # USER
    idx = 1
    while True:
        str0 = "USER" + str(idx)
        try:
            assert cfg[str0]["USERNAME"]
            userok = False
            assert cfg[str0]["PASSWORD"]
            userok = True
        except Exception:
            break
        idx += 1
    if idx == 1 or not userok:
        return "error in cfg file [USER]!", False
    # CAMERA
    idx = 1
    while True:
        str0 = "CAMERA" + str(idx)
        try:
            assert cfg[str0]
        except Exception:
            break
        try:
            cameraok = False
            assert cfg[str0]["NAME"] != ""
            assert cfg[str0]["ACTIVE"].lower() in ["yes", "no"]
            assert cfg[str0]["STREAM_URL"] != ""
            assert cfg[str0]["PHOTO_URL"] != ""
            assert cfg[str0]["REBOOT_URL"]
            assert cfg[str0]["PTZ_MODE"].lower() in ["start", "startstop", "none"]
            assert cfg[str0]["PTZ_RIGHT_URL"]
            assert cfg[str0]["PTZ_LEFT_URL"]
            assert cfg[str0]["PTZ_UP_URL"]
            assert cfg[str0]["PTZ_DOWN_URL"]
            assert int(cfg[str0]["MIN_AREA_RECT"]) > 0
            assert float(cfg[str0]["HOG_SCALE"]) > 0
            assert float(cfg[str0]["HOG_THRESH"]) > 0
            assert float(cfg[str0]["MOG2_SENSITIVITY"])
            cameraok = True
        except Exception:
            break
        idx += 1
    if idx == 1 or not cameraok:
        return "error in cfg file [CAMERA]!", False
    # OPTIONS
    try:
        assert cfg["OPTIONS"]["REDIS_HOST"].strip() != ""
    except Exception:
        return "error in cfg file [OPTIONS][REDIS_HOST]!", False
    try:
        assert int(cfg["OPTIONS"]["REDIS_PORT"]) > 0
    except Exception:
        return "error in cfg file [OPTIONS][REDIS_PORT]!", False
    try:
        assert cfg["OPTIONS"]["KEYBOARD_ACTIVE"].lower() in ["yes", "no"]
    except Exception:
        return "error in cfg file [OPTIONS][KEYBOARD_ACTIVE]!", False
    try:
        assert cfg["OPTIONS"]["LOGLEVEL"].lower() in ["debug", "info", "warning", "error"]
    except Exception:
        return "error in cfg file [OPTIONS][LOGLEVEL]!", False
    try:
        assert cfg["OPTIONS"]["SHOWFRAMES"].lower() in ["yes", "no"]
    except Exception:
        return "error in cfg file [OPTIONS][SHOWFRAMES]!", False
    try:
        assert cfg["OPTIONS"]["RETINANET_MODEL"]
    except Exception:
        return "error in cfg file [OPTIONS][RETINANET_MODEL]!", False
    # no check for ["OPTIONS"]["ADDTL_PHOTO_PATH"] cause it iss optional
    # TELEGRAM
    try:
        tgram_active = True if cfg["TELEGRAM"]["ACTIVE"].lower() == "yes" else False
    except Exception:
        return "error in cfg file [TELEGRAM][ACTIVE]!", False
    if tgram_active:
        try:
            assert cfg["TELEGRAM"]["TOKEN"]
        except Exception:
            return "error in cfg file [TELEGRAM][TOKEN]!", False
        try:
            chatids = json.loads(cfg.get("TELEGRAM", "CHATIDS"))
            if not isinstance(chatids, list):
                return "error in cfg file [TELEGRAM][CHATIDS]!", False
        except Exception:
            return "error in cfg file [TELEGRAM][CHATIDS]!", False
    return "", True


def get_external_ip(hostlist=[("WAN2TMO_DHCP", "raspisens"), ("WAN_DHCP", "etec")]):
    procstr = 'curl https://api.ipdata.co/"$(dig +short myip.opendns.com @resolver1.opendns.com)"'
    procstr += "?api-key=b8d4413e71b0e5827c4624c856f0439ee6b64ff8a71c419bfcd2d14c"

    iplist = []
    for gateway, hostn in hostlist:
        try:
            ssh = subprocess.Popen(["ssh", hostn, procstr], shell=False, stdout=subprocess.PIPE, stderr=subprocess. PIPE)
            sshres = ssh.stdout.readlines()
            s0 = ""
            for ss in sshres:
                s0 += ss.decode("utf-8")
            d = json.loads(s0)
            iplist.append((gateway, hostn, d["ip"], d["asn"]["name"]))
        except Exception:
            iplist.append((gateway, hostn, "N/A", "N/A"))
    return iplist


def get_sens_temp(hostn="raspisens", filen="/home/pi/sens.txt"):
    procstr = "cat " + filen
    ssh = subprocess.Popen(["ssh", hostn, procstr], shell=False, stdout=subprocess.PIPE, stderr=subprocess. PIPE)
    sshres = ssh.stdout.readlines()
    n = 0
    temp = 0
    hum = 0
    for s in sshres:
        s0 = s.decode("utf-8").split(" ")
        temp += float(s0[2])
        hum += float(s0[3])
        n += 1
    if n > 0:
        temp = temp / n
        hum = hum / n
    return temp, hum


