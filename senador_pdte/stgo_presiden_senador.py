import pandas as pd
import unicodedata
import BeautifulSoup as bf4


def read_comunas():
    '''
    Loads comunas
    '''
    comunas = pd.read_csv('codigos-comunas-y-nombre.csv', index_col=False)
    return comunas

def read_senadores():
    senador = pd.read_excel('13_Resultado_Mesa_Senadores_Tricel.xlsx')
    alianza = senador[senador.PACTO=='ALIANZA'].groupby(['COMUNA'])['VOTOS TRICEL'].sum()
    return alianza

def read_presidentes():
    presidente = pd.read_excel('Resultados_Mesa_Presidente_Tricel_2da_Votacion.xlsx')
    evelyn = presidente[(presidente.REGION==13) &
        (presidente.CANDIDATO=='EVELYN MATTHEI FORNET')].groupby(['COMUNA'])['VOTOS TRICEL'].sum()
    return evelyn

def parse_svg ():
    '''
    Beautiful Soup in action
    '''
    svg = open('Comunas de Santiago.svg', 'r').read()
    soup = bf4.BeautifulSoup(svg, selfClosingTags=['defs'])
    paths = soup.findAll('path')
    return paths, soup

def take_svg_names(paths, soup):
    '''
    Replaces the name of the municipality in the <id> tag with the code
    '''
    for p in paths:
        x = p['id'].strip()

        p['id'] = get_code(x)
    save(soup)

def get_code(name):
    '''
    Returns the code of the municipality given the name
    TODO: Agregar exception handling para que pueda agarrar casos
    de string y no unicodedata
    TODO: generalizar para que no tenga que argar archivo cada vez
    '''
    comunas2 = pd.read_csv('codigo_comunas.csv', index_col=0)
    name_fix = remove_accents(name)
    print name_fix
    code = str(int(comunas2[comunas2.comuna==name_fix]['codigo']))
    if len(code)<5:
        code = '0'+code
    return code

def save(soup, name='comuna_santiago_codigo.svg'):
    '''
    Saves the SVG file
    '''
    with open(name, 'w') as f:
        f.write(soup.prettify())



def remove_accents(input_str):
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return u"".join([c for c in nfkd_form if not unicodedata.combining(c)])

def compare_names(alianza, comunas):
    '''
    Used just once to compare
    They are all the same
    '''

    s = []
    for x in comunas['Nombre de la Comuna']:
        s.append(remove_accents(x.decode('utf-8')).upper())
    d = []
    ds = []
    for x in alianza.index:
        y = remove_accents(x)
        d.append(y)
        if y not in s:
            ds.append(y)
            print y

def do():
    paths, soup = parse_svg()
    take_svg_names(paths, soup)

if __name__ == "__main__":
    #do()
