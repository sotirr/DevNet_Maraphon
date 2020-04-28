'''
Файл конфигурации.
Все параметры сначала ищутся как параметры окружения
и если их не находит, то подставляет значения по умолчанию
'''
import os

basedir = os.path.abspath(os.path.dirname(__file__))


# директория где лежит инвентарный файл
inv_path = os.environ.get('INV_DIR') or basedir
# название инвентарного файла
inv_file = os.environ.get('INV_FILE') or 'devices.csv'

# Директория для сохранения бекапов
backup_path = os.environ.get('BACKUP_DIR') or f'{basedir}\\backup'

# адрес NTP сервера
ntp_server = os.environ.get('NTP_SERVER') or '192.168.0.1'
