#!/usr/bin/python 
from mysql import connector

import requests
import configparser


def main():

    config = configparser.ConfigParser()
    config.read('./credentials.ini')

    email = config['FINTUAL']['Email']
    token = config['FINTUAL']['Token'] 
    user = config['NASDB']['user']
    password=config['NASDB']['password']
    host=config['NASDB']['host']
    port=config['NASDB']['port'] 
    database=config['NASDB']['database']

    api_url = 'https://fintual.cl/api/'
    PARAMS = {'user_email': email, 'user_token': token}
    r = requests.get(url = api_url + 'goals', params = PARAMS)
    data = r.json()['data']
    results = []
    for x in r.json()['data']:
        y = x['attributes'] 
        results.append(
                (
                y['name'], 
                y['nav'],
                y['profit']
                )
        )
    # print (results)

    conn = connector.connect(
        user=user,
        password=password,
        host=host,
        port=port,
        database=database
        )
    cur = conn.cursor() 

    # #retrieving information 
    # some_name = "Georgi" 
    # cur.execute("SELECT first_name,last_name FROM employees WHERE first_name=?", (some_name,)) 

    # for first_name, last_name in cur: 
        # print(f"First name: {first_name}, Last name: {last_name}")
        
    stmt = "INSERT INTO fintual (name, value, profit) VALUES (%s, %s, %s)"
    #insert information 
    try: 
        cur.executemany(stmt, results)
    except Exception as e: 
        print(f"Error: {e}")

    conn.commit() 
    # print(f"Last Inserted ID: {cur.lastrowid}")
        
    conn.close()


if __name__ == '__main__':
    main()
