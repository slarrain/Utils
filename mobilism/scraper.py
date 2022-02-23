import requests
import json
from bs4 import BeautifulSoup
import pandas as pd
from itertools import chain
from tqdm import tqdm

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


if __name__ == '__main__':
    scrape_book_list()
