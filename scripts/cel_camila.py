from glob import glob


ORIG_PREFIX = '/media/data/CelCamila/'
DEST_PREFIX = '/media/data/FamiliaLarrainFuenzalida/'


def check_exists():
    all_files = glob(ORIG_PREFIX + '*/*/*')
    my_files = glob(DEST_PREFIX + 'fotos/*/*/*') + glob(DEST_PREFIX + 'videos/*/*/*') 
    print ("All: {}\nMine: {}".format(len(all_files), len(my_files)))

    result = [f.split('/')[0] for f in all_files if f in [g.split('/') for g in my_files]]
    print (result)


def main():
    check_exists()

if __name__ == "__main__":
    main()