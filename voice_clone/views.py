from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
import os
import uuid

from .models import VoiceSample, VoiceClone, SpeechToText
from .serializers import VoiceSampleSerializer, VoiceCloneSerializer, SpeechToTextSerializer
from .services.openrouter_service import OpenRouterService, OpenAIService
from .services.free_tts_service import FreeTTSService, GTTSService
from .services.speech_to_text_service import SpeechToTextService, WhisperSTTService


def home(request):
    """Home page view"""
    return render(request, 'home.html')


class VoiceSampleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing voice samples"""
    queryset = VoiceSample.objects.all()
    serializer_class = VoiceSampleSerializer

    def perform_create(self, serializer):
        if self.request.user.is_authenticated:
            serializer.save(user=self.request.user)
        else:
            serializer.save()


class VoiceCloneViewSet(viewsets.ModelViewSet):
    """ViewSet for voice cloning operations"""
    queryset = VoiceClone.objects.all()
    serializer_class = VoiceCloneSerializer

    @action(detail=False, methods=['post'])
    def generate_free(self, request):
        """Generate voice clone using free TTS"""
        text = request.data.get('text')
        voice_sample_id = request.data.get('voice_sample_id')

        if not text:
            return Response(
                {'error': 'Text is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            tts_service = FreeTTSService()
            output_filename = f"clone_free_{uuid.uuid4()}.wav"
            output_path = os.path.join('media', 'outputs', 'voice_clones', output_filename)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            if voice_sample_id:
                # Voice cloning with sample
                voice_sample = VoiceSample.objects.get(id=voice_sample_id)
                speaker_wav_path = voice_sample.audio_file.path
                language = request.data.get('language', 'en')

                tts_service.text_to_speech_with_clone(
                    text=text,
                    speaker_wav_path=speaker_wav_path,
                    output_path=output_path,
                    language=language
                )
            else:
                # Simple TTS without cloning (Edge TTS)
                voice_id = request.data.get('voice_id', 'female_en')
                tts_service.text_to_speech_simple(text, output_path, voice_id=voice_id)

            # Save to database
            voice_clone = VoiceClone.objects.create(
                text_input=text,
                service_used='free',
                voice_sample_id=voice_sample_id,
                user=request.user if request.user.is_authenticated else None
            )
            voice_clone.output_file.name = f'outputs/voice_clones/{output_filename}'
            voice_clone.save()

            serializer = self.get_serializer(voice_clone)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def generate_openrouter(self, request):
        """Generate voice clone using OpenRouter API"""
        text = request.data.get('text')
        voice_id = request.data.get('voice_id', 'alloy')
        model = request.data.get('model')  # Custom model from user input
        api_key = request.data.get('api_key')  # API key from user input

        if not text:
            return Response(
                {'error': 'Text is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not api_key:
            return Response(
                {'error': 'API key is required. Please enter your OpenRouter API key.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Use custom API key if provided
            service = OpenRouterService()
            service.api_key = api_key  # Override with user-provided key
            audio_content = service.text_to_speech(text, voice_id, model=model)

            # Save audio file
            output_filename = f"clone_openrouter_{uuid.uuid4()}.mp3"
            output_path = f'outputs/voice_clones/{output_filename}'

            # Save file
            file_path = default_storage.save(output_path, ContentFile(audio_content))

            # Save to database
            voice_clone = VoiceClone.objects.create(
                text_input=text,
                service_used='openrouter',
                user=request.user if request.user.is_authenticated else None
            )
            voice_clone.output_file.name = file_path
            voice_clone.save()

            serializer = self.get_serializer(voice_clone)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def generate_openai(self, request):
        """Generate voice clone using OpenAI API"""
        text = request.data.get('text')
        voice_id = request.data.get('voice_id', 'alloy')
        model = request.data.get('model', 'tts-1')
        api_key = request.data.get('api_key')  # API key from user input

        if not text:
            return Response(
                {'error': 'Text is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not api_key:
            return Response(
                {'error': 'API key is required. Please enter your OpenAI API key.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Use custom API key if provided
            service = OpenAIService()
            service.api_key = api_key  # Override with user-provided key
            audio_content = service.text_to_speech(text, voice_id, model)

            # Save audio file
            output_filename = f"clone_openai_{uuid.uuid4()}.mp3"
            output_path = f'outputs/voice_clones/{output_filename}'

            # Save file
            file_path = default_storage.save(output_path, ContentFile(audio_content))

            # Save to database
            voice_clone = VoiceClone.objects.create(
                text_input=text,
                service_used='openai',
                user=request.user if request.user.is_authenticated else None
            )
            voice_clone.output_file.name = file_path
            voice_clone.save()

            serializer = self.get_serializer(voice_clone)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SpeechToTextViewSet(viewsets.ModelViewSet):
    """ViewSet for speech-to-text operations"""
    queryset = SpeechToText.objects.all()
    serializer_class = SpeechToTextSerializer

    def create(self, request, *args, **kwargs):
        """Convert speech to text"""
        audio_file = request.FILES.get('audio_file')
        language = request.data.get('language', 'en-US')
        use_whisper = request.data.get('use_whisper', False)

        if not audio_file:
            return Response(
                {'error': 'Audio file is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Save the uploaded file temporarily
            temp_path = default_storage.save(
                f'uploads/speech_to_text/{audio_file.name}',
                ContentFile(audio_file.read())
            )
            full_path = default_storage.path(temp_path)

            # Transcribe
            if use_whisper:
                service = WhisperSTTService()
                transcribed_text = service.transcribe_audio(full_path)
            else:
                service = SpeechToTextService()
                transcribed_text = service.transcribe_audio(full_path, language)

            # Save to database
            speech_to_text = SpeechToText.objects.create(
                transcribed_text=transcribed_text,
                user=request.user if request.user.is_authenticated else None
            )
            speech_to_text.audio_file.name = temp_path
            speech_to_text.save()

            serializer = self.get_serializer(speech_to_text)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['GET'])
def get_available_voices(request):
    """Get list of available voices for different services"""
    return Response({
        'openrouter': OpenRouterService().get_available_voices(),
        'openai': OpenAIService().get_available_voices(),
        'free_tts_languages': FreeTTSService().get_supported_languages()
    })
