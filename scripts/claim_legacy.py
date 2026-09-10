"""Assign previously unowned knowledge bases to an existing account, locally only."""
import argparse
import sqlite3
from datetime import datetime
from app.core.config import get_settings
from app.runtime import get_store, resolve_project_path


def main():
    parser = argparse.ArgumentParser(description='将旧版无归属知识库分配给指定账号（先备份）')
    parser.add_argument('username')
    args = parser.parse_args()
    path = resolve_project_path(get_settings().database_path)
    backup = path.with_name(path.stem+'.before-claim-'+datetime.now().strftime('%Y%m%d%H%M%S%f')+'.sqlite3')
    if path.exists():
        with sqlite3.connect(path) as src, sqlite3.connect(backup) as dst:
            src.backup(dst)
        print('迁移前备份：',backup)
    print('分配知识库数量：',get_store().claim_legacy(args.username))
    print('旧版 messages 原样保留；因其缺少可靠的知识库归属，不自动导入新会话。')


if __name__ == '__main__':
    main()
