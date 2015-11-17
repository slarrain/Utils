import unicodedata
import folium
import json
import statsmodels.api as sm
import seaborn as sns

def crear_base_comuna ():
    base_comunas = pd.read_csv('codigos-comuna-y-nombre.csv')
    base_comunas.rename(columns={'Código de la Comuna':'codigo', 'Nombre de la Comuna':'comuna'}, inplace=True)
    for x in base_comunas.index:
        base_comunas.loc[x, 'comuna'] = remove_accents(base_comunas.loc[x, 'comuna'].decode('utf-8'))
    base_comunas.to_csv('codigo_comunas.csv', index_col=False, encoding='utf-8')



def remove_accents(input_str):
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return u"".join([c for c in nfkd_form if not unicodedata.combining(c)])

comunas_base_mal = ['AYSEN', 'COYHAIQUE', 'LA CALERA', 'LLAILLAY', 'MARCHIHUE', 'PAIGUANO']
comunas_primarias_mal = ['AISEN','COIHAIQUE','CALERA', 'LLAY-LLAY','MARCHIGUE','PAIHUANO']

comunas_base_mal_concejales = [u'AYSEN', u'CABO DE HORNOS', u'LA CALERA',
                                u'LLAILLAY', u'MARIA PINTO', u"O'HIGGINS", u'PAIGUANO',
                                u'TEODORO SCHMIDT', u'TILTIL']
comunas_concejales_mal = [u'AISEN', u'CABO DE HORNOS Y ANTARTICA', u'CALERA', u'LLAY-LLAY',
                        u'MARIA PINTO ', u'OHIGGINS', u'PAIHUANO', u'TEODORO SCHMIDTH', u'TIL-TIL']


def add_code(prim, basecomunas):
    prim['codigo_comuna'] = 0
    for i in prim.index:
        comuna = remove_accents(prim.loc[i, 'COMUNA'])
        print comuna
        if comuna in comunas_primarias_mal:
            ind = comunas_primarias_mal.index(comuna)
            prim.loc[i, 'codigo_comuna'] = basecomunas.loc[basecomunas.index[basecomunas.nombre_comuna==comunas_base_mal[ind]][0], 'codigo_comuna']
        else:
            #print i
            #print basecomunas[basecomunas.nombre_comuna==comuna]['codigo_comuna']
            prim.loc[i, 'codigo_comuna'] = basecomunas.loc[basecomunas.index[basecomunas.nombre_comuna==comuna][0], 'codigo_comuna']
    return prim

def add_code2(prim, basecomunas):
    prim['codigo_comuna'] = 0
    for i in prim.index:
        comuna = remove_accents(prim.loc[i, 'Comuna'])
        print comuna
        if comuna in comunas_concejales_mal:
            ind = comunas_concejales_mal.index(comuna)
            prim.loc[i, 'codigo_comuna'] = basecomunas.loc[basecomunas.index[basecomunas.nombre_comuna==comunas_base_mal_concejales[ind]][0], 'codigo_comuna']
        else:
            #print i
            #print basecomunas[basecomunas.nombre_comuna==comuna]['codigo_comuna']
            prim.loc[i, 'codigo_comuna'] = basecomunas.loc[basecomunas.index[basecomunas.nombre_comuna==comuna][0], 'codigo_comuna']
    return prim

def go():
    '''
    Legacy version que ya no se necesita.
    La informacion del archivo excel, cambios en los nombres de las comunas,
    quitar acentos y letras extranas no es necesari volver a hacerlo

    go_new ocupa archivo generado en esta Funcion
    '''

    prim = pd.read_excel('Resultados_Eleccion_Primaria_Presidencial_2013.xlsx')
    prim1 = prim[prim.ELECCION=='Primaria Alianza']
    cand = prim1['NOMBRE CANDIDATO'].value_counts().index.tolist()
    prim2 = prim1.groupby(['COMUNA', 'NOMBRE CANDIDATO'])['VOTOS'].sum()
    comunas = prim2.index.levels[0].tolist()
    votos = pd.Series()
    for x in comunas:
        neto_voto = prim2[x][cand[0]]-prim2[x][cand[1]]
        votos[x]=neto_voto
    basecomunas = pd.read_csv('datosComunas.tsv', delimiter='\t')

    com = []
    for x in basecomunas.nombre_comuna:
        com.append(x)

    for x in range(len(com)):
        com[x] = remove_accents(com[x].decode('utf-8'))
    for x in range(len(comunas)):
        comunas[x] = remove_accents(comunas[x])

    for i in basecomunas.index:
        basecomunas.loc[i, 'nombre_comuna'] = remove_accents(basecomunas['nombre_comuna'][i].decode('utf-8'))

    primarias = add_code(prim, basecomunas)

    #primarias.to_csv('primarias_presidenciales_2013.csv', index_col=False, encoding='utf-8')
    #primarias1 = pd.read_csv('primarias_presidenciales_2013.csv')
    #primarias1 = primarias[primarias.ELECCION=='Primaria Alianza']

    primarias2 = primarias1.groupby(['codigo_comuna', 'NOMBRE CANDIDATO'])['VOTOS'].sum()
    cods = primarias2.index.levels[0].tolist()
    votos2 = pd.Series(index=cods)
    for x in cods:
        neto_voto = primarias2[x][cand[0]]-primarias2[x][cand[1]]
        votos2[x]=float(neto_voto)/(primarias2[x][cand[0]]+primarias2[x][cand[1]])
    votos3 = pd.DataFrame({'cod':votos2.index, 'votos':votos2}, dtype='int')
    for x in votos3.cod:
        suma = primarias2[x][cand[0]]+primarias2[x][cand[1]]
        votos3.loc[x, 'percent'] = float(votos3.loc[x, 'votos']/suma)

