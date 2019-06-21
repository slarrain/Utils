#!/usr/bin/env python3

import sqlite3
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

db = "/home/santiago/Dropbox/hamster-applet/hamster.db"

cnx = sqlite3.connect(db)

base_original = {
    2: 25,
    8: 20,
    12: 22
}

# Excepcion 
base_original = {
    2: 25*23/30 - 15.5 + 25,
    8: 120-95.2,
    12: 22
}

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
df2 = facts.set_index("start_time").last("1M")
df = df2.reset_index().merge(activities[['id', 'category_id']],right_on='id', left_on='activity_id')
actual = df.groupby('category_id')['duration'].sum().to_dict()

base = base_original.copy()
names = df3[['id_y', 'name_y']].drop_duplicates().set_index('id_y')['name_y'].to_dict()
suma = 0
total_mes = sum(base.values())
for empresa in base:
    suma += actual[empresa]
    base[empresa] -= actual[empresa]
horas_left = total_mes- suma
bdays_left = len(pd.bdate_range(pd.datetime.now().date()+pd.Timedelta(days=1), pd.datetime.now().date()+pd.tseries.offsets.MonthEnd(0)))
horas_por_dia = horas_left/bdays_left

print ("Horas: {:.1f} - Por dia: {:.1f}".format(horas_left, horas_por_dia))
print("---")
for x in base:
    print ("{}: {:.1f}".format(names[x], base[x]))