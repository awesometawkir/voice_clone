from django.db import models
from django.contrib.auth.models import User


class VoiceSample(models.Model):
    """Model to store voice samples for cloning"""
    name = models.CharField(max_length=200)
    audio_file = models.FileField(upload_to='uploads/voice_samples/')
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return self.name


class VoiceClone(models.Model):
    """Model to store generated voice clones"""
    SERVICE_CHOICES = [
        ('free', 'Free TTS'),
        ('openrouter', 'OpenRouter API'),
        ('openai', 'OpenAI API'),
    ]

    text_input = models.TextField()
    output_file = models.FileField(upload_to='outputs/voice_clones/')
    service_used = models.CharField(max_length=20, choices=SERVICE_CHOICES)
    voice_sample = models.ForeignKey(VoiceSample, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"Clone - {self.service_used} - {self.created_at}"


class SpeechToText(models.Model):
    """Model to store speech-to-text conversions"""
    audio_file = models.FileField(upload_to='uploads/speech_to_text/')
    transcribed_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"STT - {self.created_at}"
