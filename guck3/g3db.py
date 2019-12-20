from peewee import Model, SqliteDatabase, CharField, BooleanField, IntegerField, FloatField
from playhouse.fields import PickleField
from guck3.mplogging import whoami
import json
import os
import os.path


class G3DB():

    def __init__(self, mplock, cfg, dirs, logger):
        self.logger = logger
        self.cfg = cfg
        self.lock = mplock
        self.dirs = dirs
        self.db_file_name = dirs["main"] + "guck3.db"
        if os.path.isfile(self.db_file_name):
            os.remove(self.db_file_name)
        self.db = SqliteDatabase(self.db_file_name)

        class BaseModel(Model):
            class Meta:
                database = self.db

        class USER(BaseModel):
            username = CharField()
            password = CharField()

        class OPTIONS(BaseModel):
            debuglevel = CharField()
            showframes = BooleanField()
            retinanet_model = CharField()
            storephotos = BooleanField()
            addtl_photo_path = CharField()
            keyboard_active = BooleanField()

        class TELEGRAM(BaseModel):
            active = BooleanField()
            token = CharField()
            chatids = PickleField()

        class CAMERA(BaseModel):
            active = BooleanField()
            name = CharField()
            stream_url = CharField()
            photo_url = CharField()
            reboot_url = CharField()
            ptz_mode = CharField()
            ptz_right_url = CharField()
            ptz_left_url = CharField()
            ptz_up_url = CharField()
            ptz_down_url = CharField()
            min_area_rect = IntegerField()
            hog_scale = FloatField()
            hog_thresh = FloatField()
            mog2_sensitivity = IntegerField()

        def max_sql_variables():
            import sqlite3
            db = sqlite3.connect(':memory:')
            cur = db.cursor()
            cur.execute('CREATE TABLE t (test)')
            low, high = 0, 100000
            while (high - 1) > low:
                guess = (high + low) // 2
                query = 'INSERT INTO t VALUES ' + ','.join(['(?)' for _ in
                                                            range(guess)])
                args = [str(i) for i in range(guess)]
                try:
                    cur.execute(query, args)
                except sqlite3.OperationalError as e:
                    if "too many SQL variables" in str(e):
                        high = guess
                    else:
                        raise
                else:
                    low = guess
            cur.close()
            db.close()
            return low

        self.USER = USER
        self.CAMERA = CAMERA
        self.OPTIONS = OPTIONS
        self.TELEGRAM = TELEGRAM
        self.tablelist = [self.USER, self.CAMERA, self.OPTIONS, self.TELEGRAM]
        self.db.connect()
        self.db.create_tables(self.tablelist)
        self.SQLITE_MAX_VARIABLE_NUMBER = int(max_sql_variables() / 4)

    def get_options(self):
        o = self.OPTIONS.select()[0]
        res = {"debuglevel": o.debuglevel, "showframes": o.showframes, "retinanet_model": o.retinanet_model,
               "storephotos": o.storephotos, "addtl_photo_path": o.addtl_photo_path,
               "keyboard_active": o.keyboard_active}
        return res

    def get_telegram(self):
        t = self.TELEGRAM.select()[0]
        res = {"active": t.active, "token": t.token, "chatids": t.chatids}
        return res

    def copy_cfg_to_db(self):
        self.copyok = True
        # USER
        idx = 1
        while True:
            str0 = "USER" + str(idx)
            try:
                username = self.cfg[str0]["USERNAME"]
                password = self.cfg[str0]["PASSWORD"]
                with self.lock:
                    self.USER.create(username=username, password=password)
            except Exception:
                break
            idx += 1
        if idx == 1:
            self.copyok = False
            return
        self.logger.debug(whoami() + "user data copied to db")
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
                with self.lock:
                    self.CAMERA.create(active=active, name=camera_name, stream_url=stream_url, photo_url=photo_url,
                                       reboot_url=reboot_url, ptz_mode=ptz_mode, ptz_right_url=ptz_right_url,
                                       ptz_left_url=ptz_left_url, ptz_up_url=ptz_up_url, ptz_down_url=ptz_down_url,
                                       min_area_rect=min_area_rect, hog_scale=hog_scale, hog_thresh=hog_thresh,
                                       mog2_sensitivity=mog2_sensitivity)
            except Exception:
                break
            idx += 1
        if idx == 1:
            self.copyok = False
            return
        self.logger.debug(whoami() + "camera data copied to db")
        # OPTIONS
        try:
            keyboard_active = True if self.cfg["OPTIONS"]["KEYBOARD_ACTIVE"].lower() == "yes" else False
        except Exception:
            keyboard_active = False
        try:
            debuglevel = self.cfg["OPTIONS"]["DEBUGLEVEL"].lower()
        except Exception:
            debuglevel = "info"
        try:
            showframes = True if self.cfg["OPTIONS"]["SHOWFRAMES"].lower() == "yes" else False
        except Exception:
            showframes = False
        try:
            retinanet_model = self.cfg["OPTIONS"]["RETINANET_MODEL"]
        except Exception:
            self.copyok = False
            return
        try:
            storephotos = True if self.cfg["OPTIONS"]["STOREPHOTOS"].lower() == "yes" else False
        except Exception:
            storephotos = False
        try:
            addtl_photo_path = self.cfg["OPTIONS"]["ADDTL_PHOTO_PATH"]
            if addtl_photo_path.lower() == "none" or not os.path.exists(addtl_photo_path):
                addtl_photo_path = "None"
            elif addtl_photo_path[-1] != "/":
                addtl_photo_path += "/"
        except Exception:
            addtl_photo_path = "None"
        try:
            with self.lock:
                self.OPTIONS.create(debuglevel=debuglevel, showframes=showframes, retinanet_model=retinanet_model,
                                    storephotos=storephotos, addtl_photo_path=addtl_photo_path,
                                    keyboard_active=keyboard_active)
        except Exception:
            self.copyok = False
            return
        # TELEGRAM
        try:
            active = True if self.cfg["TELEGRAM"]["ACTIVE"].lower() == "yes" else False
        except Exception:
            active = False
        try:
            token = self.cfg["TELEGRAM"]["TOKEN"]
        except Exception:
            active = False
            token = "N/A"
        try:
            chatids = json.loads(self.cfg.get("TELEGRAM", "CHATIDS"))
        except Exception:
            chatids = []
            active = False
            token = "N/A"
        try:
            with self.lock:
                self.TELEGRAM.create(active=active, token=token, chatids=chatids)
        except Exception:
            self.copyok = False

    def copy_db_to_cfg(self):
        if not self.copyok:
            return
        # OPTIONS
        options = self.OPTIONS.select()[0]
        self.cfg["OPTIONS"]["DEBUGLEVEL"] = options.debuglevel
        self.cfg["OPTIONS"]["SHOWFRAMES"] = "yes" if options.showframes else "no"
        self.cfg["OPTIONS"]["RETINANET_MODEL"] = options.retinanet_model
        self.cfg["OPTIONS"]["STOREPHOTOS"] = "yes" if options.storephotos else "no"
        self.cfg["OPTIONS"]["ADDTL_PHOTO_PATH"] = options.addtl_photo_path
        self.cfg["OPTIONS"]["KEYBOARD_ACTIVE"] = "yes" if options.keyboard_active else "no"
        # TELEGRAM
        tgram = self.TELEGRAM.select()[0]
        self.cfg["TELEGRAM"]["ACTIVE"] = "yes" if tgram.active else "no"
        self.cfg["TELEGRAM"]["TOKEN"] = tgram.token
        self.cfg["TELEGRAM"]["CHATIDS"] = "[" + ",".join([str(ci) for ci in tgram.chatids]) + "]"
        # CAMERAS
        cameras = self.CAMERA.select()
        for i, c in enumerate(cameras, start=1):
            cstr = "CAMERA" + str(i)
            self.cfg[cstr]["ACTIVE"] = "yes" if c.active else "no"
            self.cfg[cstr]["NAME"] = c.name
            self.cfg[cstr]["STREAM_URL"] = c.stream_url
            self.cfg[cstr]["PHOTO_URL"] = c.photo_url
            self.cfg[cstr]["REBOOT_URL"] = c.reboot_url
            self.cfg[cstr]["PTZ_MODE"] = c.photo_url
            self.cfg[cstr]["PTZ_RIGHT_URL"] = c.ptz_right_url
            self.cfg[cstr]["PTZ_LEFT_URL"] = c.ptz_left_url
            self.cfg[cstr]["PTZ_UP_URL"] = c.ptz_up_url
            self.cfg[cstr]["PTZ_DOWN_URL"] = c.ptz_down_url
            self.cfg[cstr]["MIN_AREA_RECT"] = str(c.min_area_rect)
            self.cfg[cstr]["HOG_SCALE"] = str(c.hog_scale)
            self.cfg[cstr]["HOG_THRESH"] = str(c.hog_thresh)
            self.cfg[cstr]["MOG2_SENSITIVITY"] = str(c.mog2_sensitivity)
        # USER
        users = self.USER.select()
        for i, u in enumerate(users, start=1):
            ustr = "USER" + str(i)
            self.cfg[ustr]["USERNAME"] = u.username
            self.cfg[ustr]["PASSWORD"] = u.password
        # write to cfg_file
        cfg_file = self.dirs["main"] + "guck3.config"
        try:
            with open(cfg_file, "w") as f:
                self.cfg.write(f)
        except Exception as e:
            self.logger.error(whoami() + str(e) + ". cannot write db to config file!")
            return -1
        return 1

    def close(self):
        self.db.execute_sql("VACUUM")
        self.db.drop_tables(self.tablelist)
        self.db.close()
        os.remove(self.db_file_name)
