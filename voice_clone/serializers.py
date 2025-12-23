from rest_framework import serializers
from .models import VoiceSample, VoiceClone, SpeechToText


class VoiceSampleSerializer(serializers.ModelSerializer):
    class Meta:
        model = VoiceSample
        fields = ['id', 'name', 'audio_file', 'created_at']


class VoiceCloneSerializer(serializers.ModelSerializer):
    class Meta:
        model = VoiceClone
        fields = ['id', 'text_input', 'output_file', 'service_used', 'voice_sample', 'created_at']
        read_only_fields = ['output_file', 'created_at']


class SpeechToTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpeechToText
        fields = ['id', 'audio_file', 'transcribed_text', 'created_at']
        read_only_fields = ['transcribed_text', 'created_at']
