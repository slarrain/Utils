import pandas as pd
from matplotlib import pyplot as plt
import sys

plt.rcParams['figure.figsize'] = (16.0, 12.0) # Big size plot

def main():
    filename = sys.argv[1] # The name of the iperf log file is the first argument of the script
    plot_title = filename.split('/')[-1].split('.')[0]  # Just take the name
    df = pd.read_csv(
            filename,
            skiprows=[0,1,2],  # The first 3 rows do not hold data
            skipfooter=6,  # The last 6 don't either
            header=None,  # we do not load the header
            sep=r'\s+',  # This delimiter parses the content correctly
                )
    df.rename(
        columns={  # Rename the important columns
            4:'Transfer', 
            6:'Bandwidth', 
            5:'transfer_metric'
            }, 
        inplace=True  # Do it inplace on the df
        )
    df['seconds'] = df[2].str.split('-').apply(
        lambda x: x[-1]
        ).astype(float)  # Take the last second of the interval and use that to plot
    df.Transfer = df.Transfer.astype(float)  # Tranfer should be a float

    # This fixes the problem where some data is in MBytes and some other on Kilobytes
    df.Transfer = df.loc[:, ['Transfer', 'transfer_metric']].apply(lambda x: 0.001*x[0] if x[1] == 'KBytes' else x[0], axis=1)

    # Create the 2 plots
    make_plot(df, "Transfer", "blue", plot_title, "MBytes")
    make_plot(df, "Bandwidth", "green", plot_title, "Mbits/sec")


def make_plot(df, y, color, title, label):
    ax = df.plot.line(
        x='seconds', 
        y=y, 
        color=color, 
        title=title)
    ax.set_ylabel(label)
    plt.savefig(title + "_" + y + '.png')


if __name__ == "__main__":
    main()
    # Usage
    # python3 plot_iperf.py ClientPC1-PC7.txt