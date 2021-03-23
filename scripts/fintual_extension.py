#!/usr/bin/env python3

import requests
import configparser


config = configparser.ConfigParser()
config.read('/home/santiago/github/Utils/scripts/credentials.ini')

email = config['FINTUAL']['Email']
token = config['FINTUAL']['Token']

api_url = 'https://fintual.cl/api/'
PARAMS = {'user_email': email, 'user_token': token}

p = {
        True: ":large_blue_circle:",
        False: ":red_circle:"
        }

def main():
    r = requests.get(url = api_url + 'goals', params = PARAMS)
    data = r.json()['data']
    profit = 0
    results = {}
    for x in r.json()['data']:
        y = x['attributes'] 
        if y['name'] == 'Mi Primera Inversión': continue
        # print (y['name'], y['nav'])
        results[y['name']] = {'value': y['nav'],
                'profit': y['profit']}
        profit += float(y['profit'])

    print (f"{p[profit>0]} {profit:,.0f}")
    print ("---")
    for name in results:
        print (f"{name}: {results[name]['value']:,.0f} \t {results[name]['profit']:,.0f}")

if __name__ == '__main__':
    main()
