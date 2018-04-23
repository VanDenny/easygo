import requests
from multiprocessing.dummy import Pool as ThreadPool
import sys
from selenium import webdriver
import time
from Clawer_Base.shape_io import Shapefile_Reader
from Clawer_Base.email_alerts import Email_alarm
from Clawer_Base import transCoordinateSystem
from Clawer_Base.cyclic_scheduler import Cycle_Scheduler
from Clawer_Base.clawer_frame import Clawer
from Clawer_Base.logger import logger
from Clawer_Base.user_agents import User_agents
from Clawer_Base.geo_lab import Sample_Generator
import traceback
from Clawer_Base.ioput import Res_saver
import datetime
import pandas as pd

def account_reader(file_path):
    df = pd.read_excel(file_path)
    account_dict = df.to_dict(orient='records')
    return account_dict


class CookieException(Exception):
    def __init__(self, err = 'Cookie错误'):
        Exception.__init__(self, err)


class Easygo_Params(dict):
    """将传入的块转化为网页所需的表单"""
    params = {"lng_min": '',
              "lat_max": '',
              "lng_max": '',
              "lat_min": '',
              "level": 16,
              "city": '',
              "lat": '',
              "lng": '',
              "_token": ""}
    def __init__(self, rect, city):
        city_dict = {"city": city}
        self.rect = rect
        self.update(self.params)
        self.update(city_dict)
        self.update(self.rect_to_dict(rect))

    def rect_to_dict(self,rect):
        a_dict = {}
        a_dict['lng_min'] = rect.left_down.lng
        a_dict['lng_max'] = rect.right_up.lng
        a_dict['lat_min'] = rect.left_down.lat
        a_dict['lat_max'] = rect.right_up.lat
        a_dict['lng'] = rect.center.lng
        a_dict['lat'] = rect.center.lat
        return a_dict


class Easygo_Clawer(Clawer):
    req_num = 0
    account_list = account_reader('D:\program_lib\QQ_Tool\qq_pool.xlsx')
    used_account = []
    cookies = {}
    def __init__(self, params):
        super(Easygo_Clawer, self).__init__(params)
        self.referer = {"Referer": "http://c.easygo.qq.com/eg_toc/map.html?origin=csfw"}
        self.headers.update(self.referer)
        self.url = "http://c.easygo.qq.com/api/egc/heatmapdata"
        self.cookies = Easygo_Clawer.cookies
        # print(self.cookies)

    def scheduler(self):
        if self.req_num == 0:
            self.status_change_cookies()
            # print(self.cookies)
            Easygo_Clawer.req_num += 1
        elif self.req_num <= 100:
            self.requestor()
            Easygo_Clawer.req_num += 1
        else:
            self.status_change_cookies()
            Easygo_Clawer.req_num = 1

    def process(self):
        self.scheduler()
        return self.parser(self.respond)

    def status_change_user_agent(self):
        self.headers = User_agents().get_headers()
        self.headers.update(self.referer)
        self.requestor()


    def parser(self, json_dict):
        print(json_dict)
        datas = json_dict.get('data')
        if isinstance(datas, list) and len(datas)!=0:
            points = []
            min_count = datas[0]['count']
            for i in datas:
                min_count = min(i['count'], min_count)
            for i in datas:
                point = {}
                gcj_lng = 1e-6 * (250.0 * i['grid_x'] + 125.0)
                gcj_lat = 1e-6 * (250.0 * i['grid_y'] + 125.0)
                point['gcj_lng'] = gcj_lng  # 此处的算法在宜出行网页后台的js可以找到，文件路径是http://c.easygo.qq.com/eg_toc/js/map-55f0ea7694.bundle.js
                point['gcj_lat'] = gcj_lat
                point['lng'], point['lat'] = transCoordinateSystem.gcj02_to_wgs84(gcj_lng, gcj_lat)
                point['count'] = i['count'] / min_count
                point['req_time'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                points.append(point)
            Easygo_Clawer.cookies = self.cookies
            return points
        elif isinstance(datas, list) and len(datas) == 0:
            print("此区域没有点信息")
            logger.info("此区域没有点信息 %s" % self.req_url)
        elif isinstance(datas, str):
            time.sleep(3)
            self.cookies = self.get_cookie()
            points = self.process()
            Easygo_Clawer.req_num = 1
            return points
        else:
            print(json_dict)
            logger.info('%s 链接是 %s' % (json_dict, self.req_url))

    def read_account(self, file_path):
        df = pd.read_excel(file_path)
        account_list = df.to_dict(orient='records')
        return account_list



    def get_cookie(self):
        if self.account_list:
            account = Easygo_Clawer.account_list.pop()
            chrome_login = webdriver.Chrome()
            def login():
                chrome_login.get("http://c.easygo.qq.com/eg_toc/map.html?origin=csfw&cityid=110000")
                chrome_login.find_element_by_id("u").send_keys(account['account'])
                chrome_login.find_element_by_id("p").send_keys(account['password'])
                chrome_login.find_element_by_id("go").click()
            try:
                login()
            except:
                time.sleep(2)
                login()
            time.sleep(3)
            cookies = chrome_login.get_cookies()
            chrome_login.quit()
            user_cookie = {}
            for cookie in cookies:
                user_cookie[cookie["name"]] = cookie["value"]
            account['date'] = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            Easygo_Clawer.used_account.append(account)
            time.sleep(2)
            return user_cookie
        else:
            new_df = pd.DataFrame(Easygo_Clawer.used_account)
            new_df.to_excel('D:\program_lib\QQ_Tool\qq_pool.xlsx')
            raise CookieException('今日账号已用完')


def view_bar(num, total):
    rate = float(num) / float(total)
    rate_num = int(rate * 100)
    r = '\r[%s%s]%d%%' % ("="*(rate_num+1), " "*(100-rate_num-1), rate_num, )
    sys.stdout.write(r)


def main(region_name, origin_rect):
    name = region_name
    sample_generator = Sample_Generator(name)
    sample_generator.filter_radius([origin_rect], 4000)
    rect_list = sample_generator.radius_sati_rects
    def by_rect(rect):
        easy_params = Easygo_Params(rect, '东莞')
        easy_clawer = Easygo_Clawer(easy_params)
        return easy_clawer.process()

    result_list = []
    for order, rect in enumerate(rect_list):
        time.sleep(1)
        view_bar(order+1, len(rect_list))
        part_res = by_rect(rect)
        if part_res:
            result_list += part_res
    # pool_v1 = ThreadPool(1)
    # all_res = pool_v1.map(by_rect, rect_list)
    # pool_v1.close()
    # pool_v1.join()

    res_saver = Res_saver(result_list, name)
    res_saver.save_as_file()

def easygo_func():
    try:
        email_alarm = Email_alarm()
        sf_reader = Shapefile_Reader(r'D:\GIS_workspace\东莞\东莞')
        rect_list = sf_reader.convert_to_rect(16)
        for rect in rect_list:
            main(rect[0], rect[1])
    except:
        print(traceback.print_exc())
        email_alarm.send_mail('宜出行抓取，软件崩了，快去看下吧')

if __name__ == "__main__":
    Cycle_Scheduler().by_time_point(['0600', '0700', '0800',
                                     '0900', '1000', '1100',
                                     '1200', '1300', '1400',
                                     '1500', '1600', '1700',
                                     '1800', '1900', '2000',
                                     '2100', '2200', '2300'
                                     ], '%H%M', easygo_func)








