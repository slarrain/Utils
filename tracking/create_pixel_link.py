#!/usr/bin/python3

import sys
# sys.path.append('/usr/local/lib/python3.10/dist-packages/')
# import requests
from datetime import datetime, timezone
# from mysql import connector
import configparser
import urllib.request
import json

API_KEY = 'ed663eae-ace1-4a03-b59a-2c4a6dde68a7'


def get_short_link():


    url = "https://url.santiagolarrain.myds.me/rest/v3/short-urls"
    
    payload = {
        "longUrl": "https://www.pacificlabs.cl",
        "tags": [
            "pixel", 
            # "testing"
            ]
    }
    headers = {
        "accept": "application/json",
        "X-Api-Key": API_KEY,
        "Content-Type": "application/json"
    }
    
    # r = requests.request("POST", url, json=payload, headers=headers)

    # Encode the payload as JSON
    data_bytes = json.dumps(payload, default=str).encode("utf-8")

    # Prepare the request
    request = urllib.request.Request(url, data=data_bytes)
    for key, value in headers.items():
        request.add_header(key, value)

    # Send the request and handle the response
    with urllib.request.urlopen(request) as response:
        response_data = response.read().decode("utf-8")

    # Parse the JSON response
    data = json.loads(response_data)

    # data = r.json()
    # print (data)

    return data


def send_to_mariadb(data):

    config = configparser.ConfigParser()
    config.read('./credentials.ini', )

    user = config['NASDB']['user']
    password=config['NASDB']['password']
    host=config['NASDB']['host']
    port=config['NASDB']['port'] 
    database=config['NASDB']['database']

    url = data['shortUrl']
    date_created = datetime.strptime(data['dateCreated'], '%Y-%m-%dT%H:%M:%S%z')
    short_code = data['shortCode']

    conn = connector.connect(
        user=user,
        password=password,
        host=host,
        port=port,
        database=database
        )
    cur = conn.cursor() 

    stmt = "INSERT INTO pixel_email (url, shortcode, created_date) VALUES (%s, %s, %s)"
    try: 
        cur.execute(stmt, [url, short_code, date_created])
    except Exception as e: 
        print(f"Error: {e}")

    conn.commit() 
    # print(f"Last Inserted ID: {cur.lastrowid}")
        
    conn.close()

def send_to_mariadb_nodered_api(data):


    url_api = "http://192.168.1.200:6335/pixel-create/"
    
    url = data['shortUrl']
    date_created = datetime.strptime(data['dateCreated'], '%Y-%m-%dT%H:%M:%S%z').astimezone(timezone.utc).replace(tzinfo=None)
    short_code = data['shortCode']

    payload = { 
            "shortcode": short_code,
            "url": url,
            "created_date": date_created
        }
    headers = {
        # "accept": "application/json",
        # "X-Api-Key": API_KEY,
        "Content-Type": "application/json"
    }
    
    # r = requests.request("POST", url, json=payload, headers=headers)

    # Encode the payload as JSON
    data_bytes = json.dumps(payload, default=str).encode("utf-8")

    # Prepare the request
    request = urllib.request.Request(url_api, 
            data=data_bytes
            # data=payload
            )
    for key, value in headers.items():
        request.add_header(key, value)

    # Send the request and handle the response
    with urllib.request.urlopen(request) as response:
        response_data = response.read().decode("utf-8")


if __name__ == '__main__':
    data = get_short_link()
    send_to_mariadb_nodered_api(data)
    print (data['shortUrl'])
