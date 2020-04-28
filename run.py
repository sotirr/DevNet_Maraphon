from concurrent.futures import ThreadPoolExecutor
from functools import partial
from modules import check_ntp_server, inventory, connect_to_device, make_report
from config import ntp_server
import logging


if __name__ == '__main__':

    logging.basicConfig(format='%(levelname)s: %(message)s',
                        level=logging.INFO)
    logging.getLogger('paramiko').setLevel(logging.WARNING)

    # Проверяем корректность NTP сервера
    if not check_ntp_server(ntp_server):
        logging.error('Поправьте NTP сервер')
        exit()
    # определяем задачи которые надо запускать
    static_params = {'backup': True,
                     'check_cdp': True,
                     'check_ios': True,
                     'ntp_server': ntp_server}

    # получаем список девайсов из csv
    devices = inventory()

    # запускаем подключение к устройствам в разных thread
    connect_to_device = partial(connect_to_device, **static_params)
    with ThreadPoolExecutor(max_workers=4) as executor:
        result = executor.map(connect_to_device, devices)

    # формируем отчет
    make_report(result)
