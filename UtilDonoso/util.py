#!/usr/bin/env python3

# Santiago Larrain
# slarrain@uchicago.edu
#
# Very simple and ugly script for Rodrigo Donoso's needs
#

import sys

def remove (filename):
    '''
    Fix a CSV according to Rodrigo Donoso's needs
    '''

    with open(filename, 'r') as f:

        # Open the writefile
        outf = open ('out_'+filename, 'w')

        for line in f:

            if line[:10]=='reviewerID':
                outf.writelines("ID,Pnd\n")
                header = line.split(',')

            else:
                line = line.split(',')
                id_name = line[0]
                for n in range(len(line)):
                    if line[n]=='t':
                        outf.writelines(id_name+','+header[n]+'\n')

        outf.close()


if __name__ == '__main__':

    if len(sys.argv) == 1:
        print ('Usage: python %s infile.csv', argv[0])
    elif len(sys.argv) == 2:
        remove(sys.argv[1])
    else:
        print ('Usage: python rws.py testfile.in no-comments')
