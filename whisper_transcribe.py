import os
import time
import torch
from pathlib import Path
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

# =========================
# オフライン強制（任意だけど推奨）
# ネットに行く挙動を完全に止めたい場合は有効
# =========================
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

# =========================
# デバイス設定
# =========================
use_cuda = torch.cuda.is_available()
device_str = "cuda:0" if use_cuda else "cpu"
torch_dtype = torch.float16 if use_cuda else torch.float32

# pipeline の device は "cuda:0" 文字列ではなく
# GPU: 0 / CPU: -1 を渡すのが安定です
pipe_device = 0 if use_cuda else -1

# =========================
# ★ローカルモデルパス（ここが最重要）
# whisper_transcribe.py と同じフォルダを基準に models/ を参照
# =========================
BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models" / "whisper-large-v3"

# （念のため）モデルフォルダが存在するかチェック
if not MODEL_DIR.exists():
    raise FileNotFoundError(f"Model folder not found: {MODEL_DIR}")

# =========================
# ローカルから読み込み（ネットに行かない）
# =========================
model = AutoModelForSpeechSeq2Seq.from_pretrained(
    MODEL_DIR,
    torch_dtype=torch_dtype,
    low_cpu_mem_usage=True,
    use_safetensors=True,
    local_files_only=True,   # ★オフライン必須
)
model.to(device_str)

processor = AutoProcessor.from_pretrained(
    MODEL_DIR,
    local_files_only=True,   # ★オフライン必須
)

pipe = pipeline(
    "automatic-speech-recognition",
    model=model,
    tokenizer=processor.tokenizer,
    feature_extractor=processor.feature_extractor,
    chunk_length_s=30,
    batch_size=2,
    torch_dtype=torch_dtype,
    device=pipe_device,      # ★ 0 or -1
)

def whisper_transcribe(audio_path):
    audio_input = str(audio_path) if isinstance(audio_path, Path) else audio_path

    generate_kwargs = {
        "language": "japanese",
        "task": "transcribe",
        "repetition_penalty": 1.3,
    }

    result = pipe(
        audio_input,
        return_timestamps=True,
        generate_kwargs=generate_kwargs,
    )

    print(result.get("chunks", []))
    return result
