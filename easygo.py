import requests
from multiprocessing.dummy import Pool as ThreadPool
from selenium.webdriver import ActionChains
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
    account_reader_times = 0
    used_account = []
    cookies = {}
    def __init__(self, params):
        super(Easygo_Clawer, self).__init__(params)
        self.referer = {"Referer": "http://c.easygo.qq.com/eg_toc/map.html?origin=csfw"}
        self.headers.update(self.referer)
        self.url = "http://c.easygo.qq.com/api/egc/heatmapdata"
        self.cookies = Easygo_Clawer.cookies
        self.qq_account = ''
        # print(self.cookies)

    def scheduler(self):
        if self.req_num == 0:
            self.status_change_cookies()
            # print(self.cookies)
            Easygo_Clawer.req_num += 1
        elif self.req_num <= 130:
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
        codes = json_dict.get('code')
        if codes == 0 and len(datas) != 0:
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
        elif codes == 0 and len(datas) == 0:
            print("此区域没有点信息")
            logger.info("此区域没有点信息 %s" % self.req_url)
        elif codes == 3:
            logger.info("%s 账号需要验证" % self.qq_account)
            time.sleep(3)
            self.cookies = self.get_cookie()
            points = self.process()
            Easygo_Clawer.req_num = 1
            return points
        elif codes == -100:
            logger.info("%s 账号已用完" % self.qq_account)
            time.sleep(3)
            self.cookies = self.get_cookie()
            points = self.process()
            Easygo_Clawer.req_num = 1
            return points
        else:
            print(json_dict)
            logger.info("%s 账号出现未知错误" % self.qq_account)

    def read_account(self, file_path):
        df = pd.read_excel(file_path)
        account_list = df.to_dict(orient='records')
        return account_list



    def get_cookie(self):
        self.driver = webdriver.Chrome()
        self.driver.set_window_size(200, 300)
        if self.account_list:
            account = Easygo_Clawer.account_list.pop()
            self.qq_account = str(account['account'])
            self.qq_password = str(account['password'])
            print('账号状况：剩余：%s' % len(Easygo_Clawer.account_list))
            try:
                self.login(self.qq_account, self.qq_password)
            except:
                time.sleep(2)
                self.login(self.qq_account, self.qq_password)
            time.sleep(3)
            self.scheduler_by_url()
            cookies = self.driver.get_cookies()
            user_cookie = {}
            for cookie in cookies:
                user_cookie[cookie["name"]] = cookie["value"]
            account['date'] = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            Easygo_Clawer.used_account.append(account)
            time.sleep(2)
            self.driver.quit()
            return user_cookie
        elif Easygo_Clawer.account_reader_times == 0:
            Easygo_Clawer.account_list = account_reader('D:\program_lib\QQ_Tool\qq_pool.xlsx')
            Easygo_Clawer.account_reader_times += 1
            return self.get_cookie()
        else:
            new_df = pd.DataFrame(self.used_account)
            new_df.to_excel('D:\program_lib\QQ_Tool\qq_pool.xlsx')
            raise CookieException('今日账号已用完')

    def login(self, account, password):
        self.driver.get("http://c.easygo.qq.com/eg_toc/map.html?origin=csfw")
        self.driver.find_element_by_id("u").send_keys(account)
        self.driver.find_element_by_id("p").send_keys(password)
        self.driver.find_element_by_id("go").click()

    def scheduler_by_url(self):
        current_url = self.driver.current_url
        current_url = current_url.split('?')[0]
        if current_url in 'http://c.easygo.qq.com/eg_toc/map.html?origin=csfw':
            print('登录成功')
        elif current_url == 'http://ui.ptlogin2.qq.com/cgi-bin/login':
            self.captcha()

    def captcha(self):
        self.driver.switch_to.frame('tcaptcha_iframe')
        button = self.driver.find_element_by_id('tcaptcha_drag_button')
        while True:
            ActionChains(self.driver).move_to_element(button).click_and_hold(button).perform()
            ActionChains(self.driver).move_by_offset(176, 0).release().perform()
            time.sleep(2)

            if "登录" in self.driver.page_source:
                dialog = self.driver.find_elements_by_class_name('qui-dialog-box')
                if dialog:
                    print('登录不成功')
                break



def view_bar(num, total):
    rate = float(num) / float(total)
    rate_num = int(rate * 100)
    r = '\r[%s%s]%d%%' % ("="*(rate_num+1), " "*(100-rate_num-1), rate_num, )
    sys.stdout.write(r)


def main(region_name, origin_rects):
    name = region_name
    # sample_generator = Sample_Generator(name)
    # 东莞4000
    # sample_generator.filter_radius(origin_rects, 4000)
    # rect_list = sample_generator.radius_sati_rects
    rect_list = origin_rects
    # print(rect_list)
    def by_rect(rect):
        easy_params = Easygo_Params(rect, '威海')
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
        sf_reader = Shapefile_Reader(r'D:\GIS_workspace\地理边界\威海\威海采样4000_wgc84')
        rect_list = sf_reader.convert_to_rect(3)
        print(rect_list)
        categry_dict = {}
        for rect in rect_list:
            # print(categry_dict)
            if rect[0] in categry_dict and rect[1]:
                # print('键值为 %s' % rect[0])
                categry_dict[rect[0]].append(rect[1])
            else:
                categry_dict[rect[0]] = []
        print(categry_dict)
        for categry in categry_dict.items():
            # print(categry)
            main(categry[0], categry[1])
    except:
        print(traceback.print_exc())
        email_alarm.send_mail('宜出行抓取，软件崩了，快去看下吧')

if __name__ == "__main__":
    Cycle_Scheduler().by_time_point(['0500', '0600', '0700', '0800',
                                     '0900', '1000', '1100',
                                     '1200', '1300', '1400',
                                     '1500', '1600', '1700',
                                     '1800', '1908', '2000',
                                     '2100', '2200', '2300',
                                     '0000'
                                     ], '%H%M', easygo_func)








