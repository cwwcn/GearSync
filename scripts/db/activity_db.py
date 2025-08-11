import os
from db.sqlite_db import SqliteDB
from conf.config import DB_DIR


class ActivityDB:

    def __init__(self, db_name):
        ## Garmin数据库
        self._db_name = db_name

    @property
    def db_name(self):
        return self._db_name

    ## 保存Stryd运动信息
    def saveActivity(self, id, source='garmin', target='garmin'):
        exists_select_sql = 'SELECT * FROM activity_table WHERE activity_id = ? AND activity_source = ? AND activity_target = ?'
        with SqliteDB(self._db_name) as db:
            exists_query_set = db.execute(exists_select_sql, (id, source, target)).fetchall()
            query_size = len(exists_query_set)
            if query_size == 0:
                db.execute(
                    'INSERT INTO activity_table (activity_id, activity_source, activity_target) VALUES (?, ?, ?)',
                    (id, source, target))

    def getUnSyncActivity(self, source='garmin', target='garmin'):
        select_un_upload_sql = 'SELECT activity_id FROM activity_table WHERE is_sync = 0 AND activity_source = ? AND activity_target = ?'
        with SqliteDB(self._db_name) as db:
            un_upload_result = db.execute(select_un_upload_sql, (source, target)).fetchall()  # 注意：一个值时需要有最后面的,
            query_size = len(un_upload_result)
            if query_size == 0:
                return None
            else:
                activity_id_list = []
                for result in un_upload_result:
                    activity_id_list.append(result[0])
                return activity_id_list

    def updateSyncStatus(self, id: int, source: str = 'garmin', target='garmin'):
        update_sql = "update activity_table set is_sync = 1 WHERE activity_id = ? AND activity_source = ? AND activity_target = ?"
        with SqliteDB(self._db_name) as db:
            db.execute(update_sql, (id, source, target))

    def updateExceptionSyncStatus(self, id: int, source: str = 'garmin', target='garmin'):
        update_sql = "update activity_table set is_sync = 2 WHERE activity_id = ? AND activity_source = ? AND activity_target = ?"
        with SqliteDB(self._db_name) as db:
            db.execute(update_sql, (id, source, target))

    def initDB(self):
        with SqliteDB(os.path.join(DB_DIR, self._db_name)) as db:
            # 创建表
            db.execute('''
                      CREATE TABLE activity_table(
                          id INTEGER NOT NULL PRIMARY KEY  AUTOINCREMENT ,
                          activity_source VARCHAR(50) NOT NULL DEFAULT 'garmin' ,
                          activity_target VARCHAR(50) NOT NULL,
                          activity_id INTEGER NOT NULL  , 
                          is_sync INTEGER NOT NULL  DEFAULT 0,
                          create_time TIMESTAMP DEFAULT (datetime('now', '+8 hours')),
                          update_time TIMESTAMP DEFAULT (datetime('now', '+8 hours'))
                      ) 
                    ''')

            # 创建更新触发器，同时更新 create_time 和 update_time 字段
            db.execute('''
                      CREATE TRIGGER IF NOT EXISTS update_activity_table_time 
                      AFTER UPDATE ON activity_table 
                      FOR EACH ROW 
                      BEGIN 
                        UPDATE activity_table SET create_time = datetime('now', '+8 hours'), 
                                                 update_time = datetime('now', '+8 hours') 
                        WHERE id = OLD.id;
                      END;
                    ''')
