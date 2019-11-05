import requests
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import time
import psycopg2


class CianParser():
    yand_api_token = '31a6ed51-bc46-4d1d-9ac9-e3c2e22d2628'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.9; rv:45.0) Gecko/20100101 Firefox/45.0'
    }
    street_names = {
        'ул.': 'улица',
        'пер.': 'переулок',
        'ш.': 'шоссе',
        'просп.': 'проспект',
        'бул.': 'бульвар',
        'деревня': 'деревня'
    }
    months = {
        'января': 1,
        'февраля': 2,
        'марта': 3,
        'апреля': 4,
        'мая': 5,
        'июня': 6,
        'июля': 7,
        'августа': 8,
        'сентября': 9,
        'октября': 10,
        'ноября': 11,
        'декабря': 12
    }
    building_types = {
        'Деревянный': 'WOOD',
        'Кирпичный': 'BRICK',
        'Монолитный': 'MONOLIT',
        'Панельный': 'PANEL',
        'Монолитно-кирпичный': 'MONOLIT_BRICK',
        'Блочный': 'BLOCK'
    }

    def parse_flat_info(self, url):
        page = requests.get(url, headers=self.headers, timeout=3).text
        # print(page)
        soup = BeautifulSoup(page, 'lxml')

        address = soup.find('div', {'class': 'a10a3f92e9--geo--18qoo'}).find('span').get('content').split(',')
        address = [i.strip() for i in address]

        metros_response = soup.find_all('li', {'class': 'a10a3f92e9--underground--kONgx'})
        metros = {}
        for metro in metros_response:
            metros.update({
                metro.find('a').text: metro.find('span').text
            })

        main_info_response = soup.find_all('div', {'class': 'a10a3f92e9--info--2ywQI'})
        main_info = {}
        for info in main_info_response:
            main_info.update({
                info.find('div', {'class': 'a10a3f92e9--info-title--mSyXn'}).text: info.find('div', {
                    'class': 'a10a3f92e9--info-text--2uhvD'}).text
            })

        general_info_response = soup.find_all('li', {'class': 'a10a3f92e9--item--_ipjK'})
        general_info = {}
        for info in general_info_response:
            general_info.update({
                info.find('span', {'class': 'a10a3f92e9--name--3bt8k'}).text: info.find('span', {
                    'class': 'a10a3f92e9--value--3Ftu5'}).text
            })

        building_info_response = soup.find_all('div', {'class': 'a10a3f92e9--item--2Ig2y'})
        building_info = {}
        for info in building_info_response:
            building_info.update({
                info.find('div', {'class': 'a10a3f92e9--name--22FM0'}).text: info.find('div', {
                    'class': 'a10a3f92e9--value--38caj'}).text
            })

        real_price = soup.find('span', {'class': 'a10a3f92e9--price_value--1iPpd'}).find('span').text

        history_prices_response = soup.find_all('tr', {'class': 'price_history_widget-history-event-nK20eRdJ'})
        history_prices = {}
        for info in history_prices_response:
            history_prices.update({
                info.find('td', {'class': 'price_history_widget-event-date-At3o0vWR'}).text:
                    info.find('td', {'class': 'price_history_widget-event-price-1hxoWz1dS'}).text
            })

        # update_time = soup.find('div', {'class': 'a10a3f92e9--container--3nJ0d'}).text

        offer_id = url.split('/')[-2]

        coords_response = requests.get(
            f'https://geocode-maps.yandex.ru/1.x/?apikey={self.yand_api_token}&format=json&geocode={",".join(address)}').text
        coords = \
            json.loads(coords_response)['response']['GeoObjectCollection']['featureMember'][0]['GeoObject']['Point'][
                'pos']
        longitude, latitude = coords.split(' ')

        # -------------------
        # preparation

        for metro, data in metros.items():
            metros.update({
                metro: {
                    'time_to_metro': sum([int(i) if i.isdigit() else 0 for i in data.split(' ')]),
                    'transport_type': 'ON_FOOT' * int('пешком' in data.split(' ')) or 'ON_TRANSPORT'
                }
            })

        city = address[0]
        district = " ".join(address[-3].split(' ')[1:])
        street = []
        for i in address[-2].split(' '):
            if i in self.street_names:
                street.append(self.street_names[i])
            else:
                street.append(i)
        street = ' '.join(street)
        house_number = address[-1]

        full_sq = float(main_info['Общая'].split(' ')[0].replace(',', '.'))
        kitchen_sq = -1
        life_sq = -1
        if 'Жилая' in main_info:
            life_sq = float(main_info['Жилая'].split(' ')[0].replace(',', '.'))
        if 'Кухня' in main_info:
            kitchen_sq = float(main_info['Кухня'].split(' ')[0].replace(',', '.'))

        floor = int(main_info['Этаж'].split(' ')[0])
        max_floor = int(main_info['Этаж'].split(' ')[-1])
        flats_count = -1
        built_year = -1
        if 'Построен' in main_info:
            built_year = int(main_info['Построен'])
        elif 'Год постройки' in building_info:
            built_year = int(building_info['Год постройки'])

        is_apartment = True
        closed = False

        renovation = False
        if 'Ремонт' in general_info:
            renovation = True

        building_type_str = 'UNKNOWN'
        if 'Тип дома' in building_info:
            if building_info['Тип дома'] in self.building_types:
                building_type_str = self.building_types[building_info['Тип дома']]

        has_elevator = False
        if 'Лифты' in building_info:
            if building_info['Лифты'] != 'Нет':
                has_elevator = True

        real_price = [datetime.now(), int(''.join(real_price.split()[:-1]))]
        prices = []
        for date, price in history_prices.items():
            date = date.split(' ')
            if date[0] == 'сегодня':
                day = datetime.now().day
                month = datetime.now().month
            elif date[0] == 'вчера':
                day = (datetime.now() - timedelta(hours=24)).day
                month = (datetime.now() - timedelta(hours=24)).month
            else:
                day = int(date[0])
                month = int(self.months[date[1]])
            time = date[-1]
            if ':' in time:
                hours = int(date[-1].split(':')[0])
                minutes = int(date[-1].split(':')[1])
                prices.append(
                    [datetime(datetime.now().year, month, day, hours, minutes), int(''.join(price.split()[:-1]))])
            else:
                year = int(time)
                prices.append([datetime(year, month, day), int(''.join(price.split()[:-1]))])
        prices.append(real_price)

        if address[0] == 'Москва':
            address = ', '.join(['Россия', city, street, house_number])
        else:
            address = ', '.join(['Россия', address[0], address[1], street, house_number])

        longitude = float(longitude)
        latitude = float(latitude)

        result = {
            'offer_id': offer_id,
            'district': district,
            'address': address,
            'full_sq': full_sq,
            'live_sq': life_sq,
            'kitchen_sq': kitchen_sq,
            'floor': floor,
            'max_floor': max_floor,
            'flats_count': flats_count,
            'built_year': built_year,
            'is_apartment': is_apartment,
            'closed': closed,
            'renovation': renovation,
            'building_type_str': building_type_str,
            'has_elevator': has_elevator,
            'prices': prices,
            'metros': metros,
            'longitude': longitude,
            'latitude': latitude
        }

        return result

    def save_to_db(self, flat):
        conn = psycopg2.connect(host='localhost', dbname='video_analytics', user='va', password='theorema')
        cur = conn.cursor()

        cur.execute('select id from districts where name={};'.format(flat.district))
        district_id = cur.fetchone()

        metro_ids = {}
        for metro in flat.metros:
            cur.execute('select id from metros where name={};'.format(metro))
            metro_ids.update({metro: cur.fetchone()})

        cur.execute('select * from buildings where address={};'.format(flat.address))
        is_building_exist = cur.fetchone()
        if not building:
            cur.execute(
                'insert into buildings values ({max_floor}, {building_type_str}, {built_year}, {flats_count}, {address}, {renovation}, {has_elevator}, {longitude}, {latitude}, {district_id}, {created_at}, {updated_at});'.format(
                    flat['max_floor'], flat['building_type_str'], flat['built_year'], flat['flats_count'],
                    flat['address'], flat['renovation'], flat['has_elevator'], flat['longitude'], flat['latitude'],
                    district_id)
            )
            cur.execute('select id from buildings where address={};'.format(flat['addres']))
            building_id = cur.fetchone()
            for metro, metro_id in metro_ids.items():
                cur.execute(
                    'insert into time_metro_buildings values ({building_id}, {metro_id}, {time_to_metro}, {transport_type}, {created_at}, {updated_at});'.format(
                        building_id, metro_id, flat['metros'][metro]['time_to_metro'],
                        flat['metros'][metro]['transport_type']
                    ))

        cur.execute('select * from flats where offer_id={}'.format(flat['offer_id']))
        is_offer_exist = cur.fetchone()
        if not is_offer_exist:
            cur.execute(
                'insert into flats values ({full_sq}, {kitchen_sq}, {life_sq}, {floor}, {is_apartment}, {building_id}, {created_at}, {updated_at}, {offer_id}, {closed})'.format(
                    flat['full_sq'], flat['kitchen_sq'], flat['life_sq'], flat['floor'], flat['is_apartment'],
                    flat['building_id'], flat['created_at'], flat['updated_at'], flat['offer_id'], flat['closed']
                ))

    def get_flats_url(self, url):
        response = requests.get(url, self.headers, timeout=3).text
        soup = BeautifulSoup(response, 'lxml')
        pages_response = soup.find_all('a', {'class': 'c6e8ba5398--header--1fV2A'})
        pages_url = [page.get('href') for page in pages_response]

        next_page_response = soup.find('ul', {'class': '_93444fe79c--list--HEGFW'}).find_all('li')
        my_page = soup.find('li', {'class': '_93444fe79c--list-item--2KxXr _93444fe79c--list-item--active--3dOSi'})
        if my_page == next_page_response[-1]:
            next_page_number = 0
        else:
            next_page_number = int(my_page.find('span').text) + 1

        return pages_url, next_page_number

    def get_setOfPages_url(self, url):
        all_urls = []
        page_number = 1
        next_page_number = 1
        while (page_number == next_page_number):
            res_url = url.format(page_number)
            page_number += 1
            new_urls, next_page_number = self.get_flats_url(res_url)
            all_urls += new_urls
            print(new_urls)

            time.sleep(2)
        print(len(all_urls))

        return all_urls

    def parse(self, url):
        urls = self.get_setOfPages_url(url)
        print(*urls, sep='\n')
        count = 0
        for url in urls:
            try:
                result = self.parse_flat_info(url)
                print(result)
                self.save_to_db(result)
                time.sleep(2)
            except:
                print('fail ', url)
            count += 1

        print('end ', count)


parser = CianParser()
parser.parse(
    'https://www.cian.ru/cat.php?deal_type=sale&engine_version=2&offer_type=flat&p={}&region=1&room1=1&room2=1')
