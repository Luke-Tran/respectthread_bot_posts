#!/bin/bash

while :
do
git pull origin master
python3 respectthread_bot_sql.py
sleep 30
done
