FROM python:3.7-alpine

RUN pip install requests mysql-connector-python

ADD fintual.py /
ADD credentials.ini /

CMD [ "python", "./fintual.py" ]
