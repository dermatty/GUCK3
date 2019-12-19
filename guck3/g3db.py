from peewee import Model, SqliteDatabase, CharField, BooleanField, IntegerField, FloatField
from playhouse.fields import PickleField
import json


class G3DB():

    def __init__(self, cfg, dirs, logger):
        self.logger = logger
        self.cfg = cfg
        self.dirs = dirs
        self.db_file_name = dirs["main" + "guck3.db"]
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
        self.tablelist = [self.USER]
        self.db.connect()
        self.db.create_tables(self.tablelist)
        self.SQLITE_MAX_VARIABLE_NUMBER = int(max_sql_variables() / 4)
        self.copy_cfg_to_db()

    def copy_cfg_to_db(self):
        self.copyok = True
        # USER
        idx = 1
        while True:
            str0 = "USER" + str(idx)
            try:
                username = self.cfg[str0]["USERNAME"]
                password = self.cfg[str0]["PASSWORD"]
                self.USER.create(username=username, password=password)
            except Exception:
                break
            idx += 1
        if idx == 1:
            self.copyok = False
            return
        # CAMERA
        idx = 1
        while True:
            str0 = "CAMERA" + str(idx)
            try:
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
                self.CAMERA.create(active=active, name=camera_name, stream_url=stream_url, photo_url=photo_url,
                                   reboot_url=reboot_url, ptz_mode=ptz_mode, ptz_right_url=ptz_right_url,
                                   ptz_left_url=ptz_left_url, ptz_up_url=ptz_up_url, ptz_down_url=ptz_down_url,
                                   min_area_rect=min_area_rect, hog_scale=hog_scale, hog_thresh=hog_thresh,
                                   mog2_sensitivity=mog2_sensitivity)
            except Exception:
                break
        if idx == 1:
            self.copyok = False
            return
        # OPTIONS
        try:
            loglevel = self.cfg["OPTIONS"]["debuglevel"].lower()
        except Exception:
            loglevel = "info"
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
            if addtl_photo_path.lower() == "none":
                addtl_photo_path = "None"
        except Exception:
            addtl_photo_path = "None"
        try:
            self.OPTIONS.create(debuglevel=loglevel, showframes=showframes, retinanet_model=retinanet_model,
                                storephotos=storephotos, addtl_photo_path=addtl_photo_path)
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
            self.TELEGRAM.create(active=active, token=token, chatids=chatids)
        except Exception:
            self.copyok = False

    def copy_db_to_cfg(self):
        if not self.copyok:
            return
        # OPTIONS
        options = self.OPTIONS.select()
        self.cfg["OPTIONS"]["DEBUGLEVEL"] = options.debuglevel
        self.cfg["OPTIONS"]["SHOWFRAMES"] = "yes" if options.showframes else "no"
        self.cfg["OPTIONS"]["RETINAMODEL"] = options.retinamodel
        self.cfg["OPTIONS"]["STOREPHOTOS"] = "yes" if options.storephotos else "no"
        self.cfg["OPTIONS"]["ADDTL_PHOTO_PATH"] = options.addtl_photo_path
        # TELEGRAM
        tgram = self.TELEGRAM.select()
        self.cfg["TELEGRAM"]["ACTIVE"] = "yes" if tgram.active else "no"
        self.cfg["TELEGRAM"]["TOKEN"] = tgram.token
        self.cfg["TELEGRAM"]["CHATIDS"] = "[" + ",".join(tgram.chatids) + "]"
        # CAMERAS

        # USER


    def close(self):
        self.copy_db_to_cfg()
        self.db.execute_sql("VACUUM")
        self.db_drop()
        self.db_close()
