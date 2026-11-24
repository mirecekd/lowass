# scripts/voices_engine.py
"""sherpa-onnx part of the voices spike: model download, offline diarization, speaker embeddings."""
from __future__ import annotations

import tarfile
from pathlib import Path

import numpy as np

from scripts.voices_core import Segment

MODELS_DIR = Path.home() / ".cache" / "lowass" / "models"
RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
SEG_URL = RELEASES + "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMB_URL = RELEASES + "speaker-recongition-models/"
SEGMENTATION = MODELS_DIR / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
EMBEDDINGS = {
    "wespeaker": "wespeaker_en_voxceleb_resnet34_LM.onnx",
    "campplus": "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx",
    "eres2net": "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
    "titanet": "nemo_en_titanet_small.onnx",
    "eres2net-en": "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx",
    "campplus-en": "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx",
}
DEFAULT_EMBEDDING = "eres2net"
SAMPLE_RATE = 16000


def embedding_path(embedding: str) -> Path:
    return MODELS_DIR / EMBEDDINGS[embedding]


def _fetch(url: str, target: Path) -> None:
    if not url.startswith("https://"):
        raise ValueError(f"only https downloads are allowed: {url}")
    import requests  # a project dependency; unlike urllib it speaks only http(s)

    print(f"downloading {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(target, "wb") as out:
                out.writelines(resp.iter_content(1 << 20))
    except OSError as exc:  # requests.RequestException is an OSError too
        target.unlink(missing_ok=True)  # a half-written model must not look downloaded
        raise SystemExit(f"download of {url} failed: {exc}") from exc


def download(embedding: str) -> None:
    if not SEGMENTATION.exists():
        archive = MODELS_DIR / "segmentation.tar.bz2"
        _fetch(SEG_URL, archive)
        with tarfile.open(archive) as tar:
            tar.extractall(MODELS_DIR, filter="data")
        archive.unlink()
    if not embedding_path(embedding).exists():
        _fetch(EMB_URL + EMBEDDINGS[embedding], embedding_path(embedding))
    print(f"models ready in {MODELS_DIR}")


def check_models(embedding: str) -> None:
    if not SEGMENTATION.exists() or not embedding_path(embedding).exists():
        raise SystemExit("models are missing, run with --download first")


def load_audio(path: str) -> np.ndarray:
    """Mono float32 at 16 kHz."""
    import soundfile as sf  # pyright: ignore[reportMissingImports]
    from scipy.signal import resample_poly

    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    if rate != SAMPLE_RATE:
        mono = resample_poly(mono, SAMPLE_RATE, rate).astype(np.float32)
    return mono


def diarize(audio: np.ndarray, embedding: str, num_speakers: int = -1, threshold: float = 0.5) -> list[Segment]:
    import sherpa_onnx as so  # pyright: ignore[reportMissingImports]

    config = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(
            pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(SEGMENTATION), window_shift_ratio=0.1)),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=str(embedding_path(embedding)), num_threads=4),
        clustering=so.FastClusteringConfig(num_clusters=num_speakers, threshold=threshold),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise SystemExit("sherpa-onnx rejected the config, check the model files")
    result = so.OfflineSpeakerDiarization(config).process(audio).sort_by_start_time()
    return [Segment(r.start, r.end, r.speaker) for r in result]


class Embedder:
    """One speaker embedding per audio slice."""

    def __init__(self, embedding: str):
        import sherpa_onnx as so  # pyright: ignore[reportMissingImports]

        self._extractor = so.SpeakerEmbeddingExtractor(
            so.SpeakerEmbeddingExtractorConfig(model=str(embedding_path(embedding)), num_threads=4))

    def embed(self, audio: np.ndarray, seg: Segment) -> np.ndarray:
        stream = self._extractor.create_stream()
        stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=audio[int(seg.start * SAMPLE_RATE):int(seg.end * SAMPLE_RATE)])
        stream.input_finished()
        return np.array(self._extractor.compute(stream), dtype=np.float32)
