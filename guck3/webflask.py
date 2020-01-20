from __future__ import unicode_literals
import multiprocessing
import gunicorn.app.base
import os
from flask import Flask, render_template, make_response, request, g, redirect, url_for, session, Response
from flask.logging import default_handler
from flask_sse import sse
from flask_session import Session
import flask_login
from setproctitle import setproctitle
from guck3.mplogging import whoami
from guck3.g3db import G3DB
import time
from guck3 import models, setup_dirs
from threading import Thread
import logging
import redis
import configparser
import requests
import cv2
import numpy as np
import threading
from threading import get_ident

DB = None
USERS = None
USERDATA = None
DIRS = None

# get redis data
ret, dirs = setup_dirs()
cfg_file = dirs["main"] + "guck3.config"
cfg = configparser.ConfigParser()
cfg.read(cfg_file)
try:
    REDIS_HOST = cfg["OPTIONS"]["REDIS_HOST"]
except Exception:
    REDIS_HOST = "127.0.0.1"
try:
    REDIS_PORT = int(cfg["OPTIONS"]["REDIS_PORT"])
except Exception:
    REDIS_PORT = 6379
REDISCLIENT = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, db=0)


# -------------- Helper functions --------------

def number_of_workers():
    return (multiprocessing.cpu_count() * 2) + 1


# -------------- Init Flask App --------------
app = Flask(__name__)
app.secret_key = "dfdsmdsv11nmDFSDfds"
app.config["REDIS_URL"] = "redis://" + REDIS_HOST + ":" + str(REDIS_PORT)
app.config['SESSION_TYPE'] = "redis"
app.config["SESSION_REDIS"] = REDISCLIENT
app.register_blueprint(sse, url_prefix='/stream')
Session(app)


# -------------- MainCommunicator --------------
class MainCommunicator(Thread):

    def __init__(self, inqueue, outqueue):
        Thread.__init__(self)
        self.daemon = True
        self.inqueue = inqueue
        self.outqueue = outqueue

    def run(self):
        while True:
            time.sleep(1)


# -------------- Login Manager --------------

login_manager = flask_login.LoginManager()
login_manager.login_view = 'userlogin'
login_manager.init_app(app)


@app.before_request
def beforerequest():
    try:
        user0 = flask_login.current_user.get_id()
        g.user = user0
        if user0 is not None:
            USERDATA = DB.get_userdata()
            if not USERDATA or user0 not in USERDATA:
                DB.insert_new_userdata(user0, time.time(), True, 0, [])
            else:
                DB.update_userdata(user0, time.time(), True, USERDATA[user0]["no_newdetections"],
                                   USERDATA[user0]["photolist"])
    except Exception as e:
        app.logger.info(whoami() + str(e))
        pass


class User(flask_login.UserMixin):
    pass


@login_manager.user_loader
def user_loader(email):
    if email not in USERS:
        return
    try:
        user = User()
        user.id = email
    except Exception:
        pass
    return user


@app.route("/userlogout", methods=['GET', 'POST'])
@flask_login.login_required
def userlogout():
    userid = flask_login.current_user.get_id()
    app.logger.info(whoami() + ": user logging out - " + userid)
    flask_login.logout_user()
    return redirect(url_for("index"))


@app.route("/userlogin", methods=['GET', 'POST'])
def userlogin():
    if request.method == "GET":
        app.logger.info(whoami() + ": new user starting to log in ...")
        userloginform = models.UserLoginForm(request.form)
        return render_template("login.html", userloginform=userloginform, userauth=flask_login.current_user.is_authenticated)
    else:
        userloginform = models.UserLoginForm(request.form)
        email = userloginform.email.data
        pw = userloginform.password.data
        app.logger.info(whoami() + ": user trying to log in - " + email)
        try:
            correct_pw = USERS[email]
        except Exception:
            app.logger.warning(whoami() + ": user log in failed - " + email)
            return redirect(url_for("index"))
        if pw == correct_pw:
            app.logger.info(whoami() + ": user logged in - " + email)
            try:
                user = User()
                user.id = email
                flask_login.login_user(user)
            except Exception:
                pass
            return render_template("index.html")
        app.logger.warning(whoami() + ": user log in failed- " + email)
        return redirect(url_for('index'))


# -------------- Index.html / Home --------------

@app.route("/", methods=['GET', 'POST'])
@app.route("/home", methods=['GET', 'POST'])
@flask_login.login_required
def index():
    return render_template('index.html')


# -------------- detections --------------

@app.route("/detections", methods=['GET', 'POST'])
@flask_login.login_required
def detections():
    return render_template('index.html')


# -------------- livecam --------------

# all this is copy-paste from :
#    https://github.com/miguelgrinberg/flask-video-streaming

class CameraEvent(object):
    def __init__(self):
        self.events = {}

    def wait(self):
        ident = get_ident()
        if ident not in self.events:
            self.events[ident] = [threading.Event(), time.time()]
        return self.events[ident][0].wait()

    def set(self):
        now = time.time()
        remove = None
        for ident, event in self.events.items():
            if not event[0].isSet():
                event[0].set()
                event[1] = now
            else:
                if now - event[1] > 5:
                    remove = ident
        if remove:
            del self.events[remove]

    def clear(self):
        self.events[get_ident()][0].clear()


