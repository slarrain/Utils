#!/bin/bash

if [ ! -d "/media/nas" ]; then
	sudo mkdir /media/nas
fi

sudo mount 192.168.1.122:/media/data /media/nas
