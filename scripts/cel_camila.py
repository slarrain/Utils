from glob import glob
from shutil import copy2


ORIG_PREFIX = '/media/data/CelCamila/'
DEST_PREFIX = '/media/data/FamiliaLarrainFuenzalida/'


def check_exists():
    all_files = glob(ORIG_PREFIX + '*/*/*')
    my_files = glob(DEST_PREFIX + 'fotos/*/*/*') + glob(DEST_PREFIX + 'videos/*/*/*') 
    print ("All: {}\nMine: {}".format(len(all_files), len(my_files)))

    result = [f.split('/')[-1] for f in all_files if f in [g.split('/')[-1] for g in my_files]]
    print (result)
    return result, all_files, my_files


def main():
    result, all_files, my_files = check_exists()
    if len(result) > 0:
        print ("ERROR. Archivos serán sobreescritos")
        exit(1)
    for path in all_files:
        filename = path.split('/')[-1]
        ano = filename[4:8]
        mes = filename[8:10]
        meses = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12']
        anos = ['2017', '2018', '2019']
        if mes not in meses or ano not in anos:
            print ("ERROR mes-ano--> {}".format(filename))
            exit(1) 
        if filename.startswith('IMG'):
            tipo = 'fotos'
        elif filename.startswith('VID'):
            tipo = 'videos'
        else:
            print ("ERROR --> {}".format(filename))
            exit(1)
        src = path
        dst = DEST_PREFIX + '/' + tipo + '/' + ano + '/' + mes + '/' + filename        
        print ("{} \t {}".format(src, dst))
        copy2(src=src, dst=dst, follow_symlinks=False)

if __name__ == "__main__":
    main()