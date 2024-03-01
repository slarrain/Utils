import argparse
import pandas as pd
import shutil

def make_a_copy(filename):
    print (f"Making a backup copy of {filename}")
    shutil.copy(filename, filename+'.bak')

def change(d):
    if len(d) == 5:
        return d + '-2024'
    else:
        return d


def get_mini_df(tipo, exc):
    d = {
        "Cargos":"Otros Cargos",
        "Abonos":"Abonos"
    }
    col_name = d[tipo]
    indice_inicio = exc.loc[exc[exc.columns[0]] == col_name].index[0] + 2
    for i in range(indice_inicio, len(exc)):
        if exc.loc[i, "Cartola Anterior"] == "Subtotal:":
            indice_fin = i -1
            # print (i -1)
            break
    df = exc.loc[indice_inicio:indice_fin, [exc.columns[0], exc.columns[1], exc.columns[2], exc.columns[-1]]]
    df.columns = ['Fecha', 'Categoria', 'Detalle', 'Monto $']
    df.Categoria = tipo
    df.Fecha = df.Fecha.apply(change)
    df.Fecha = pd.to_datetime(df.Fecha, dayfirst=True).dt.date
    return df


def main(orig_filename):

    filename = "/home/santiago/MEGA/PacificLabs/Administrativo/COSTOS/COSTOS2023.xlsx"
    make_a_copy(filename)
    df = pd.read_excel(filename, 
                   sheet_name='datos', 
                   usecols="A:G")
    exc = pd.read_excel(orig_filename)
    cargos = get_mini_df("Cargos", exc)
    abonos = get_mini_df("Abonos", exc)
    startrow = len(df)+1

    print (cargos.to_markdown())
    print (abonos.to_markdown())

    with pd.ExcelWriter(
        filename,
        # engine='openpyxl',
        mode="a",
        if_sheet_exists="overlay",
        date_format='%Y-%m-%d',
        datetime_format='%Y-%m-%d',
    ) as writer:
        cargos.to_excel(writer, sheet_name="datos", index=False, startrow=startrow, header=False)
        abonos.to_excel(writer, sheet_name="datos", index=False, startrow=startrow+len(cargos), header=False)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
            "-f",
            "--filename",
            help="Specify the Excel filename to extract the data from",
            type=str
            )
    args = parser.parse_args()
    main(args.filename)
