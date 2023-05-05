import datetime
import logging
import re
import time

from fastapi import FastAPI, File, UploadFile, Query, applications
from fastapi.responses import StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
import whisper
from whisper.utils import ResultWriter, WriteTXT, WriteSRT, WriteVTT, WriteTSV, WriteJSON
from whisper import tokenizer
from faster_whisper import WhisperModel
from .faster_whisper.utils import (
    model_converter as faster_whisper_model_converter,
    ResultWriter as faster_whisper_ResultWriter,
    WriteTXT as faster_whisper_WriteTXT,
    WriteSRT as faster_whisper_WriteSRT,
    WriteVTT as faster_whisper_WriteVTT,
    WriteTSV as faster_whisper_WriteTSV,
    WriteJSON as faster_whisper_WriteJSON,
)
import os
from os import path
from pathlib import Path
import ffmpeg
from typing import BinaryIO, Union
import numpy as np
from io import StringIO
from threading import Lock
import torch
import importlib.metadata

from .timer import Timer

setupTimer = Timer(name="setup")
setupTimer.start()

SAMPLE_RATE = 16000
LANGUAGE_CODES = sorted(list(tokenizer.LANGUAGES.keys()))

logging.basicConfig(level=logging.NOTSET)

projectMetadata = importlib.metadata.metadata('ngic-whisper')
app = FastAPI(
    title=projectMetadata['Name'].title().replace('-', ' '),
    description=projectMetadata['Summary'],
    version=projectMetadata['Version'],
    contact={
        "url": projectMetadata['Home-page']
    },
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
    license_info={
        "name": "MIT License",
        "url": projectMetadata['License']
    }
)

assets_path = os.getcwd() + "/swagger-ui-assets"
if path.exists(assets_path + "/swagger-ui.css") and path.exists(assets_path + "/swagger-ui-bundle.js"):
    app.mount("/assets", StaticFiles(directory=assets_path), name="static")


    def swagger_monkey_patch(*args, **kwargs):
        return get_swagger_ui_html(
            *args,
            **kwargs,
            swagger_favicon_url="",
            swagger_css_url="/assets/swagger-ui.css",
            swagger_js_url="/assets/swagger-ui-bundle.js",
        )


    applications.get_swagger_ui_html = swagger_monkey_patch

setupTimer.time_step("app-setup")

app.whisper_model_name = os.getenv("ASR_MODEL", "base")
logging.info("Using ASR model: '{}'".format(app.whisper_model_name))

faster_whisper_model_path_base = os.getenv("FAST_MODEL_PATH", "/root/.cache/faster_whisper")
logging.info("Fast Model Path: '{}'".format(faster_whisper_model_path_base))

app.whisper_model: any
app.faster_whisper_model: any


def load_model(model_name: str):
    logging.info("Loading Model: '{}'".format(model_name))
    faster_whisper_model_path = os.path.join(faster_whisper_model_path_base, model_name)
    faster_whisper_model_converter(model_name, faster_whisper_model_path)
    logging.info("Fast Model converted")

    if torch.cuda.is_available():
        logging.info("Using cuda device")
        app.whisper_model = whisper.load_model(model_name).cuda()
        app.faster_whisper_model = WhisperModel(faster_whisper_model_path, device="cuda", compute_type="float16")
    else:
        logging.info("Using cpu device")
        app.whisper_model = whisper.load_model(model_name)
        app.faster_whisper_model = WhisperModel(faster_whisper_model_path)


setupTimer.time_step("whisper-model-setup")
load_model(app.whisper_model_name)
model_lock = Lock()

setupTimer.time_step("whisper-model-loaded")


def get_model(method: str = "openai-whisper"):
    if method == "faster-whisper":
        return app.faster_whisper_model
    return app.whisper_model


@app.get("/", response_class=RedirectResponse, include_in_schema=False)
async def index():
    return "/docs"


@app.post("/changemodel", tags=["Endpoints"])
def changemodel(
        model: Union[str, None] = Query(default="base", enum=["tiny", "base", "small", "medium", "large", "large-v2"])
):
    if model is None or model == app.whisper_model_name:
        return {"old_model": app.whisper_model_name, "new_model": app.whisper_model_name}

    oldmodel = app.whisper_model_name

    with model_lock:
        load_model(model)
        app.whisper_model_name = model

    return {"old_model": oldmodel, "new_model": model}


@app.post("/asr", tags=["Endpoints"])
def transcribe(
        method: Union[str, None] = Query(default="openai-whisper", enum=["openai-whisper", "faster-whisper"]),
        task: Union[str, None] = Query(default="transcribe", enum=["transcribe", "translate"]),
        language: Union[str, None] = Query(default=None, enum=LANGUAGE_CODES),
        initial_prompt: Union[str, None] = Query(default=None),
        audio_file: UploadFile = File(...),
        encode: bool = Query(default=True, description="Encode audio first through ffmpeg"),
        output: Union[str, None] = Query(default="json", enum=["txt", "vtt", "srt", "tsv", "json"])
):
    filename = audio_file.filename.split('.')[0]
    result = run_asr(audio_file.file, task, language, initial_prompt, method, audio_file.filename, encode)
    myFile = StringIO()
    write_result(result, myFile, output, method)
    myFile.seek(0)
    return StreamingResponse(myFile, media_type="text/plain",
                             headers={'Content-Disposition': f'attachment; filename="{filename}.{output}"'})


