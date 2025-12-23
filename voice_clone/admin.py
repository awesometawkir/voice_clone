from django.contrib import admin
from .models import VoiceSample, VoiceClone, SpeechToText


@admin.register(VoiceSample)
class VoiceSampleAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at', 'user']
    list_filter = ['created_at']
    search_fields = ['name']


@admin.register(VoiceClone)
class VoiceCloneAdmin(admin.ModelAdmin):
    list_display = ['service_used', 'created_at', 'user']
    list_filter = ['service_used', 'created_at']
    search_fields = ['text_input']


@admin.register(SpeechToText)
class SpeechToTextAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'user']
    list_filter = ['created_at']
    search_fields = ['transcribed_text']
