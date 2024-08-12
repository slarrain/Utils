#!/usr/bin/python3
import sys
import json
import urllib.request
from datetime import datetime, timezone

def send_to_mariadb_nodered_api_update(url, mid, subject, to, fecha):


    url_api = "http://192.168.1.200:6335/pixel-update/"
    
    payload = { 
            "mid": mid,
            "url": url,
            "fecha": fecha,
            "subject": subject,
            "to": to
        }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    # Encode the payload as JSON
    data_bytes = json.dumps(payload, default=str).encode("utf-8")

    # Prepare the request
    request = urllib.request.Request(url_api, 
            data=data_bytes
            )
    for key, value in headers.items():
        request.add_header(key, value)

    # Send the request and handle the response
    with urllib.request.urlopen(request) as response:
        response_data = response.read().decode("utf-8")



if __name__ == '__main__':
    for line in sys.stdin:
        if 'Message-ID: <' in line:
            mid = line.strip().split('<')[-1][:-1]
            print (mid)
        if 'Subject: ' in line:
            subject = line.strip().split('Subject: ')[-1]
            print (subject)

        if 'To: ' in line and 'In-Reply-To:' not in line:
            to = line.strip().split('To: ')[-1]
            print (to)
        if "Date: " in line:
            fecha = line.strip().split("Date: ")[-1]
            print (fecha)
            fecha = datetime.strptime(fecha.strip(), '%a, %d %b %Y %H:%M:%S %z').astimezone(timezone.utc).replace(tzinfo=None)
            print (fecha)
        pre_url = 'src=3D"https://url.santiagolarrain.myds.me/'
        if pre_url in line:
            url = line.strip().split('src=3D"')[-1].split('/track')[0]
            print (url)

    send_to_mariadb_nodered_api_update(url, mid, subject, to, fecha)

