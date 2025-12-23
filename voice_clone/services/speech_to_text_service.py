import os
import tempfile


class SpeechToTextService:
    """Service for converting speech to text"""

    def __init__(self):
        self.recognizer = None

    def initialize_recognizer(self):
        """Initialize speech recognizer (lazy loading)"""
        if self.recognizer is None:
            try:
                import speech_recognition as sr
                self.recognizer = sr.Recognizer()
            except ImportError:
                raise Exception("SpeechRecognition not installed. Install with: pip install SpeechRecognition")

    def convert_to_wav(self, audio_file_path):
        """
        Convert audio file to WAV format if needed
        """
        file_extension = os.path.splitext(audio_file_path)[1].lower()

        if file_extension == '.wav':
            return audio_file_path

        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(audio_file_path)
            wav_path = tempfile.mktemp(suffix='.wav')
            audio.export(wav_path, format='wav')
            return wav_path
        except ImportError:
            raise Exception("pydub not installed. Install with: pip install pydub")
        except Exception as e:
            raise Exception(f"Audio conversion error: {str(e)}")

    def transcribe_audio(self, audio_file_path, language='en-US'):
        """
        Transcribe audio file to text using Google Speech Recognition (free)
        """
        self.initialize_recognizer()
        import speech_recognition as sr

        wav_path = self.convert_to_wav(audio_file_path)

        try:
            with sr.AudioFile(wav_path) as source:
                audio_data = self.recognizer.record(source)
                text = self.recognizer.recognize_google(audio_data, language=language)
                return text
        except sr.UnknownValueError:
            raise Exception("Speech recognition could not understand the audio")
        except sr.RequestError as e:
            raise Exception(f"Could not request results from speech recognition service: {str(e)}")
        except Exception as e:
            raise Exception(f"Transcription error: {str(e)}")
        finally:
            # Clean up temporary WAV file if created
            if wav_path != audio_file_path and os.path.exists(wav_path):
                os.remove(wav_path)

    def transcribe_audio_sphinx(self, audio_file_path):
        """
        Transcribe using offline Sphinx (alternative, fully offline)
        Requires: pip install pocketsphinx
        """
        self.initialize_recognizer()
        import speech_recognition as sr

        wav_path = self.convert_to_wav(audio_file_path)

        try:
            with sr.AudioFile(wav_path) as source:
                audio_data = self.recognizer.record(source)
                text = self.recognizer.recognize_sphinx(audio_data)
                return text
        except Exception as e:
            raise Exception(f"Sphinx transcription error: {str(e)}")
        finally:
            if wav_path != audio_file_path and os.path.exists(wav_path):
                os.remove(wav_path)


class WhisperSTTService:
    """Advanced speech-to-text using OpenAI Whisper (better quality)"""

    def __init__(self):
        self.model = None

    def load_model(self, model_size='base'):
        """
        Load Whisper model
        Sizes: tiny, base, small, medium, large
        """
        try:
            import whisper
            self.model = whisper.load_model(model_size)
        except ImportError:
            raise Exception("Whisper not installed. Install with: pip install openai-whisper")
        except Exception as e:
            raise Exception(f"Failed to load Whisper model: {str(e)}")

    def transcribe_audio(self, audio_file_path, language=None):
        """
        Transcribe audio using Whisper
        More accurate than Google Speech Recognition
        """
        if self.model is None:
            self.load_model()

        try:
            result = self.model.transcribe(audio_file_path, language=language)
            return result['text']
        except Exception as e:
            raise Exception(f"Whisper transcription error: {str(e)}")

    def transcribe_with_timestamps(self, audio_file_path):
        """
        Transcribe with word-level timestamps
        """
        if self.model is None:
            self.load_model()

        try:
            result = self.model.transcribe(audio_file_path, word_timestamps=True)
            return {
                'text': result['text'],
                'segments': result['segments']
            }
        except Exception as e:
            raise Exception(f"Whisper transcription error: {str(e)}")
