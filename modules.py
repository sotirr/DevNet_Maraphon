from datetime import datetime
from netmiko import ConnectHandler
from netmiko import NetMikoTimeoutException, NetMikoAuthenticationException
from config import inv_path, inv_file, backup_path, ntp_server
from time import sleep
from itertools import repeat
import csv
import os
import logging
import ntplib
import socket


def _normalized_name(hostname):
    '''
    возвращаем название файла бекапа
    '''
    time = datetime.now().strftime('%d-%m-%y_%H-%M')
    return f'{hostname}_{time}'


def _check_dir(dir_name):
    '''
    Проверяет наличие каталогов в backup_path и если не находит то создает
    На вход ждет имя каталога, возвращает абсолютный путь до каталога.
    '''
    if not (os.path.exists(backup_path)):
        os.mkdir(backup_path)
    abs_path = f'{backup_path}\\{dir_name}'
    if not (os.path.exists(abs_path)):
        os.mkdir(abs_path)
    return abs_path


def _save_backup(ssh, hostname):
    '''
    Создает бекап конфигурации.
    На вход ждет соединение и имя устройства
    '''
    logging.info(f'backup {hostname} config start')

    bckp_abs_path = _check_dir(hostname)
    bckp_name = _normalized_name(hostname)
    bckp_data = ssh.send_command('sh run\n')
    with open(f'{bckp_abs_path}\\{bckp_name}', 'w') as bckp_file:
        bckp_file.writelines(bckp_data)

    logging.info(f'backup {hostname} config complite')


def _check_cdp(ssh, hostname):
    '''
    Проверяет запущен ли CDP на устройстве.
    Возвращает статус протокола CDP и количество соседей
    если протокол запущен.
    '''
    logging.info(f'Checking CDP on {hostname}')

    command_out = ssh.send_command('sh cdp neighbors\n')

    if '%' in command_out:
        return 'CDP is OFF'
    # Берем последний элемент последней строки
    neighbors_count = command_out.split('\n')[-1].split()[-1]
    return f'CDP is ON, {neighbors_count} peers'


def _check_ios(ssh, hostname):
    '''
    Парсим команду sh ver
    Всю нужную информацию содержит первая строка вывода
    поэтому проще использовать методы строк хоть и менее наглядно.

    Возвращаем кортеж из трех элементов:
    (Модель, версия IOS, PE или NPE)
    '''
    logging.info(f'Checking IOS on {hostname}')
    # Берем первую строчку из вывода комманды sh ver
    command_out = ssh.send_command('sh ver\n').split('\n')[0]
    # превращаем строку в список по разделителю <,>
    output_split = command_out.split(',')
    # Вытаскиваем нужную нам информацию
    model = output_split[1].strip().split()[0]
    ios = output_split[1].strip().split()[-1]
    ios_ver = output_split[2].strip().split()[1]
    # Проверяем является ли образ PE
    check_pe = 'NPE' if 'npe' in ios.lower() else 'PE'

    return (model, ios_ver, check_pe)


def _ping_ntp(ssh, hostname, ntp_server):
    '''
    Проверяем доступность NTP сервера с устройства.
    Возвращаем True если доступен
    '''
    result = ssh.send_command(f'ping {ntp_server}\n')
    if '.....' in result:
        logging.error(f'NTP сервер недоступен на {hostname}')
        return False
    else:
        return True


def _command_in_config(ssh, commands):
    '''
    Возвращаем список команд, которых еще нет в конфигурации
    '''
    run_config = ssh.send_command('sh run\n')
    result = []
    for command in commands:
        if command not in run_config:
            result.append(command)
        return result


def _config_ntp(ssh, hostname, ntp_server):
    '''
    Настраиваем NTP сервер
    '''
    commands = ['clock timezone GMT 0',
                f'ntp server {ntp_server} version 3']
    commands_for_config = _command_in_config(ssh, commands)
    # проверяем что команд еще нету в конфигурации
    if commands_for_config:
        # Проверяем доступность сервера
        if _ping_ntp(ssh, hostname, ntp_server):
            logging.info(f'config ntp server on {hostname}')
            result = ssh.send_config_set(commands)
            ssh.send_command('write')
            return result


def _check_ntp_sync(ssh, hostname):
    '''
    Проверяем статус синхронизации
    '''
    logging.info(f'Checking NTP sync on {hostname}')
    # Форсируем синхронизацию времени
    ssh.send_command('clock read-calendar')
    sleep(3)
    result = ssh.send_command('sh ntp associations\n')
    return 'Clock in Sync' if f'*~{ntp_server}' in result else 'Not Sync'


def connect_to_device(device, backup=False, check_cdp=False,
                      check_ios=False, ntp_server=None):
    logging.info(f'Connection to device: {device["hostname"]}')
    device_params = {'device_type': device['device_type'],
                     'ip': device['ip'],
                     'username': device['username'],
                     'password': device['password'],
                     'secret': device['secret'],
                     }
    model, ios_ver, check_pe, cdp_status, ntp_sync_status = repeat('None', 5)

    try:
        with ConnectHandler(**device_params) as ssh:
            ssh.enable()
            if backup:
                _save_backup(ssh, device['hostname'])
            if check_cdp:
                cdp_status = _check_cdp(ssh, device['hostname'])
            if check_ios:
                model, ios_ver, check_pe = _check_ios(ssh, device['hostname'])
            if ntp_server:
                _config_ntp(ssh, device['hostname'], ntp_server)
                ntp_sync_status = _check_ntp_sync(ssh, device['hostname'])
    except (NetMikoAuthenticationException, NetMikoTimeoutException) as err:
        logging.error(err)

    result = {'hostname': device['hostname'], 'model': model,
              'ios_ver': ios_ver, 'check_pe': check_pe,
              'cdp_status': cdp_status, 'ntp_sync_status': ntp_sync_status}
    return result


def check_ntp_server(ntp_server):
    '''
    Проверяем валидность DNS Сервера
    '''
    ntp = ntplib.NTPClient()
    try:
        ntp.request(ntp_server)
        return True
    except (ntplib.NTPException, socket.timeout, socket.gaierror) as err:
        logging.error(err)
        return False


def make_report(data):
    '''
    Создаем отчет.
    На вход ждем список словарей с информацией о оборудовании.
    Формат:
    [{'hostname': hostname, 'model': model, 'ios_ver': ios_ver,
      'check_pe': check_pe, 'cdp_status':cdp_status,
      'ntp_sync_status': ntp_sync_status}]
    На выходе создается csv файл с заголовками из ключей.
    '''
    headers = ['hostname', 'model', 'ios_ver',
               'check_pe', 'cdp_status', 'ntp_sync_status']
    with open('report.csv', 'w', newline='') as rep_file:
        writer = csv.DictWriter(rep_file, delimiter=';', fieldnames=headers)
        writer.writeheader()
        for row in data:
            writer.writerow(row)


def inventory():
    '''
    Читает инвентарный файл csv и возвращает список в котором
    элементы это отдельные устройства, описанные в виде OrderedDict

    Ожидаемый формат CSV:
    hostname;ip;username;password;secret;device_type
    '''
    with open(f'{inv_path}\\{inv_file}', 'r') as file:
        inv_dict = csv.DictReader(file, delimiter=';')
        result = list(inv_dict)
    return result


if __name__ == '__main__':
    pass
