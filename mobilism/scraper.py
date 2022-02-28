#!/usr/bin/python 
import requests
import configparser
import argparse
import json
from bs4 import BeautifulSoup
import pandas as pd
from itertools import chain
from tqdm import tqdm
from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from datetime import datetime
from sqlalchemy import create_engine


def scrape_book_list():

    url = "https://forum.mobilism.me/viewforum.php?f=19&start={}"
    
    data = []
    for i in tqdm(range(5, 1125760, 40)):
        
        try:
            data.append(process_single_page(url.format(i)))
        except:
            tqdm.write(url.format(i))

    save_data(list(chain.from_iterable(data)))


def process_single_page(url):

    r = requests.get(url)
    soup = BeautifulSoup(r.text, 'html5')
    tabla = list(soup.select("table.footable:nth-child(6) > tbody:nth-child(2)"))[0]
    x = tabla.find_all('a', class_='topictitle')
    rv = []
    for l in x:
        rv.append(
            {
                'name': l.text, 
                'link': l.get('href'),
                'fecha': l.get('title')
            }

                )
    return rv

def save_data(lista):
    with open("listado_libros.json", 'w') as f:
        json.dump(lista, f, indent=2)


def extract_formatos(texto):
    formatos = [
        'ePUB',
        'EPUB',
        'PDF',
        'MP3',
        'MOBI',
        'AZW3',
        'M4B',
        'CBR',
        'AZW',
        'CHM',
        'PDB',
        'M4A',
        'CBZ'
    ]
    rv = []
    for f in formatos:
        if f in texto:
            rv.append(f)
    return rv


def process_dates(fecha):
    now = datetime.now()
    if 'minutes ago' in fecha:
        fecha = str(now - relativedelta(minutes=int(fecha.replace(' minutes ago',''))))
    elif 'Yesterday' in fecha:
        fecha += str((now - relativedelta(days=1)).date())
    return parse(fecha, fuzzy=True)    



def procesar_descargados():

    with open("listado_libros.json") as f:
        d = json.load(f)

    df = pd.DataFrame(d)
    df['formato'] = df.name.apply(lambda x: ','.join(extract_formatos(x)))

    df = pd.concat([df, pd.DataFrame(df.name.str.split('\(.').apply(lambda x: x[0].split('by')).apply(lambda x: (''.join(x[:-1]).strip(), x[-1].strip())).tolist(), columns=('nombre', 'autor'))], axis=1)

    df.fecha = df.fecha.str.replace("Posted : ","")
    df['fecha'] = df.fecha.apply(process_dates)
    df.link = df.link.str.replace('./', 'https://forum.mobilism.me/')
    indices = df[df.nombre == ''].index
    df.loc[indices, 'nombre'] = df.loc[indices, 'autor']
    df.loc[indices, 'autor'] = ''

    return df

def send_to_db(df):
    config = configparser.ConfigParser()
    config.read('./credentials.ini')

    user = config['NASDB']['user']
    password=config['NASDB']['password']
    host=config['NASDB']['host']
    port=config['NASDB']['port'] 
    database=config['NASDB']['database']

    engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}")

    # conn = connector.connect(
        # user=user,
        # password=password,
        # host=host,
        # port=port,
        # database=database
        # )
    print ("Sending to DB")

    df.to_sql(
            name="mobilism_book_list",
            con=engine.connect(),
            if_exists='append',
            index=False,
            )


def main(args):
    if args.scrape:
        scrape_book_list()
    elif args.todb:
        df = procesar_descargados()
        send_to_db(df)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
            "-s",
            "--scrape",
            help="Perform the scrape",
            action='store_true',
            )
    parser.add_argument(
            "-d",
            "--todb",
            help="Process and Send to DB",
            action='store_true',
            )
    args = parser.parse_args()
    main(args)
