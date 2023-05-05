#!/bin/bash

# Settings

test_details_filename="test_details.txt"
results_glob_filter="*.json"

# Parameters
sourceDir=""
outputCSVFile=""

if [ $# -eq 0 ]; then
    printf "***************************\n"
    printf -- "--sourceDir={path} Directory source of results\n"
    printf -- "--outputCSVFile={path} Output csv file path\n"
    printf "***************************\n"
    exit 1
fi


while [ $# -gt 0 ]; do
  case "$1" in
    --sourceDir=*)
      sourceDir="${1#*=}"
      ;;
    --outputCSVFile=*)
      outputCSVFile="${1#*=}"
      ;;
    *)
      printf "***************************\n"
      printf "* Error: Invalid argument. '%s'*\n" "$1"
      printf "***************************\n"
      exit 1
  esac
  shift
done

rm -f "$outputCSVFile"

echo "file_id, length, whisper_method, gpu, model, audio_load, model_load, transcribe, elapsed" > "$outputCSVFile"

source_files=$(echo "${sourceDir:+$sourceDir/}$results_glob_filter" | sed 's#//#/#g')

# Loop through all files in audio source directory (shuffled)
for test_result in $source_files;
do
  echo "$test_result"
  datarow="$(jq -r -f program.jq "$test_result")"
  echo "$datarow" >> "$outputCSVFile"
  echo "$datarow"
done