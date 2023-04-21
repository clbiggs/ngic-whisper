#!/bin/bash

# Settings
api_host="localhost:9000"
api_method="openapi-whisper"
api_task="transcribe"
api_encode="true"
api_output="json"


# Parameters
audioSourceDir=""
resultOutputDir=""
iterations=4
testName=""
randomizeName=0

if [ $# -eq 0 ]; then
    printf "***************************\n"
    printf -- "--testName={string} Name of test (optional)\n"
    printf -- "--randomizeName Randomizes test name (testName-randomChars)"
    printf -- "--iterations={number} Number of iterations per file (default: 4)\n"
    printf -- "--audioSourceDir={path} Source of audio files\n"
    printf -- "--resultOutputDir={path} Destination path for output\n"
    printf "***************************\n"
    exit 1
fi


while [ $# -gt 0 ]; do
  case "$1" in
    --audioSourceDir=*)
      audioSourceDir="${1#*=}"
      ;;
    --resultOutputDir=*)
      resultOutputDir="${1#*=}"
      ;;
    --iterations=*)
      iterations="${1#*=}"
      ;;
    --testName=*)
      testName="${1#*=}"
      ;;
    --randomizeName)
      randomizeName=1
      ;;
    --apiHost=*)
      api_host="${1#*=}"
      ;;
    --apiMethod=*)
      api_method="${1#*=}"
      ;;
    *)
      printf "***************************\n"
      printf "* Error: Invalid argument. '%s'*\n" "$1"
      printf "***************************\n"
      exit 1
  esac
  shift
done

if [ -z "$audioSourceDir" ]; then
    printf "audioSourceDir value is required\n"
    exit 1
fi
if [ -z "$resultOutputDir" ]; then
    printf "resultOutputDir value is required\n"
    exit 1
fi

test_start=$SECONDS
full_test_name="$testName"

if [ $randomizeName -ne 0 ]; then
      uid=$(echo $(uuidgen) | sed 's/[-]//g' | head -c 20;)
      full_test_name="${testName:+$testName-}$uid"
fi

full_output_path=$(echo "${resultOutputDir:+$resultOutputDir/}$full_test_name" | sed 's#//#/#g')
full_api_url="http://${api_host}/asr?method=${api_method}&task=${api_task}&encode=${api_encode}&output=${api_output}"

printf "Test Name: %s\n" "$full_test_name"
printf "Audio Source Dir: %s\n" "$audioSourceDir"
printf "Result Out Dir: %s\n" "$full_output_path"
printf "API Url: %s\n" "$full_api_url"
printf "Iterations: %s\n\n" "$iterations"

if ! mkdir -p "$full_output_path";
then
    printf "Failed to create output directory\n"
    exit 5
fi
# Loop through all files in audio source directory
for audioFile in "$audioSourceDir"/*;
do
    for (( i = 0; i < iterations; i++ )); do
        printf "Processing '%s' iteration %s\n" "$audioFile" "$((i+1))"
        full_filename=$(basename "$audioFile")
        extension="${full_filename##*.}"
        filename="${full_filename%.*}"

        output_filename="${full_filename}__${i}.json"
        output_headers_filename="${full_filename}__${i}_headers.txt"
        full_output_filepath=$(echo "${full_output_path:+$full_output_path/}$output_filename" | sed 's#//#/#g')
        full_output_headers_filepath=$(echo "${full_output_path:+$full_output_path/}$output_headers_filename" | sed 's#//#/#g')

        printf "Output will be saved to '%s'\n" "$full_output_filepath"

        start=$SECONDS

        #Call API and SAVE response
        printf "Calling API\n"

        curl --location "$full_api_url" \
          --header 'Content-Type: multipart/form-data' \
          --header 'Accept: application/json' \
          --form "audio_file=@\"$audioFile\"" \
          -o "$full_output_filepath" -D "$full_output_headers_filepath";

        duration=$((SECONDS - start))
        printf "\nCompleted '%s' iteration %s in %s seconds\n\n" "$audioFile" "$i" "$duration"


    done
done


printf "\n***************************\n"
printf " Test Complete. '%s' seconds\n" "$((SECONDS - test_start))"
printf "***************************\n\n"