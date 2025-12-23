import os
import tempfile
import asyncio
import nest_asyncio
import edge_tts
import torch
import torchaudio
import numpy as np

# Apply nest_asyncio to allow nested event loops (crucial for Django)
nest_asyncio.apply()

class FreeTTSService:
    """
    Service for free voice cloning/TTS.
    Primary: Microsoft Edge TTS (Free, High Quality, Male/Female)
    Fallback: gTTS (Google)
    """

    def __init__(self):
        self.use_coqui = False
        self.tts = None
        self.device = "cpu"
        self.ffmpeg_available = False

        # CRITICAL: Force torchaudio to use soundfile (bypass torchcodec)
        import os
        os.environ["COQUI_TOS_AGREED"] = "1"  # Auto-agree to Coqui license

        # Check for Coqui TTS (needed for cloning)
        try:
            import torch
            import torchaudio
            import soundfile as sf
            
            # Monkey-patch torchaudio.load to use soundfile instead of torchcodec
            # This bypasses the torchcodec requirement completely
            original_load = torchaudio.load
            
            def soundfile_load(filepath, *args, **kwargs):
                """Load audio using soundfile instead of torchcodec"""
                data, samplerate = sf.read(filepath, dtype='float32')
                # Convert to torch tensor and add channel dimension if mono
                if len(data.shape) == 1:
                    data = data.reshape(1, -1)  # (samples,) -> (1, samples)
                else:
                    data = data.T  # (samples, channels) -> (channels, samples)
                return torch.from_numpy(data), samplerate
            
            # Replace torchaudio.load with our soundfile version
            torchaudio.load = soundfile_load
            
            from TTS.api import TTS
            
            self.use_coqui = True
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"✓ Coqui TTS available for Cloning. Using device: {self.device}")
            print(f"✓ Torchaudio.load patched to use soundfile (bypassing torchcodec)")
        except ImportError as e:
            print(f"✗ Coqui TTS not available - ImportError: {e}")
            print("  Cloning will use standard Edge TTS voices.")
            self.use_coqui = False
        except Exception as e:
            print(f"✗ Coqui TTS initialization error: {e}")
            print("  Cloning will use standard Edge TTS voices.")
            import traceback
            traceback.print_exc()
            self.use_coqui = False
        
        # Check FFmpeg availability (required for audio conversion)
        self.ffmpeg_available = self._check_ffmpeg()
        if not self.ffmpeg_available:
            print("⚠️  WARNING: FFmpeg not found in PATH!")
            print("   Audio file conversion (.m4a, .mp3, .webm) will fail.")
            print("   This may cause 'baby voice' issues in voice cloning.")
            print("   Install FFmpeg: https://ffmpeg.org/download.html")
        else:
            print("✓ FFmpeg available for audio conversion")

        # We define a mapping of simple voice IDs to Edge TTS voices
        self.voices = {
            "female_en": "en-US-AriaNeural",  # Mature adult female voice (was AnaNeural)
            "male_en": "en-US-GuyNeural",
            "female_gb": "en-GB-SoniaNeural",
            "male_gb": "en-GB-RyanNeural",
            
            # Spanish
            "female_es": "es-ES-ElviraNeural",
            "male_es": "es-ES-AlvaroNeural",
            
            # French
            "female_fr": "fr-FR-DeniseNeural",
            "male_fr": "fr-FR-HenriNeural",

            # German
            "female_de": "de-DE-KatjaNeural",
            "male_de": "de-DE-ConradNeural",
        }

    def initialize_model(self):
        """Initialize the TTS model (lazy loading)"""
        # Load Coqui if enabled and not loaded
        if self.use_coqui and self.tts is None:
            try:
                # CRITICAL: Set torchaudio backend BEFORE importing TTS
                import torchaudio
                try:
                    torchaudio.set_audio_backend("soundfile")
                    print("✓ Set torchaudio backend to soundfile")
                except Exception as e:
                    print(f"Warning: Could not set torchaudio backend: {e}")
                
                from TTS.api import TTS
                
                # Use XTTS v2 model
                self.model_name = "tts_models/multilingual/multi-dataset/xtts_v2" 
                print(f"Loading native TTS model: {self.model_name}...")
                self.tts = TTS(self.model_name).to(self.device)
                print(f"✓ XTTS v2 model loaded successfully on {self.device}")
                
            except Exception as e:
                print(f"✗ Failed to load Coqui Model: {e}")
                import traceback
                traceback.print_exc()
                self.use_coqui = False
                self.tts = None

    def text_to_speech_simple(self, text, output_path, voice_id="female_en"):
        """
        Generate speech using Edge TTS
        """
        # Get edge voice, default to US Female if not found
        edge_voice = self.voices.get(voice_id, "en-US-AriaNeural")  # Default to Aria (adult female)
        
        try:
            # Run async edge-tts in a sync wrapper
            asyncio.run(self._edge_generate(text, edge_voice, output_path))
            return output_path
        except Exception as e:
            print(f"Edge TTS failed: {e}. Falling back to gTTS.")
            return self._gtts_generate(text, output_path)

    async def _edge_generate(self, text, voice, output_path):
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)

    def text_to_speech_with_clone(self, text, speaker_wav_path, output_path, language="en"):
        """
        Attempt cloning if Coqui is enabled, otherwise use standard voice
        """
        if self.use_coqui:
            # Force initialize if not already done
            self.initialize_model()
            try:
                print(f"Attempting to clone voice from: {speaker_wav_path}")

                # Track temp files for cleanup (initialize outside try block)
                original_speaker_path = speaker_wav_path
                temp_converted_path = None
                processed_speaker_path = speaker_wav_path

                # Preprocess audio to fix "baby voice" (format/sample rate issues)
                try:
                    import librosa
                    import soundfile as sf
                    from pydub import AudioSegment

                    # LOGGING START
                    with open("debug_tts.log", "a") as log:
                        log.write(f"\n--- Processing: {speaker_wav_path} ---\n")

                    # Convert to WAV first if needed (fixes webm/m4a issues)
                    file_ext = os.path.splitext(speaker_wav_path)[1].lower()
                    if file_ext in ['.webm', '.m4a', '.mp4', '.ogg', '.mp3']:
                        if not self.ffmpeg_available:
                            raise Exception(
                                f"FFmpeg is required to convert {file_ext} files but is not installed or not in PATH. "
                                "Please install FFmpeg from https://ffmpeg.org/download.html and add it to your system PATH. "
                                "Without FFmpeg, voice cloning will produce poor quality 'baby voice' output."
                            )
                        print(f"Converting {file_ext} to WAV format using FFmpeg...")
                        audio = AudioSegment.from_file(speaker_wav_path)

                        # Convert to mono and set proper sample rate
                        audio = audio.set_channels(1)  # Force mono
                        audio = audio.set_frame_rate(22050)  # Set to XTTS input rate

                        # Save to temp WAV
                        temp_converted = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                        temp_converted.close()
                        audio.export(temp_converted.name, format="wav")
                        temp_converted_path = temp_converted.name
                        speaker_wav_path = temp_converted_path
                        print(f"Converted to WAV: {speaker_wav_path}")

                        with open("debug_tts.log", "a") as log:
                            log.write(f"Converted {file_ext} to WAV at 22050Hz Mono\n")

                    # 1. Load audio with librosa
                    # FORCE 22050Hz (XTTS_v2 input_sample_rate requirement)
                    # FORCE MONO=True (Stereo causes pitch issues)
                    print("Loading audio with librosa at 22050Hz Mono...")

                    y, sr = librosa.load(speaker_wav_path, sr=22050, mono=True)
                    
                    with open("debug_tts.log", "a") as log:
                        duration = librosa.get_duration(y=y, sr=sr)
                        log.write(f"Loaded Audio: Shape={y.shape}, SR={sr}, Duration={duration:.2f}s\n")

                    # Validate audio length (XTTS v2 needs 6+ seconds for best results)
                    if duration < 3.0:
                        raise Exception(
                            f"Reference audio too short ({duration:.1f}s). "
                            "XTTS v2 requires at least 6 seconds of clear speech for good voice cloning. "
                            "Please upload a longer voice sample."
                        )
                    elif duration < 6.0:
                        print(f"⚠️  Warning: Audio is {duration:.1f}s. 6+ seconds recommended for best results.")
                        with open("debug_tts.log", "a") as log:
                            log.write(f"Warning: Short audio ({duration:.1f}s). 6+ seconds recommended.\n")

                    # 2. Trim silence (Relaxed to 60db to avoid cutting speech)
                    # aggressive 20db was likely causing the "baby voice" by removing breath/intonation
                    y_trimmed, _ = librosa.effects.trim(y, top_db=60)
                    
                    if librosa.get_duration(y=y_trimmed, sr=sr) < 1.0:
                         print("Trimmed audio too short! Using original.")
                         with open("debug_tts.log", "a") as log: log.write("Trimmed < 1s. Reverting to original.\n")
                    else:
                         y = y_trimmed
                    
                    # 3. Save as temporary wav file
                    temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    temp_wav.close()

                    # Write at 22050Hz to match XTTS_v2 input_sample_rate
                    # Model will output at 24000Hz automatically
                    sf.write(temp_wav.name, y, 22050)

                    processed_speaker_path = temp_wav.name
                    print(f"SUCCESS: Audio preprocessed to 22050Hz Mono at: {processed_speaker_path}")
                    
                    with open("debug_tts.log", "a") as log:
                        log.write(f"Saved processed audio to {processed_speaker_path}\n")
                    
                except ImportError as e:
                    print(f"Library not installed: {e}. Using original file (may cause pitch issues)")
                    processed_speaker_path = speaker_wav_path
                    with open("debug_tts.log", "a") as log:
                        log.write(f"ImportError: {e}\n")
                except Exception as e:
                    print(f"Audio preprocessing failed: {e}. Using original file.")
                    processed_speaker_path = speaker_wav_path
                    with open("debug_tts.log", "a") as log:
                        log.write(f"Preprocessing Error: {e}\n")
                        import traceback
                        log.write(traceback.format_exc())
                
                
                # Use tts_to_file for proper voice cloning (recommended XTTS v2 API)
                print(f"Generating cloned voice using XTTS v2 tts_to_file method...")
                with open("debug_tts.log", "a") as log:
                    log.write(f"Using tts_to_file with speaker_wav: {processed_speaker_path}\n")
                    log.write(f"Text: {text}\n")
                    log.write(f"Language: {language}\n")
                
                # Use the high-level API that handles voice cloning correctly
                self.tts.tts_to_file(
                    text=text,
                    speaker_wav=processed_speaker_path,
                    file_path=output_path,
                    language=language,
                    split_sentences=True  # Better handling of longer texts
                )

                
                print(f"✓ Voice cloned successfully to: {output_path}")
                
                # Verify the output file
                import soundfile as sf
                data_verify, sr_verify = sf.read(output_path)
                duration = len(data_verify) / sr_verify
                
                with open("debug_tts.log", "a") as log:
                    log.write(f"Generated audio saved to: {output_path}\n")
                    log.write(f"Sample rate: {sr_verify}Hz, Duration: {duration:.2f}s, Shape: {data_verify.shape}\n")
                
                print(f"Generated audio: {sr_verify}Hz, {duration:.2f}s")    

                # Cleanup temp files
                if processed_speaker_path != original_speaker_path and os.path.exists(processed_speaker_path):
                    os.unlink(processed_speaker_path)

                if temp_converted_path and os.path.exists(temp_converted_path):
                    os.unlink(temp_converted_path)

                return output_path
            except Exception as e:
                print(f"\u2717 Coqui Voice Cloning failed: {e}")
                print(f"   Exception type: {type(e).__name__}")
                import traceback
                traceback.print_exc()
                with open("debug_tts.log", "a") as log:
                    log.write(f"\n=== VOICE CLONING ERROR ===\n")
                    log.write(f"Error: {e}\n")
                    log.write(f"Type: {type(e).__name__}\n")
                    log.write(traceback.format_exc())
                    log.write("\n")
                print("   Falling back to standard Edge TTS voice...")
        
        # Fallback to high-quality standard TTS
        # Map simple language code to a voice (e.g. 'en' -> 'female_en')
        default_voice = f"female_{language}" if f"female_{language}" in self.voices else "female_en"
        print(f"Cloning not active. Using standard high-quality voice: {default_voice}")
        return self.text_to_speech_simple(text, output_path, voice_id=default_voice)

    def _gtts_generate(self, text, output_path, language='en'):
        """Internal helper for gTTS generation"""
        try:
            from gtts import gTTS
            tts = gTTS(text=text, lang=language, slow=False)
            tts.save(output_path)
            return output_path
        except ImportError:
            raise Exception("gTTS not installed.")
        except Exception as e:
            raise Exception(f"gTTS error: {str(e)}")

    def get_supported_languages(self):
        """Get supported languages"""
        return ["en", "es", "fr", "de", "it", "pt", "zh-cn", "ja", "ko"]
    
    def _check_ffmpeg(self):
        """Check if FFmpeg is available in PATH"""
        try:
            from pydub.utils import which
            ffmpeg_path = which("ffmpeg")
            if ffmpeg_path:
                print(f"FFmpeg found at: {ffmpeg_path}")
                return True
            return False
        except Exception as e:
            print(f"Error checking FFmpeg: {e}")
            return False



class GTTSService:
    """Wrapper for gTTS"""
    
    def text_to_speech(self, text, output_path, language='en'):
        from gtts import gTTS
        tts = gTTS(text=text, lang=language, slow=False)
        tts.save(output_path)
        return output_path
