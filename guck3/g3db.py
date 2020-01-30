from guck3.mplogging import whoami
import pickle
import time

'''class G3DB():

    def __init__(self, mplock, cfg, dirs, logger):
        self.logger = logger
        self.cfg = cfg
        self.lock = mplock
        self.dirs = dirs
        self.db_file_name = dirs["main"] + "guck3.db"
        self.db = SqliteDatabase(self.db_file_name)

        class BaseModel(Model):
            class Meta:
                database = self.db

        class USER(BaseModel):
            username = CharField()
            password = CharField()

        # for webflask status tracking
        class USERDATA(BaseModel):
            username = CharField()
            active = BooleanField()
            lasttm = FloatField()
            no_newdetections = IntegerField()
            photolist = PickleField()

        class OPTIONS(BaseModel):
            loglevel = CharField()
            showframes = BooleanField()
            retinanet_model = CharField()
            storephotos = BooleanField()
            addtl_photo_path = CharField()
            keyboard_active = BooleanField()
            redis_host = CharField()
            redis_port = IntegerField()

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
        self.USERDATA = USERDATA
        self.tablelist = [self.USER, self.CAMERA, self.OPTIONS, self.TELEGRAM, self.USERDATA]

        self.db.connect()
        self.db.create_tables(self.tablelist)

        self.SQLITE_MAX_VARIABLE_NUMBER = int(max_sql_variables() / 4)
        self.logger.debug(whoami() + "SQLITE_MAX_VARIABLE_NUMBER = " + str(self.SQLITE_MAX_VARIABLE_NUMBER))

        self.copy_cfg_to_db()

    # ---- USERS ------
    def get_users(self):
        user_conf = {}
        with self.lock:
            for u in self.USER:
                user_conf[u.username] = u.password
        if user_conf == {}:
            return None
        return user_conf

    # ---- USERDATA ------
    def get_userdata(self):
        userdata = {}
        with self.lock:
            for ud in self.USERDATA:
                userdata[ud.username] = {}
                userdata[ud.username]["active"] = ud.active
                userdata[ud.username]["lasttm"] = ud.lasttm
                userdata[ud.username]["no_newdetections"] = ud.no_newdetections
                userdata[ud.username]["photolist"] = ud.photolist
        if userdata == {}:
            return None
        return userdata

    def insert_new_userdata(self, username, lasttm, active, no_newdetections, photolist):
        try:
            with self.lock:
                self.USERDATA.create(username=username, lasttm=lasttm, active=active, no_newdetections=no_newdetections,
                                     photolist=photolist)
        except Exception as e:
            self.logger.warning(whoami() + str(e) + ": cannot insert USERDATA")

    def update_userdata(self, username, lasttm, active, no_newdetections, photolist):
        try:
            with self.lock:
                query = self.USERDATA.update(lasttm=lasttm, active=active, no_newdetections=no_newdetections,
                                             photolist=photolist).where(self.USERDATA.username == username)
                query.execute()
                return 1
        except Exception as e:
            self.logger.warning(whoami() + str(e) + ": cannot update USERDATA")
            return -1

    # ---- CAMERA ------
    def get_cameras(self):
        camera_conf = []
        with self.lock:
            for c in self.CAMERA:
                cdata = {
                        "name": c.name,
                        "active": c.active,
                        "stream_url": c.stream_url,
                        "photo_url": c.photo_url,
                        "reboot_url": c.reboot_url,
                        "ptz_mode": c.ptz_mode,
                        "ptz_right_url": c.ptz_right_url,
                        "ptz_left_url": c.ptz_left_url,
                        "ptz_up_url": c.ptz_up_url,
                        "ptz_down_url": c.ptz_down_url,
                        "min_area_rect": c.min_area_rect,
                        "hog_scale": c.hog_scale,
                        "hog_thresh": c.hog_thresh,
                        "mog2_sensitivity": c.mog2_sensitivity,
                    }
                camera_conf.append(cdata)
        if not camera_conf:
            return None
        return camera_conf

    # ---- OPTIONS ------
    def get_options(self):
        with self.lock:
            o = self.OPTIONS.select()[0]
        res = {"loglevel": o.loglevel, "showframes": o.showframes, "retinanet_model": o.retinanet_model,
               "storephotos": o.storephotos, "addtl_photo_path": o.addtl_photo_path,
               "keyboard_active": o.keyboard_active, "redis_host": o.redis_host, "redis_port": o.redis_port}
        return res

    # ---- TELEGRAM ------
    def get_telegram(self):
        with self.lock:
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
            redis_host = self.cfg["OPTIONS"]["REDIS_HOST"]
        except Exception:
            redis_host = "127.0.0.1"
        try:
            redis_port = int(self.cfg["OPTIONS"]["REDIS_PORT"])
        except Exception:
            redis_port = 6379
        try:
            keyboard_active = True if self.cfg["OPTIONS"]["KEYBOARD_ACTIVE"].lower() == "yes" else False
        except Exception:
            keyboard_active = False
        try:
            loglevel = self.cfg["OPTIONS"]["LOGLEVEL"].lower()
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
            if addtl_photo_path.lower() == "none" or not os.path.exists(addtl_photo_path):
                addtl_photo_path = "None"
            elif addtl_photo_path[-1] != "/":
                addtl_photo_path += "/"
        except Exception:
            addtl_photo_path = "None"
        try:
            with self.lock:
                self.OPTIONS.create(loglevel=loglevel, showframes=showframes, retinanet_model=retinanet_model,
                                    storephotos=storephotos, addtl_photo_path=addtl_photo_path,
                                    keyboard_active=keyboard_active, redis_host=redis_host, redis_port=redis_port)
        except Exception:
            self.copyok = False
            return
        self.logger.debug(whoami() + "options data copied to db")
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
            return
        self.logger.debug(whoami() + "telegram data copied to db")

    def copy_db_to_cfg(self):
        if not self.copyok:
            return
        # OPTIONS
        with self.lock:
            options = self.OPTIONS.select()[0]
        self.cfg["OPTIONS"]["LOGLEVEL"] = options.loglevel
        self.cfg["OPTIONS"]["SHOWFRAMES"] = "yes" if options.showframes else "no"
        self.cfg["OPTIONS"]["RETINANET_MODEL"] = options.retinanet_model
        self.cfg["OPTIONS"]["STOREPHOTOS"] = "yes" if options.storephotos else "no"
        self.cfg["OPTIONS"]["ADDTL_PHOTO_PATH"] = options.addtl_photo_path
        self.cfg["OPTIONS"]["KEYBOARD_ACTIVE"] = "yes" if options.keyboard_active else "no"
        self.cfg["OPTIONS"]["REDIS_HOST"] = options.redis_host
        self.cfg["OPTIONS"]["REDIS_PORT"] = str(options.redis_port)
        self.logger.debug(whoami() + "options copied to DB")
        # TELEGRAM
        with self.lock:
            tgram = self.TELEGRAM.select()[0]
        self.cfg["TELEGRAM"]["ACTIVE"] = "yes" if tgram.active else "no"
        self.cfg["TELEGRAM"]["TOKEN"] = tgram.token
        self.cfg["TELEGRAM"]["CHATIDS"] = "[" + ",".join([str(ci) for ci in tgram.chatids]) + "]"
        self.logger.debug(whoami() + "telegram data copied to DB")
        # CAMERAS
        with self.lock:
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
        self.logger.debug(whoami() + "camera data copied to DB")
        # USER
        with self.lock:
            users = self.USER.select()
        for i, u in enumerate(users, start=1):
            ustr = "USER" + str(i)
            self.cfg[ustr]["USERNAME"] = u.username
            self.cfg[ustr]["PASSWORD"] = u.password
        self.logger.debug(whoami() + "user data copied to DB")
        # write to cfg_file
        cfg_file = self.dirs["main"] + "guck3.config"
        try:
            with open(cfg_file, "w") as f:
                self.cfg.write(f)
        except Exception as e:
            self.logger.error(whoami() + str(e) + ". cannot write db to config file!")
            return -1
        return 1

    def closeall(self):
        self.logger.info(whoami() + "starting db closeall procedure ...")
        self.copy_db_to_cfg()
        c = self.USERDATA.delete()
        c.execute()
        c = self.CAMERA.delete()
        c.execute()
        o = self.OPTIONS.delete()
        o.execute()
        t = self.TELEGRAM.delete()
        t.execute()
        self.db.drop_tables(self.tablelist)
        self.db.close()
        self.logger.info(whoami() + "... closeall procedure done!")'''


