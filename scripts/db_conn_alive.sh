#!/usr/bin/env bash

#Declare the DB names and initialize them as False
declare -A dbs=(
    [CERT_Pyme]=false
    [CERT_Ssilver]=false
    [CERT_Golden]=false
    [CERT_Internacional]=false
    [CERT_Platinum]=false
    [CERT_Trial]=false
    [CERT_SmartFinancial]=false
)
# source db ini
. ~/github/defontana2/smart_finance/credentials.ini 

# Some harcoded variables
CHECK_OK="(1 rows affected)"
QUERY='select top 1 1 from dbo.'
OK=":large_blue_circle:"
BAD=":red_circle:"
TABLE_DEFAULT="docvtaenc"
TABLE_SMART="cesiones"

# For every DB in the list
for db in ${!dbs[@]}; do
    # If the DB is Smartfinancial, change the table
    if [[ $db == "CERT_SmartFinancial" ]]; then
        table=$TABLE_SMART
    else
        table=$TABLE_DEFAULT
    fi

    # Run the query
    rv=$(/opt/mssql-tools/bin/sqlcmd -U $user -P $password -S $host -d $db -Q "$QUERY$table")

    # Check if we got a valid result and change to the corresponding emoticon
    if [[ $rv == *"$CHECK_OK"* ]] 
    then
        dbs[$db]=$OK
    else
        dbs[$db]=$BAD
    fi
done 

# Create a single line variable with the emoticions
TOP=""
for db in ${!dbs[@]}; do
    TOP+="${dbs[$db]} " 
done

echo "DBs: $TOP"
echo "---"
# For the Dropdown, give me the DB name as well
for db in ${!dbs[@]}; do
    echo "$db ${dbs[$db]}" 
done
