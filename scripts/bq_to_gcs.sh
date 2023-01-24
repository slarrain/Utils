#!/usr/bin/env bash
datasets=$(bq ls | awk '{print $1}' | tail +3)

for dataset in $datasets
do
	tables=$(bq ls $dataset | awk '{print $1}' | tail +3)
	
	for table in $tables
	do
		echo "$dataset.$table"
		bq extract --destination_format "AVRO" --compression "SNAPPY" "secom-208521:$dataset.$table" "gs://secom-desarrollos/BU/$dataset/$table-*.avro"
	done
done