# --------------- REDIS API -------------------

class RedisAPI:
    def __init__(self, red, dirs, cfg, logger):
        self.red = red
        self.cfg = cfg
        self.dirs = dirs
        self.logger = logger
        self.copyok = True
        if not self.getp("g3_userdata"):
            self.setp("g3_userdata", {})
        if not self.getp("g3_photodata"):
            self.setp("g3_photodata", [])
        if not self.getp("g3_userdata_last_updated"):
            self.setp("g3_userdata_last_updated", 0)
        if not self.getp("g3_new_detections"):
            self.setp("g3_new_detections", 0)
        if not self.getp("g3_hoststatus"):
            self.setp("g3_hoststatus", None)
        self.copy_users_to_redis()
        self.copy_cameras_to_redis()
        self.setp("g3_putcmd", "")

    def setp(self, key, value):
        try:
            ret = self.red.set(key, pickle.dumps(value))
            return ret
        except Exception:
            return False

    def getp(self, key):
        try:
            ret = pickle.loads(self.red.get(key))
            return ret
        except Exception:
            return None

    def set_host_status(self, status):
        self.setp("g3_hoststatus", status)

    def get_host_status(self):
        return self.getp("g3_hoststatus")

    def set_putcmd(self, cmd):
        self.setp("g3_putcmd", cmd)

    def get_putcmd(self):
        ret = self.getp("g3_putcmd")
        self.setp("g3_putcmd", "")
        return ret

    def copy_redis_to_cameras_cfg(self):
        self.logger.debug(whoami() + "copying redis camera data to config ...")
        cameras = self.getp("g3_cameras")
        for i, c in enumerate(cameras, start=1):
            cstr = "CAMERA" + str(i)
            self.cfg[cstr]["ACTIVE"] = "yes" if c[0] else "no"
            self.cfg[cstr]["NAME"] = c[1]
            self.cfg[cstr]["STREAM_URL"] = c[2]
            self.cfg[cstr]["PHOTO_URL"] = c[3]
            self.cfg[cstr]["REBOOT_URL"] = c[4]
            self.cfg[cstr]["PTZ_MODE"] = c[5]
            self.cfg[cstr]["PTZ_RIGHT_URL"] = c[6]
            self.cfg[cstr]["PTZ_LEFT_URL"] = c[7]
            self.cfg[cstr]["PTZ_UP_URL"] = c[8]
            self.cfg[cstr]["PTZ_DOWN_URL"] = c[9]
            self.cfg[cstr]["MIN_AREA_RECT"] = str(c[10])
            self.cfg[cstr]["HOG_SCALE"] = str(c[11])
            self.cfg[cstr]["HOG_THRESH"] = str(c[12])
            self.cfg[cstr]["MOG2_SENSITIVITY"] = str(c[13])
        # write to cfg_file
        cfg_file = self.dirs["main"] + "guck3.config"
        try:
            with open(cfg_file, "w") as f:
                self.cfg.write(f)
        except Exception as e:
            self.logger.error(whoami() + str(e) + ", cannot write redis to config file!")
            return -1
        self.logger.debug(whoami() + "... redis camera data copied to config!")
        return 1

    def copy_cameras_to_redis(self):
        self.logger.debug(whoami() + "copying camera data to redis ...")
        self.setp("g3_cameras", [])
        cameralist = []
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
                cameralist.append((active, camera_name, stream_url, photo_url, reboot_url, ptz_mode, ptz_right_url,
                                  ptz_left_url, ptz_up_url, ptz_down_url, min_area_rect, hog_scale, hog_thresh,
                                  mog2_sensitivity))
            except Exception:
                break
            idx += 1
        if idx == 1:
            self.copyok = False
            return
        self.setp("g3_cameras", cameralist)
        self.logger.debug(whoami() + " ... camera data copied to redis!")

    def get_cameras(self):
        camera_conf = []
        cameralist = self.getp("g3_cameras")
        for c in cameralist:
            cdata = {
                    "name": c[1],
                    "active": c[0],
                    "stream_url": c[2],
                    "photo_url": c[3],
                    "reboot_url": c[4],
                    "ptz_mode": c[5],
                    "ptz_right_url": c[6],
                    "ptz_left_url": c[7],
                    "ptz_up_url": c[8],
                    "ptz_down_url": c[9],
                    "min_area_rect": c[10],
                    "hog_scale": c[11],
                    "hog_thresh": c[12],
                    "mog2_sensitivity": c[13]
                }
            camera_conf.append(cdata)
        if not camera_conf:
            return None
        return camera_conf

    def copy_users_to_redis(self):
        self.setp("g3_users", {})
        idx = 1
        users = {}
        while True:
            str0 = "USER" + str(idx)
            try:
                username = self.cfg[str0]["USERNAME"]
                password = self.cfg[str0]["PASSWORD"]
                users[username] = password
            except Exception:
                break
            idx += 1
        if idx == 1:
            self.copyok = False
            return
        self.setp("g3_users", users)
        self.logger.debug(whoami() + "user data copied to db")

    def get_photodata(self):
        return self.getp("g3_photodata")

    def insert_photodata(self, photonames):
        photodata = self.getp("g3_photodata")
        for p in photonames:
            photodata.insert(0, p)
            if len(photodata) > 15:
                del photodata[-1]
        self.setp("g3_photodata", photodata)

    def get_users(self):
        return self.getp("g3_users")

    def get_userdata(self):
        return self.getp("g3_userdata")

    def get_userdata_last_updated(self):
        return self.getp("g3_userdata_last_updated")

    def user_in_userdata(self, username):
        userdata = self.getp("g3_userdata")
        return userdata, (len([1 for key in userdata if key == username]) > 0)

    def insert_update_userdata(self, username, lasttm, active, no_newdetections, photolist):
        try:
            userdata, user_in_userdata = self.user_in_userdata(username)
            if not user_in_userdata:
                userdata[username] = {}
            userdata[username]["lastttm"] = lasttm
            userdata[username]["active"] = active
            userdata[username]["no_newdetections"] = no_newdetections
            userdata[username]["photolist"] = photolist
            self.setp("g3_userdata", userdata)
            self.setp("g3_userdata_last_updated", time.time())
        except Exception as e:
            self.logger.warning(whoami() + str(e))
