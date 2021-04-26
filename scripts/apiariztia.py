#!/usr/bin/env python3

import requests
import configparser


config = configparser.ConfigParser()
config.read('/home/santiago/github/Utils/scripts/credentials.ini')

user = config['ARIZTIA']['user']
password = config['ARIZTIA']['password']
endpoint = config['ARIZTIA']['endpoint']

p = {
        True: ":large_blue_circle:",
        False: ":x:"
        }

def main():
    request_body = {
          "IdSucursalEmpresa": 0,
          "IdArea": 0,
          "IdCanal": 0,
          "IdSubcanal": 2,
          "IdSucursalCliente": 0,
          "Producto": [
            {
              "IdProducto": 200612607,
              "Descripcion": "string"
            },
            {
                "IdProducto": 210512607
            }   
          ]
        }
    expected_result = {105510237,
                 105910266,
                 212112607,
                 309612607,
                 402513061,
                 402613068,
                 422313184,
                 961914699}
    r = requests.post(url = endpoint + '/Canasta', json=request_body, auth=(user, password))
    result = set([x['IdProducto'] for x in r.json()]) == expected_result
    print (f"API{p[result]}")

if __name__ == '__main__':
    main()