def go_new():
    '''
    Nueva version de la main function.
    Lee el archivo, genera subgrupos y retorna ultima version
    '''

    primarias = pd.read_csv('primarias_presidenciales_2013.csv')
    primarias1 = primarias[primarias.ELECCION=='Primaria Alianza']
    #cand = primarias1['NOMBRE CANDIDATO'].value_counts().index.tolist()

    primarias2 = primarias1.groupby(['codigo_comuna', 'NOMBRE CANDIDATO'])['VOTOS'].sum()

    return primarias2

def get_votos(primarias2):
    '''
    Genera 3 variables votos:
    votos_neto: La diferencia neta de votos --> Longueria - Allamand
    votos_per: La diferencia en Porcentajes
    votos_df: Las 2 anteriores unidas en un Data Frame
    '''

    cods = primarias2.index.levels[0].tolist() # Lista de codigos de Comunas

    votos_per = pd.Series(index=cods) # Diferencia en Porcentajes
    votos_neto = pd.Series(index=cods) #Numero absoluto de diferencia de votos (Longueira - Allamand)

    for x in cods:
        neto_voto = primarias2[x][0]-primarias2[x][1]
        votos_neto[x]=neto_voto
        votos_per[x]=neto_voto/float(primarias2[x][0]+primarias2[x][1])

    #DataFrame con votos_neto y votos_per
    votos_df = pd.DataFrame({'cod':votos_per.index, 'votos':votos_neto, 'percent':votos_per})
    return votos_df

def correct_code(votos):
    '''
    Arregla problemas del codigo de las comunas
    1402 --> '01402'
    '''
    votos.loc[:, 'cod'] = votos.loc[:, 'cod'].astype('str', copy=False)
    for i in votos.index:
        if len(votos.loc[i, 'cod'])<5:
            votos.loc[i, 'cod'] = '0'+votos.loc[i, 'cod']

def main():
    primarias2 = go_new()
    votos_df = get_votos(primarias2)
    correct_code(votos_df)
    create_map(votos_df)

def bin(votos):
    '''
    Funcion para crear bins que, si bien no cambia los colores del mapa,
    permiten una leyenda adecuada
    '''
    for x in votos.index:
        y = votos.loc[x, 'votos']
        if y<-300:
            y=1
        elif y<-50:
            y=11
        elif y<0:
            y=21
        elif y<50:
            y=31
        elif y<300:
            y=41
        else:
            y=51
        votos.loc[x, 'votos'] = y

def json_codigo_comuna():
    # It was faster to just harcode the themn thing. Is only 4
    # http://www.sinim.gov.cl/archivos/centro_descargas/modificacion_instructivo_pres_codigos.pdf
    # Already used
    new_c = ['Villa Alemana', 'Quilpue','Olmue','Limache']
    dict_new_c = {'Villa Alemana': '05804', 'Quilpue': '05801','Olmue':'05803','Limache':'05802'}


    with open('comunas_popup_4.json', 'r') as f:
        geojson = json.load(f)
    n = len(geojson['objects']['cl_comunas']['geometries'])
    for x in range(n):
        comuna = geojson['objects']['cl_comunas']['geometries'][x]['properties']['name']
        cod = int(geojson['objects']['cl_comunas']['geometries'][x]['id'])
        comuna = remove_accents(comuna)
        #if cod not in comunas_cod:
            #print cod, comuna
        if comuna in new_c:
            geojson['objects']['cl_comunas']['geometries'][x]['id'] = dict_new_c[comuna]

    with open ('comunas_popup_4.json', 'w') as g:
        json.dump(geojson, g)

