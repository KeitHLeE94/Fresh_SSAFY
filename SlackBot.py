# -*- coding: utf-8 -*-
import json
import os
import requests
import urllib.request
import time
import re
from bs4 import BeautifulSoup
from slackclient import SlackClient
from flask import Flask, request, make_response, render_template, jsonify
from selenium import webdriver

# 바꼈지롱

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

with open('SlackBotKey.json') as f:
    slackKeys = json.load(f)
slack_token = slackKeys["slack_token"]
slack_client_id = slackKeys["slack_client_id"]
slack_client_secret = slackKeys["slack_client_secret"]
slack_verification = slackKeys["slack_verification"]
sc = SlackClient(slack_token)


# 메인페이지 함수
@app.route("/", methods=["GET"])
def index():
    return "<h1>Server is ready.</h1>"


# 사용자의 입력에 대한 분석 결과를 return하는 함수.
# DialogFlow를 통해 사용자의 입력에 대응하는 Intent와 Speech를 return.
def get_answer(text, user_key):
    data_send = {
        'query': text,
        'sessionId': user_key,
        'lang': 'ko',
    }
    data_header = {
        'Authorization': slackKeys["authorization"],
        'Content-Type': 'application/json; charset=utf-8'
    }
    dialogflow_url = 'https://api.dialogflow.com/v1/query?v=20150910'
    res = requests.post(dialogflow_url, data=json.dumps(data_send), headers=data_header)
    if res.status_code != requests.codes.ok:
        return '오류가 발생했습니다.'
    data_receive = res.json()
    result = {
        "speech" : data_receive['result']['fulfillment']['speech'],
        "intent" : data_receive['result']['metadata']['intentName']
    }
    return result


# event handle 함수
def _event_handler(event_type, slack_event):
    print(slack_event["event"])

    # event type이 app_mention(@...으로 소환)인 경우
    if event_type == "app_mention":
        channel = slack_event["event"]["channel"]
        text = slack_event["event"]["text"]
        text = text[13:]
        keywords = list()

        userid = 'session'

        # 사용자 입력에 대응하는 Intent와 Speech를 찾는다.
        result = get_answer(text, userid)

        if result['intent'] == 'Bugs':
            keywords = _crawl_naver_keywords()
        elif result['intent'] == 'Road Address':
            keywords = road_address(text, result['speech'])
        elif result['intent'] == 'Default Welcome Intent':
            keywords = default_greetings(result)
        else:
            keywords = default_fallbacks(result)
        sc.api_call(
            "chat.postMessage",
            channel=channel,
            text=keywords
        )

        return make_response("App mention message has been sent", 200, )

    # event type이 따로 정의되지 않은 경우
    message = "You have not added an event handler for the %s" % event_type

    return make_response(message, 200, {"X-Slack-No-Retry": 1})


# 사용자의 입력을 처리하는 함수
# 사용자의 입력에 매칭되는 event를 찾는다.
@app.route("/listening", methods=["GET", "POST"])
def hears():
    slack_event = json.loads(request.data)
    if "challenge" in slack_event:
        return make_response(slack_event["challenge"], 200, {"content_type": "application/json"})
    if slack_verification != slack_event.get("token"):
        message = "Invalid Slack verification token: %s" % (slack_event["token"])
        make_response(message, 403, {"X-Slack-No-Retry": 1})
    if "event" in slack_event:
        event_type = slack_event["event"]["type"]

        # 사용자의 입력에 대응하는 event를 찾는다.
        return _event_handler(event_type, slack_event)

    # 사용자의 입력에 대응하는 event가 정의되지 않았거나 적절한 event를 찾지 못했을 경우.
    return make_response("[NO EVENT IN SLACK REQUEST] These are not the droids\
                         you're looking for.", 404, {"X-Slack-No-Retry": 1})


