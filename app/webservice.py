from fastapi import FastAPI, File, UploadFile, Query, applications
from fastapi.responses import StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
from faster_whisper import WhisperModel
from app.utils import ResultWriter, WriteTXT, WriteSRT, WriteVTT, WriteTSV, WriteJSON, LANGUAGES
import importlib.metadata
import torch
import fastapi_offline_swagger_ui
import os
from os import path
import ffmpeg
from typing import BinaryIO, Union
import numpy as np
from io import StringIO
from threading import Lock

SAMPLE_RATE = 16000
LANGUAGE_CODES = sorted(list(LANGUAGES.keys()))

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

assets_path = fastapi_offline_swagger_ui.__path__[0]
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

model_path = os.getenv("ASR_MODEL_PATH")
if torch.cuda.is_available():
    model = WhisperModel(model_path, device="cuda")
else:
    model = WhisperModel(model_path, device="cpu")
model_lock = Lock()


@app.get("/", response_class=RedirectResponse, include_in_schema=False)
async def index():
    return "/docs"


@app.post("/asr", tags=["Endpoints"])
def transcribe(
        audio_file: UploadFile = File(...),
        task: Union[str, None] = Query(default="transcribe", enum=["transcribe", "translate"]),
        language: Union[str, None] = Query(default=None, enum=LANGUAGE_CODES),
        initial_prompt: Union[str, None] = Query(default=None),
        output: Union[str, None] = Query(default="txt", enum=["txt", "vtt", "srt", "tsv", "json"]),
):
    result = run_asr(audio_file.file, task, language, initial_prompt)
    filename = audio_file.filename.split('.')[0]
    outFile = StringIO()
    if output == "srt":
        WriteSRT(ResultWriter).write_result(result, file=outFile)
    elif output == "vtt":
        WriteVTT(ResultWriter).write_result(result, file=outFile)
    elif output == "tsv":
        WriteTSV(ResultWriter).write_result(result, file=outFile)
    elif output == "json":
        WriteJSON(ResultWriter).write_result(result, file=outFile)
    elif output == "txt":
        WriteTXT(ResultWriter).write_result(result, file=outFile)
    else:
        return 'Please select an output method!'
    outFile.seek(0)
    return StreamingResponse(outFile, media_type="text/plain",
                             headers={'Content-Disposition': f'attachment; filename="{filename}.{output}"'})


def run_asr(file: BinaryIO, task: Union[str, None], language: Union[str, None], initial_prompt: Union[str, None]):
    audio = load_audio(file)
    options_dict = {
        "task": task,
        "beam_size": 5}
    if language:
        options_dict["language"] = language
    if initial_prompt:
        options_dict["initial_prompt"] = initial_prompt
    with model_lock:
        result = model.transcribe(audio, **options_dict)

    return result


def load_audio(file: BinaryIO, sr: int = SAMPLE_RATE):
    """
    Open an audio file object and read as mono waveform, resampling as necessary.
    Modified from https://github.com/openai/whisper/blob/main/whisper/audio.py to accept a file object
    Parameters
    ----------
    file: BinaryIO
        The audio file like object
    sr: int
        The sample rate to resample the audio if necessary
    Returns
    -------
    A NumPy array containing the audio waveform, in float32 dtype.
    """
    try:
        # This launches a subprocess to decode audio while down-mixing and resampling as necessary.
        # Requires the ffmpeg CLI and `ffmpeg-python` package to be installed.
        out, _ = (
            ffmpeg.input("pipe:", threads=0)
            .output("-", format="s16le", acodec="pcm_s16le", ac=1, ar=sr)
            .run(cmd="ffmpeg", capture_stdout=True, capture_stderr=True, input=file.read())
        )
    except ffmpeg.Error as e:
        raise RuntimeError(f"Failed to load audio: {e.stderr.decode()}") from e

    return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0
