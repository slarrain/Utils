#############################
#   Santiago Larrain        #
#   slarrain@uchicago.edu   #
#   @slarrain               #
#############################


import pandas as pd
import BeautifulSoup as bf4
import numpy as np

#Colors lists
#Got them from: http://colorbrewer2.org/
colors1 = ['#ffffb2','#fed976','#feb24c','#fd8d3c','#f03b20','#bd0026']
colors2 = ['#d73027','#fc8d59','#fee08b','#d9ef8b','#91cf60','#1a9850']
colors3 = ['#ffffcc','#ffeda0','#fed976','#feb24c','#fd8d3c','#fc4e2a','#e31a1c',
'#bd0026','#800026']

def load_files():
    '''
    Does the reading
    '''
    db = pd.read_excel('BASE_FINAL_SEGPRES_ERTM_DA .xlsx')
    comunas = pd.read_csv('comunas.csv', encoding='windows-1252', header=None)
    svg = open('Comunas de Santiago.svg', 'r').read()
    return db, comunas, svg

def parse_svg (svg):
    '''
    Beautiful Soup in action
    '''
    soup = bf4.BeautifulSoup(svg, selfClosingTags=['defs'])
    paths = soup.findAll('path')
    return paths, soup


def process_munis(comunas, db, names, ind='IND_M_T', n=6):
    '''
    Creates different indexes for the Munis for the different DataFrames
    '''
    y = comunas[comunas[0].isin(names)].index
    y = [x-1 if (x>115 or x==64) else x-2 for x in y] #Annoying and custom. Had to fix
                                                      #discrepancies in the databases indexes
    rm = db.ix[y][['MUNICIPALIDAD', 'IDELWEB', 'IND_M_T']].copy()

    t = rm[ind]
    #t.hist(bins=n) # Take a look at the distribution to decide the number of bins

    u = (t.max()-t.min())/n
    t.fillna(7*u+t.min(), inplace=True) # Only useful if ind=IND_M_T. IDELWEB has
                                        # all the values
    bins = t.apply(lambda f: int((f-t.min())/u)) #Convert values into beans
    bins[bins==n] -=1   # t.max needs to be < n
    return bins

def take_svg_names(paths):
    '''
    Takes the names of the Munis from the SVG file.
    Applies strip function to the path itself and to the created list.
    It solves the 'Lo Prado ' bug.
    '''
    names = []
    for p in paths:
        p['id'] = p['id'].strip()
        names.append(p['id'])
    return names
    #names[5] = names[5].strip() # 'Lo Prado '

def new_path(paths):
    '''
    Creates a new empty path to replce the old one with the new colors
    '''
    path_style = paths[0]['style'][13:]
    path_style = path_style + ';fill:'
    return path_style


def replace_colors(comunas, bins, paths, path_style, c=1):
    '''
    Main function that changes the colors of each polygon in the map, according to the
    bins values.
    '''

    if c==2:
        colors = colors2
    elif c==3:
        colors = colors3
    else:
        colors = colors1

    colors.reverse() #Darker is worse

    for p in paths:

        y = int(comunas.index[comunas[0]==p['id']][0])

        # Fix indexes again
        if y>115 or y==64:
            y-=1
        else:
            y-=2

        n = int(bins[y])

        p['style'] = path_style + colors3[n]

    return paths


def save(soup, name):
    '''
    Saves the SVG file
    '''
    with open(name, 'w') as f:
        f.write(soup.prettify())

def do():
    '''
    Runs the program
    '''
    n=9
    db, comunas, svg = load_files()
    paths, soup = parse_svg(svg)
    names = take_svg_names(paths)
    path_style = new_path(paths)
    bins = process_munis(comunas, db, names, 'IDELWEB', n)
    paths = replace_colors(comunas, bins, paths, path_style, 3)
    save(soup, 'heatmap_6.svg')

if __name__ == "__main__":
    do()
