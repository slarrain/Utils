from glob import glob


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
    # if len(result) > 0:
    #     print ("ERROR. Archivos serán sobreescritos")
    #     exit(1)
    # for path in all_files:
    #     filename = path.split('/')[-1]
    #     tipo = 'fotos' if filename.startswith('IMG') 


if __name__ == "__main__":
    main()