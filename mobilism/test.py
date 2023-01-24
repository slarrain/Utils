import sys
from bs4 import BeautifulSoup
import requests

def main(a):
    r = requests.get(a)
    soup = BeautifulSoup(r.text, 'lxml')
    links = soup.find_all('a', class_='postlink')
    b = [x.get('href') for x in links if not x.get('href').startswith("https://forum.mobilism.org/")]
    print b
    return b


# if __name__ == '__main__':
a = sys.argv[1]
main(a)