def change_json(primarias):
    '''
    Una sola vez. Cambia el archivo GeoJSON para que muestre informacion sobre
    la comuna. En este caso: Nombre, Votos Allamand y Votos Longueira
    '''

    with open('comunas.json', 'r') as f:
        geojson = json.load(f)
    n = len(geojson['objects']['cl_comunas']['geometries'])
    for x in range(n):
        comuna = geojson['objects']['cl_comunas']['geometries'][x]['properties']['name']
        cod = int(geojson['objects']['cl_comunas']['geometries'][x]['id'])
        # '<br/>' because is html and '\n' didn't work
        texto = comuna+'<br/>'+primarias[cod].index[0][3:]+': '+str(primarias[cod][0])+'<br/>'+primarias[cod].index[1][3:]+': '+str(primarias[cod][1])
        geojson['objects']['cl_comunas']['geometries'][x]['properties']['popupContent'] = texto


    with open ('comunas_popup_3.json', 'w') as g:
        json.dump(geojson, g)

def concejales():
    concejales_base = pd.read_csv('RES_TER_Concejales_Oficial_2.csv')
    concejales_alianza = concejales_base[concejales_base.Pacto=='COALICION']
    concejales = concejales_alianza.groupby(['Comuna', 'Subpacto'])['Electo'].count()


{
  "type": "FeatureCollection",
  "features": [
    {
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [
              -117.7495299744,
              35.7405399984
            ],
            [
              -117.7422264169,
              35.7472081889
            ],
            [
              -117.7521555454,
              35.7536368252
            ]
          ]
        ]
      },
      "type": "Feature",
      "id": 1,
      "properties": {
        "name": "AirportLake,Subsection0",
        "popupContent": "sid:1 fault:AirportLake,Subsection0"
      }
    }
  ]
}

def plot_reg(votos3):
    pobreza2 = pd.read_csv('pobreza_comunal2.csv')
    pobreza2.rename(columns={'Código':'cod'}, inplace=True)
    df3 = pd.merge(votos3, pobreza2[[pobreza2.columns[0], pobreza2.columns[4]]], on='cod', how='inner')
    df2.loc[:, df.columns[1]] -= 3945
    df2.loc[:, df.columns[2]] *= 100
    plt.scatter(df2[df2.columns[2]],df2[df2.columns[1]], alpha=0.5)
    df2.rename(columns={df2.columns[2]:'pobreza'}, inplace=True)
    sns.jointplot(x=df2.columns[2], y=df2.columns[1], data=df2, kind='reg')


def votos_cod(votos3):
    '''
    Fixes votos DF 5 bad cods
    '''
    # Base pobreza tiene codigos actualizados
    # Base votos antiguos
    dict_cod_cod = {5108:5804, 5106:5801, 5505: 5802, 5507:5803}
    # Se borra Antartica por no estar en pobreza
    votos4 = votos3[votos3.cod!=12202]
    for key in dict_cod_cod:
        votos4.loc[key, 'cod'] = dict_cod_cod[key]
    return votos4





def linear_reg(votos, pobreza2):
    '''
    Linear regression de Votos sobre Pobreza en las primaria de la Alianza
    '''
    Y = votos4['votos']

    Y.reset_index(drop=True, inplace=True) #Need to have the same index

    X = pobreza2[pobreza2.columns[3]] # TODO: rename column

    X = sm.add_constant(X) #Tried without it. Doesn't work
    est = sm.OLS(Y, X).fit()
    est.summary() #Same as Stata

    '''
    vtl = votos_neto.index.tolist()
    pl = p3.cod.tolist()
    for x in pl:
        if x not in vtl:
            print x
    '''

def create_map(votos_df):
    # Location: Chile (Bulnes)
    map1 = folium.Map(location=[-37.016667, -73.13333], zoom_start=5)

    # comunas_popup_3 es el GeoJSON con las comunas y el popup information
    # con nombre de la comuna y numero de votos de cada candidato
    # 'data' es el dataFrame con los votos
    # columnas son codigo de comuna (que esta tambien en el GeoJSON) y
    # percent(aunque podria ser diferencia de votos)
    # threshold_scale es donde hace el corte (TODO)
    # fill_color son la gama de colores
    map1.geo_json(geo_path='comunas_popup_3.json', topojson='objects.cl_comunas',
                data_out='data_out_5.json', data=votos_df, columns=['cod', 'percent'],
                key_on='feature.id',
                fill_color='RdYlBu',
             legend_name='Allamand - Longueira', threshold_scale=[-0.2, -0.05, 0.0, 0.05, 0.2])

    # Nombre y path del nuevo mapa
    map1.create_map(path='map23.html')
