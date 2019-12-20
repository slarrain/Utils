#!/bin/bash

# Not working
sudo dnf install ~/Download/hamster-time-tracker-1.04-5.el7.noarch.rpm

sudo sed -i -e 's/python/python2/' /usr/bin/hamster

sudo sed -i -e 's/python/python2/' /usr/bin/hamster-service

sudo sed -i -e 's/python/python2/' /usr/bin/hamster-windows-service