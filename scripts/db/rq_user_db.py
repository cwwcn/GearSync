import os
from db.sqlite_db import SqliteDB


class RQUserDB:
    def __init__(self, db_path):
        self.db_path = db_path

    def get_user_by_email(self, encrypted_email):
        """
        根据加密邮箱查询用户信息
        """
        with SqliteDB(self.db_path) as db:
            return db.execute('SELECT * FROM user_info WHERE email=?', (encrypted_email,)).fetchall()

    def delete_user_by_id(self, user_id):
        """
        根据用户ID删除用户信息
        """
        with SqliteDB(self.db_path) as db:
            db.execute('DELETE FROM user_info WHERE id = ?', (user_id,))

    def update_user_login_time(self, encrypted_email):
        """
        更新用户登录时间
        """
        with SqliteDB(self.db_path) as db:
            db.execute('''UPDATE user_info SET update_date = datetime('now','localtime') WHERE email = ?''',
                       (encrypted_email,))

    def init_database(self):
        """
        初始化数据库表
        """
        with SqliteDB(self.db_path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS user_info (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    email VARCHAR(100), user_id  VARCHAR(100),
                    access_token VARCHAR(100),
                    create_date TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                    update_date TIMESTAMP DEFAULT (datetime('now', 'localtime'))
                    )''')
