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
from guck3.camera import gen, Camera
import time
from guck3 import models, setup_dirs
from threading import Thread, Lock
import logging
import redis
import configparser
import requests
import signal


DB = None
USERS = None
DIRS = None
maincomm = None

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


def sighandler(a, b):
    try:
        DB.closeall()
    except Exception as e:
        print(str(e))


# -------------- Init Flask App --------------
app = Flask(__name__)
app.secret_key = "dfdsmdsv11nmDFSDfds_ers"
app.config["REDIS_URL"] = "redis://" + REDIS_HOST + ":" + str(REDIS_PORT)
app.config['SESSION_TYPE'] = "redis"
app.config["SESSION_REDIS"] = REDISCLIENT
app.register_blueprint(sse, url_prefix='/stream')
Session(app)


# -------------- MainCommunicator --------------
class MainCommunicator(Thread):

    def __init__(self, inqueue, outqueue, app, db):
        Thread.__init__(self)
        self.daemon = True
        self.inqueue = inqueue
        self.outqueue = outqueue
        self.lock = Lock()
        self.app = app
        self.db = db
        self.userdata_updated = False

    def sse_publish(self):
        if self.pd_active:
            with self.app.app_context():
                result0 = render_template("guckphoto.html", nralarms=0, guckstatus="on", dackel="bark")
                type0 = "nrdet0"
                sse.publish({"message": result0}, type=type0)
                type0 = "title0"
                sse.publish({"message": str(0)}, type=type0)
        else:
            with self.app.app_context():
                result0 = render_template("guckphoto.html", nralarms=0, guckstatus="off", dackel="nobark")
                type0 = "nrdet0"
                sse.publish({"message": result0}, type=type0)
                type0 = "title0"
                sse.publish({"message": str(0)}, type=type0)
        self.last_sse_published = time.time()

    def run(self):
        self.pd_active = "N/A"
        self.last_sse_published = 0
        while True:
            try:
                with self.lock:
                    self.outqueue.put(("get_pd_status", None))
                    cmd, data = self.inqueue.get()
            except Exception:
                pass
            try:
                lastuserdata_tt = float(REDISCLIENT.get("userdata_last_updated").decode())
                userdata_updated_since = (lastuserdata_tt > self.last_sse_published)
            except Exception:
                userdata_updated_since = False
            if cmd != self.pd_active or userdata_updated_since:
                self.pd_active = cmd
                self.sse_publish()
            time.sleep(0.5)


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
            userdata = DB.get_userdata()
            user_in_userdata = False
            if userdata:
                user_in_userdata = (len([1 for key in userdata if key == user0]) > 0)
            if not userdata or not user_in_userdata:
                DB.insert_new_userdata(user0, time.time(), True, 0, [])
            else:
                DB.update_userdata(user0, time.time(), True, userdata[user0]["no_newdetections"],
                                   userdata[user0]["photolist"])
            REDISCLIENT.set("userdata_last_updated", time.time())
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
    except Exception as e:
        app.logger.warning(whoami() + str(e))
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

@app.route('/video_feed/<camnr>')
def video_feed(camnr):
    return Response(gen(Camera(int(camnr)-1, DB)), mimetype='multipart/x-mixed-replace; boundary=frame')


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


def main(cfg, dirs, inqueue, outqueue, loggerqueue):
    global DB
    global USERS
    global DIRS
    global app
    global maincomm

    setproctitle("g3." + os.path.basename(__file__))

    DIRS = dirs

    log_handler = logging.FileHandler(dirs["logs"] + "webflask.log", mode="w")
    log_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    app.logger.removeHandler(default_handler)
    app.logger.setLevel(logging.DEBUG)
    app.logger.addHandler(log_handler)

    app.logger.info(whoami() + "starting ...")

    tlock = Lock()
    DB = G3DB(tlock, cfg, dirs, app.logger)
    if not DB.copyok:
        app.logger.error(whoami() + ": cannot init DB, exiting")
        DB.closeall()
        outqueue.put("False")
    else:
        outqueue.put("True")

    # Password
    USERS = DB.get_users()

    # start communicator thread
    maincomm = MainCommunicator(inqueue, outqueue, app, DB)
    maincomm.start()

    options = {
        'bind': '%s:%s' % ('127.0.0.1', '8080'),
        'capture-output': True,
        'debug': True,
        'workers': number_of_workers(),
    }
    signal.signal(signal.SIGFPE, sighandler)     # nicht die feine englische / faut de mieux
    StandaloneApplication(app, options).run()


if __name__ == '__main__':
    main()