@app.post("/detect-language", tags=["Endpoints"])
def language_detection(
        audio_file: UploadFile = File(...),
        method: Union[str, None] = Query(default="openai-whisper", enum=["openai-whisper", "faster-whisper"]),
        encode: bool = Query(default=True, description="Encode audio first through ffmpeg")
):
    # load audio and pad/trim it to fit 30 seconds
    audio = load_audio(audio_file.file, encode)
    audio = whisper.pad_or_trim(audio)

    # detect the spoken language
    with model_lock:
        model = get_model(method)
        if method == "faster-whisper":
            segments, info = model.transcribe(audio, beam_size=5)
            detected_lang_code = info.language
        else:
            # make log-Mel spectrogram and move to the same device as the model
            mel = whisper.log_mel_spectrogram(audio).to(model.device)
            _, probs = model.detect_language(mel)
            detected_lang_code = max(probs, key=probs.get)

        result = {"detected_language": tokenizer.LANGUAGES[detected_lang_code], "language_code": detected_lang_code}

    return result


def run_asr(
        file: BinaryIO,
        task: Union[str, None],
        language: Union[str, None],
        initial_prompt: Union[str, None],
        method: Union[str, None],
        fileid: Union[str, None],
        encode=True
):
    asrTimer = Timer(name="asrTimer")
    asrTimer.start()

    audio, duration = load_audio(file, encode)

    asrTimer.time_step("loaded-audio")

    options_dict = {"task": task}
    if language:
        options_dict["language"] = language
    if initial_prompt:
        options_dict["initial_prompt"] = initial_prompt

    with model_lock:
        model = get_model(method)

        asrTimer.time_step("model-loaded")

        logging.info("Asr Method: '{}'".format(method))

        if method == "faster-whisper":
            segments = []
            text = ""
            i = 0
            segment_generator, info = model.transcribe(audio, beam_size=5, **options_dict)
            for segment in segment_generator:
                segments.append(segment)
                text = text + segment.text
            result = {
                "language": options_dict.get("language", info.language),
                "segments": segments,
                "text": text,
            }
            if duration < 0:
                duration = info.duration
        else:
            result = model.transcribe(audio, **options_dict)

        result["method"] = method
        result["gpu"] = torch.cuda.is_available()
        result["model"] = app.whisper_model_name
        result["length"] = duration
        result["file_id"] = fileid

        asrTimer.time_step("transcribed")
        asrTimer.stop()

        result["timings"] = asrTimer.steps

    return result


def write_result(
        result: dict, file: BinaryIO, output: Union[str, None], method: Union[str, None]
):
    if method == "faster-whisper":
        if output == "srt":
            faster_whisper_WriteSRT(ResultWriter).write_result(result, file=file)
        elif output == "vtt":
            faster_whisper_WriteVTT(ResultWriter).write_result(result, file=file)
        elif output == "tsv":
            faster_whisper_WriteTSV(ResultWriter).write_result(result, file=file)
        elif output == "json":
            faster_whisper_WriteJSON(ResultWriter).write_result(result, file=file)
        elif output == "txt":
            faster_whisper_WriteTXT(ResultWriter).write_result(result, file=file)
        else:
            return 'Please select an output method!'
    else:
        if output == "srt":
            WriteSRT(ResultWriter).write_result(result, file=file)
        elif output == "vtt":
            WriteVTT(ResultWriter).write_result(result, file=file)
        elif output == "tsv":
            WriteTSV(ResultWriter).write_result(result, file=file)
        elif output == "json":
            WriteJSON(ResultWriter).write_result(result, file=file)
        elif output == "txt":
            WriteTXT(ResultWriter).write_result(result, file=file)
        else:
            return 'Please select an output method!'


def load_audio(file: BinaryIO, encode=True, sr: int = SAMPLE_RATE):
    """
    Open an audio file object and read as mono waveform, resampling as necessary.
    Modified from https://github.com/openai/whisper/blob/main/whisper/audio.py to accept a file object
    Parameters
    ----------
    file: BinaryIO
        The audio file like object
    encode: Boolean
        If true, encode audio stream to WAV before sending to whisper
    sr: int
        The sample rate to resample the audio if necessary
    Returns
    -------
    A NumPy array containing the audio waveform, in float32 dtype.
    """
    duration = -1
    if encode:
        try:
            # This launches a subprocess to decode audio while down-mixing and resampling as necessary.
            # Requires the ffmpeg CLI and `ffmpeg-python` package to be installed.
            out, stdo = (
                ffmpeg.input("pipe:", threads=0)
                .output("-", format="s16le", acodec="pcm_s16le", ac=1, ar=sr)
                .run(cmd="ffmpeg", capture_stdout=True, capture_stderr=True, input=file.read())
            )
            matches = re.findall(r"time=(?P<duration>\d+:\d+:\d+[.]\d+)", stdo.decode(), re.IGNORECASE)
            if len(matches) > 0:
                x = time.strptime(matches[-1], '%H:%M:%S.%f')
                duration = x.tm_sec + x.tm_min * 60 + x.tm_hour * 3600
        except ffmpeg.Error as e:
            raise RuntimeError(f"Failed to load audio: {e.stderr.decode()}") from e
    else:
        out = file.read()

    return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0, duration


setupTimer.stop()
