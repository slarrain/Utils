import pandas as pd 
from itertools import cycle
import argparse
from IPython.utils.io import Tee
from contextlib import closing
import random

DIAS = [
    'LUNES',
    'MARTES',
    'MIERCOLES',
    'JUEVES',
    'VIERNES',
    'SABADO',
    'DOMINGO'
]

FIN_SEMANA = DIAS[-2:]

def main(menu_base='demo.xlsx', start_dia='LUNES', n_dias=6):
    df = pd.read_excel(menu_base)
    i = DIAS.index(start_dia)
    new_dias = DIAS[i:] + DIAS[:i]
    ciclo = cycle(new_dias)
    comidas, ingredientes = get_comidas_ingredientes(df)

    menu = {}
    for _ in range(n_dias):
        dia = next(ciclo)
        almuerzo = random.choice(list(comidas))
        comidas.remove(almuerzo)
        comida = random.choice(list(comidas))
        comidas.remove(comida)
        
        i = 0
        while not son_compatibles(almuerzo, comida, ingredientes, dia):
            comidas.add(almuerzo)
            comidas.add(comida)
            almuerzo = random.choice(list(comidas))
            comidas.remove(almuerzo)
            comida = random.choice(list(comidas))
            comidas.remove(comida)
            # almuerzo, comida = comidas.pop(), comidas.pop()
            i += 1
            if i%1000==0: 
                print ("ERROR {}: {} - {}".format(i, almuerzo, comida))
                break
            # import pdb; pdb.set_trace()

        menu[dia] = [
            almuerzo,
            comida
        ]
    return menu


def get_comidas_ingredientes(df):
    comidas = set(df['Comida'].tolist())
    df.fillna('', inplace=True)

    ingredientes_dict = {}
    for _, row in df.iterrows():
        comida = row.Comida
        preferencia = row.Preferencia.strip().upper()
        fds = row.FinSemana.strip().upper()
        if fds == 'SI': weekend = True
        elif fds == 'NO': weekend = False 
        else: weekend = None
        verano = row.Verano.strip().upper()
        verano = True if verano == 'SI' else False
        ing = [x.strip() for x in row.Ingredientes.split(',') if len(x)>0]
        ingredientes_dict[comida] = {
                'ingredientes': ing,
                'weekend': weekend,
                'preferencia': preferencia,
                'verano': verano
            }
    # print (ingredientes_dict)
    return comidas, ingredientes_dict    


def son_compatibles(almuerzo, comida, ingredientes, dia):
    ing_almuerzo = set(ingredientes[almuerzo]['ingredientes'])
    ing_comida = set(ingredientes[comida]['ingredientes'])
    # print (ing_almuerzo, ing_comida)
    # print (almuerzo, comida)
    if ing_almuerzo.intersection(ing_comida):
        return False
    if ingredientes[almuerzo]['preferencia'] == 'COMIDA':
        return False
    if ingredientes[comida]['preferencia'] == 'ALMUERZO':
        return False
    if dia in FIN_SEMANA and (ingredientes[almuerzo]['weekend'] == False or  ingredientes[comida]['weekend'] == False):
        return False
    if dia not in FIN_SEMANA and (ingredientes[almuerzo]['weekend'] == True or  ingredientes[comida]['weekend'] == True):
        return False
    return True


def print_menu(menu):
    filename = 'menu_{}_{}.txt'.format(list(menu.keys())[0], len(menu))
    with closing(Tee(filename, "w", channel="stdout")) as outputstream:
        for dia in menu:
            print ("\t\t\t{}".format(dia))
            print ("Almuerzo:\t\t{}".format(menu[dia][0]))
            print ("Comida:  \t\t{}".format(menu[dia][1]))
            print ('')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
            "-d",
            "--dia",
            help="En que dia parte?",
            default='LUNES',
            type=str
            )
    parser.add_argument(
            "-n",
            "--numero",
            help="Numero de Dias para los que se quiere menu",
            default=3,
            type=int
            )
    parser.add_argument(
            "-f",
            "--file",
            help="Archivo .XLSX de comidas e ingradientes",
            default='demo.xlsx',
            type=str
            )
    args = parser.parse_args()
    menu = main(args.file, args.dia, args.numero)
    print_menu(menu)