# Intent가 Bugs로 판단되면 실행.
# 벅스뮤직 인기순위 1~10위 곡 제목 + 아티스트 크롤링 함수
def _crawl_naver_keywords():
    keywords = list()
    titleList = list()
    artistList = list()
    rank = 1

    sourcecode = urllib.request.urlopen('https://music.bugs.co.kr/').read()
    soup = BeautifulSoup(sourcecode, 'html.parser')

    for title in soup.find_all('p', class_='title'):
        item = str(rank) + '위: ' + title.text.strip('\n')
        titleList.append(item)
        rank += 1

    for artist in soup.find_all('p', class_='artist'):
        item = ' / ' + artist.text.strip('\n')
        artistList.append(item)

    for i in range(10):
        item = titleList[i] + artistList[i]
        keywords.append(item)

    # 한글 지원을 위해 앞에 unicode u를 붙여준다.
    return u'\n'.join(keywords)


# Intent가 Default Welcome Intent로 판단되면 실행.
def default_greetings(inputstuff):
    return inputstuff['speech']


# Intent가 Road Address로 판단되면 실행.
def road_address(address, speech):
    # Selenium으로 크롤링한다.
    driver = webdriver.Chrome('C:\Chrome Driver\chromedriver.exe')

    # 검색어에서 주소만 남기도록 처리
    if address.find('도로명주소') != -1:
        endIndex = address.find('도로명주소')
        address = address[:endIndex-1]

    # 검색 결과 메시지
    roadAddressResult = list()
    speechList = speech.split('`')[1:]
    roadAddressResult.append(speechList[0])
    roadAddressResult.append('========================================================================================')

    # 도로명 주소 검색 사이트에서 address로 검색.
    driver.get('http://www.juso.go.kr/support/AddressMainSearch.do?searchType=TOTAL#detail')
    driver.find_element_by_name('searchKeyword').send_keys(address)
    time.sleep(0.5)
    driver.find_element_by_xpath('//*[@id="searchButton"]').click()

    # 검색 결과 메시지 예: address을(를) 검색한 결과 총 6건 입니다.
    resultMessage = driver.find_element_by_xpath('//*[@id="searchAddress"]/div/p').text.replace(',', '')
    # 저기서 숫자만 떼온다.
    resultCount = int(re.findall('\d+', resultMessage)[0])

    # 검색 결과 - 여러개면 최대 10개까지만 알려준다.
    if resultCount > 10:
        resultCount = 10

    # 검색 결과에서 우편번호만 따로 모은다.
    zipCodeList = list()
    zipCodeTemp = driver.find_elements_by_class_name('fixed')

    for item in zipCodeTemp:
        # 우편번호는 반드시 5자리이므로 길이가 5인 것만 살림.
        if len(item.text) == 5:
            zipCodeList.append(str(item.text))

    if resultCount > 2:
        for itemNum in range(1, resultCount+1):
            roadAddressResult.append(\
                driver.find_element_by_xpath('//*[@id="list' + str(itemNum) + '"]/td[2]/ul/li[2]/div[2]').text\
                + '  /  우편번호: ' + str(zipCodeList[itemNum-1]))
    elif resultCount == 1:
        roadAddressResult.append(\
            driver.find_element_by_xpath('//*[@id="list1"]/td[2]/ul/li[2]/div[2]').text\
            +  '  /  우편번호: ' + zipCodeList[0])

    # 안내 메시지
    roadAddressResult.append('========================================================================================')
    roadAddressResult.append(speechList[1])
    roadAddressResult.append(speechList[2])
    roadAddressResult.append(speechList[3])
    print(roadAddressResult)

    # 검색끝나면 드라이버 종료.
    driver.quit()

    return u'\n'.join(roadAddressResult)


# Intent가 제대로 정의되지 않으면 실행.
def default_fallbacks(inputstuff):
    return inputstuff['speech']


# Main함수
if __name__ == '__main__':
    app.run('0.0.0.0', port=8080)