class BaseCamera(object):
    thread = None  # background thread that reads frames from camera
    frame = None  # current frame is stored here by background thread
    last_access = 0  # time of last client access to the camera
    event = CameraEvent()

    def __init__(self):
        """Start the background camera thread if it isn't running yet."""
        if BaseCamera.thread is None:
            BaseCamera.last_access = time.time()
            BaseCamera.thread = threading.Thread(target=self._thread)
            BaseCamera.thread.start()
            while self.get_frame() is None:
                time.sleep(0.01)

    def get_frame(self):
        BaseCamera.last_access = time.time()
        BaseCamera.event.wait()
        BaseCamera.event.clear()
        return BaseCamera.frame

    @staticmethod
    def frames():
        raise RuntimeError('Must be implemented by subclasses.')

    @classmethod
    def _thread(cls):
        app.logger.info(whoami() + "starting camera thread")
        frames_iterator = cls.frames()
        for frame in frames_iterator:
            BaseCamera.frame = frame
            BaseCamera.event.set()  # send signal to clients
            time.sleep(0)
            if time.time() - BaseCamera.last_access > 10:
                frames_iterator.close()
                app.logger.info(whoami() + "stopping camera thread due to inactivity")
                break
        BaseCamera.thread = None


class Camera(BaseCamera):
    def __init__(self, camnr):
        cameralist = [(cd["name"], cd["stream_url"]) for cd in DB.get_cameras()]
        Camera.name, Camera.surl = cameralist[camnr]
        app.logger.info(whoami() + "opening video stream on camera " + self.name)
        super(Camera, self).__init__()

    @staticmethod
    def frames():
        try:
            camera = cv2.VideoCapture(Camera.surl)
            while True:
                _, img = camera.read()
                yield cv2.imencode('.jpg', img)[1].tobytes()
        except Exception as e:
            app.logger.warning(whoami() + "cannot get frames from " + Camera.name + ": " + str(e))


def gen(camera):
    while True:
        try:
            frame = camera.get_frame()
            if frame:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        except Exception:
            pass


@app.route('/video_feed/<camnr>')
def video_feed(camnr):
    return Response(gen(Camera(int(camnr)-1)), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route("/livecam", defaults={"camnrstr": 0, "ptz": 0}, methods=['GET', 'POST'])
@app.route("/livecam/<camnrstr>", defaults={"ptz": 0}, methods=['GET', 'POST'])
@app.route("/livecam/<camnrstr>/<ptz>", methods=['GET', 'POST'])
@flask_login.login_required
def livecam(camnrstr=0, ptz=0):
    if request.method == "GET":
        ptz0 = int(ptz)
        camnr = int(camnrstr)
        cameradata = DB.get_cameras()
        cameralist = [(cd["name"], cd["photo_url"], cd["stream_url"]) for cd in cameradata]
        if ptz0 != 0 and len(cameralist)-1 >= camnr:
            ptzlist = [(cd["ptz_up_url"], cd["ptz_down_url"], cd["ptz_left_url"], cd["ptz_right_url"])
                       for cd in cameradata]
            ptz_up, ptz_down, ptz_left, ptz_right = ptzlist[camnr]
            ptzcommand = ""
            if ptz0 == 1:
                ptzcommand = ptz_up
            elif ptz0 == 2:
                ptzcommand = ptz_down
            elif ptz0 == 3:
                ptzcommand = ptz_left
            elif ptz0 == 4:
                ptzcommand = ptz_right
            if ptzcommand != "":
                try:
                    requests.get(ptzcommand)
                except Exception:
                    pass
        return render_template("livecam.html", cameralist=cameralist, camnr=camnr+1, ptz=0)
    elif request.method == "POST":
        pass


# -------------- StandaloneApplication/main --------------

class StandaloneApplication(gunicorn.app.base.BaseApplication):

    def __init__(self, app, options=None):
        self.options = options or {}
        self.application = app
        super().__init__()

    def load_config(self):
        config = {key: value for key, value in self.options.items()
                  if key in self.cfg.settings and value is not None}
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


def main(cfg, mplock, dirs, inqueue, outqueue, loggerqueue):
    global DB
    global USERS
    global USERDATA
    global DIRS
    global app

    setproctitle("g3." + os.path.basename(__file__))

    DIRS = dirs

    log_handler = logging.FileHandler(dirs["logs"] + "webflask.log", mode="w")
    log_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    app.logger.removeHandler(default_handler)
    app.logger.setLevel(logging.DEBUG)
    app.logger.addHandler(log_handler)

    app.logger.info(whoami() + "starting ...")

    db = G3DB(mplock, cfg, dirs, app.logger)
    DB = db

    # Password
    USERS = DB.get_users()
    USERDATA = DB.get_userdata()

    # start communicator thread
    maincomm = MainCommunicator(inqueue, outqueue)
    maincomm.start()

    options = {
        'bind': '%s:%s' % ('127.0.0.1', '8080'),
        'capture-output': True,
        'debug': True,
        'workers': number_of_workers(),
    }
    StandaloneApplication(app, options).run()


if __name__ == '__main__':
    main()
