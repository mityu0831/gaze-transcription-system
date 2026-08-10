from pathlib import Path
import torchaudio
from silero_vad import load_silero_vad, read_audio, get_speech_timestamps, collect_chunks

def silence_remove(audio_path, sampling_rate):
    # 1. モデルの読み込み
    model = load_silero_vad(onnx=False)
    audio = read_audio(audio_path, sampling_rate=sampling_rate)

    # 2. 無音を除いた発話区間を検出（秒単位で出力）
    segments = get_speech_timestamps(audio, model, sampling_rate=sampling_rate)

    # 3. 無音区間を除去して 1 本に連結
    speech_audio = collect_chunks(segments, audio)
    # 4. WAV 保存
    out_path = Path(audio_path).with_suffix(".speech.wav")
    torchaudio.save(
        out_path,
        speech_audio.unsqueeze(0),    # (channels=1, samples=N)
        sampling_rate
    )
    # 5. 保存先パスを返す
    return out_path
    