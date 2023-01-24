#!/usr/bin/env python3

import sqlite3
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

db = "/home/santiago/Dropbox/hamster-applet/hamster.db"

cnx = sqlite3.connect(db)

# meses since Julio
# start_date = '2019-07-01'
start_date = '2021-08-01'
duracion = len(pd.date_range(start_date, pd.datetime.today().strftime("%Y-%m-%d"), freq='1M', closed='left')) + 1
base_original = {
    # 'SECOM': 40*duracion-12-15,
    # 'Ariztia': 50*duracion,
    'SECOM': 40,
    'Ariztia': 50,
    # 'Koyle': 30-(11.3+5.5),
    # 'RetailCompass': 22.5*duracion
    'Elecciones': 12
}

# Excepcion 
# base_original = {
#     2: 25*23/30 - 15.5 + 25,
#     8: 120-95.2,
#     12: 22
# }

q1 = "SELECT * FROM activities"
q2 = "SELECT * FROM categories"
q3 = "SELECT * FROM facts"

activities = pd.read_sql_query(q1, cnx)
categories = pd.read_sql_query(q2, cnx)
facts = pd.read_sql_query(q3, cnx, parse_dates=['start_time', 'stop_time'])
if facts.end_time.iloc[-1] is None:
    facts.end_time.iloc[-1] = pd.datetime.now()
facts.end_time = pd.to_datetime(facts.end_time)

facts['duration'] = (facts.end_time - facts.start_time)/ pd.np.timedelta64(1, 'h')
df3 = activities.merge(categories, left_on='category_id', right_on='id')
dict_nombre_codigo = df3[['id_y', 'name_y']].drop_duplicates().set_index('name_y').to_dict()['id_y']

df2 = facts.set_index("start_time").sort_index()#.last("1M")
# df2 = df2[(df2.index.month == pd.datetime.now().month) & (df2.index.year == pd.datetime.now().year)]
df2 = df2[df2.index >= start_date]
df = df2.reset_index().merge(activities[['id', 'category_id']],right_on='id', left_on='activity_id')
actual = df.groupby('category_id')['duration'].sum().to_dict()

# base = base_original.copy()
base = {}
for name in base_original:
    base[dict_nombre_codigo[name]] = base_original[name]
names = df3[['id_y', 'name_y']].drop_duplicates().set_index('id_y')['name_y'].to_dict()
suma = 0
total_mes = sum(base.values())
for empresa in base:
    if empresa in actual:
        suma += actual[empresa]
        base[empresa] -= actual[empresa]
hoy = df.set_index("start_time").sort_index()#.last("1D")
hoy = hoy[hoy.index.date == pd.datetime.now().date()]
hoy_horas = hoy.loc[hoy.category_id.isin(base.keys()), :].duration.sum()
horas_left = total_mes- suma
horas_left = sum(base[empresa] for empresa in base if base[empresa] > 0)
bdays_left = len(pd.bdate_range(pd.datetime.now().date()+pd.Timedelta(days=1), pd.datetime.now().date()+pd.tseries.offsets.MonthEnd(0)))
bdays_left_hoy = len(pd.bdate_range(pd.datetime.now().date(), pd.datetime.now().date()+pd.tseries.offsets.MonthEnd(0)))
horas_por_dia = horas_left/bdays_left if bdays_left > 0 else 0
horas_por_dia_hoy = horas_left/bdays_left_hoy if bdays_left_hoy > 0 else 0

first_string = """Mes: :watch: {:.1f} - Diario: :hourglass: {:.1f} - Hoy: :clock4:{:.1f}
""".format(
    horas_left, 
    horas_por_dia, 
    hoy_horas
    )
print (first_string)
print("---")
for x in base:
    print ("{}: {:.1f}/{}".format(names[x], base[x], base_original[names[x]]))
