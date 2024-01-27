import os
import re
import uuid
import base64
import torch
import torchaudio
import requests
import logging
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import Xtts

try:
    import deepspeed

    deepspeed_available = True
except:
    deepspeed_available = False


def download_xtts():
    files_to_download = {
        "LICENSE.txt": "https://huggingface.co/coqui/XTTS-v2/resolve/v2.0.2/LICENSE.txt?download=true",
        "README.md": "https://huggingface.co/coqui/XTTS-v2/resolve/v2.0.2/README.md?download=true",
        "config.json": "https://huggingface.co/coqui/XTTS-v2/resolve/v2.0.2/config.json?download=true",
        "model.pth": "https://huggingface.co/coqui/XTTS-v2/resolve/v2.0.2/model.pth?download=true",
        "dvae.pth": "https://huggingface.co/coqui/XTTS-v2/resolve/v2.0.2/dvae.pth?download=true",
        "mel_stats.pth": "https://huggingface.co/coqui/XTTS-v2/resolve/v2.0.2/mel_stats.pth?download=true",
        "speakers_xtts.pth": "https://huggingface.co/coqui/XTTS-v2/resolve/v2.0.2/speakers_xtts.pth?download=true",
        "vocab.json": "https://huggingface.co/coqui/XTTS-v2/resolve/v2.0.2/vocab.json?download=true",
    }
    os.makedirs(os.path.join(os.getcwd(), "xttsv2_2.0.2"), exist_ok=True)
    for filename, url in files_to_download.items():
        destination = os.path.join(os.getcwd(), "xttsv2_2.0.2", filename)
        if not os.path.exists(destination):
            logging.info(f"[CTTS] Downloading {filename} for XTTSv2...")
            response = requests.get(url, stream=True)
            block_size = 1024  # 1 Kibibyte
            with open(destination, "wb") as file:
                for data in response.iter_content(block_size):
                    file.write(data)


class CTTS:
    def __init__(self):
        global deepspeed_available
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.device == "cuda":
            torch.cuda.empty_cache()
        checkpoint_dir = os.path.join(os.getcwd(), "xttsv2_2.0.2")
        if not os.path.exists(checkpoint_dir):
            download_xtts()
        config = XttsConfig()
        config.load_json(str(os.path.join(checkpoint_dir, "config.json")))
        self.model = Xtts.init_from_config(config)
        self.model.load_checkpoint(
            config,
            checkpoint_dir=str(checkpoint_dir),
            vocab_path=str(os.path.join(checkpoint_dir, "vocab.json")),
            use_deepspeed=deepspeed_available,
        )
        self.model.to(self.device)
        self.output_folder = os.path.join(os.getcwd(), "outputs")
        os.makedirs(self.output_folder, exist_ok=True)
        self.voices_path = os.path.join(os.getcwd(), "voices")
        wav_files = []
        for file in os.listdir(self.voices_path):
            if file.endswith(".wav"):
                wav_files.append(file.replace(".wav", ""))
        self.voices = wav_files

    async def generate(
        self,
        text,
        voice="default",
        language="en",
    ):
        output_file = os.path.join(self.output_folder, f"{uuid.uuid4().hex}.wav")
        cleaned_string = re.sub(r"([!?.])\1+", r"\1", text)
        cleaned_string = re.sub(
            r'[^a-zA-Z0-9\s\.,;:!?\-\'"\u0400-\u04FFÀ-ÿ\u0150\u0151\u0170\u0171]\$',
            "",
            cleaned_string,
        )
        cleaned_string = re.sub(r"\n+", " ", cleaned_string)
        text = cleaned_string.replace("#", "")
        if not voice.endswith(".wav"):
            voice = f"{voice}.wav"
        audio_path = os.path.join(self.voices_path, voice)
        if not os.path.exists(audio_path):
            audio_path = os.path.join(self.voices_path, "default.wav")
        gpt_cond_latent, speaker_embedding = self.model.get_conditioning_latents(
            audio_path=[f"{audio_path}"],
            gpt_cond_len=self.model.config.gpt_cond_len,
            max_ref_length=self.model.config.max_ref_len,
            sound_norm_refs=self.model.config.sound_norm_refs,
        )
        output = self.model.inference(
            text=text,
            language=language,
            gpt_cond_latent=gpt_cond_latent,
            speaker_embedding=speaker_embedding,
            temperature=0.7,
            length_penalty=float(self.model.config.length_penalty),
            repetition_penalty=10.0,
            top_k=int(self.model.config.top_k),
            top_p=float(self.model.config.top_p),
            enable_text_splitting=True,
        )
        torchaudio.save(output_file, torch.tensor(output["wav"]).unsqueeze(0), 24000)
        with open(output_file, "rb") as file:
            audio_data = file.read()
        os.remove(output_file)
        return base64.b64encode(audio_data).decode("utf-8")


if __name__ == "__main__":
    download_xtts()
