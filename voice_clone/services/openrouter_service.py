import requests
import os
from django.conf import settings
import json


class OpenRouterService:
    """Service for OpenRouter API integration"""

    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self.model = settings.OPENROUTER_MODEL
        self.base_url = "https://openrouter.ai/api/v1"

    def text_to_speech(self, text, voice_id="alloy", model=None):
        """
        Generate speech from text using OpenRouter API
        Note: OpenRouter routes to various TTS models

        Args:
            text: Text to convert to speech
            voice_id: Voice to use (for OpenAI models)
            model: OpenRouter model name (e.g., 'openai/tts-1', 'openai/tts-1-hd')
                   If not provided, uses default from settings
        """
        if not self.api_key:
            raise ValueError("OpenRouter API key not configured - add OPENROUTER_API_KEY to .env file")

        # Use custom model if provided, otherwise use default from settings
        model_to_use = model if model else self.model

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # OpenRouter supports routing to various TTS models
        url = f"{self.base_url}/audio/speech"

        payload = {
            "model": model_to_use,
            "input": text,
            "voice": voice_id,
        }

        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.content
        except requests.exceptions.RequestException as e:
            raise Exception(f"OpenRouter API error: {str(e)}")

    def get_available_voices(self):
        """Return available voice options"""
        return [
            "alloy",
            "echo",
            "fable",
            "onyx",
            "nova",
            "shimmer"
        ]


class OpenAIService:
    """Direct OpenAI API service as alternative"""

    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.base_url = "https://api.openai.com/v1"

    def text_to_speech(self, text, voice_id="alloy", model="tts-1"):
        """
        Generate speech from text using OpenAI API
        Supports both standard TTS (tts-1) and new GPT-4o Audio models
        """
        if not self.api_key:
            raise ValueError("OpenAI API key not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Handle GPT-4o Audio models (Chat Completions API)
        if "gpt-4o" in model and "audio" in model:
            url = f"{self.base_url}/chat/completions"
            
            payload = {
                "model": model,
                "modalities": ["text", "audio"],
                "audio": {
                    "voice": voice_id,
                    "format": "mp3"
                },
                "messages": [
                    {
                        "role": "user",
                        "content": text
                    }
                ]
            }

            try:
                response = requests.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                # Extract base64 audio and decode
                import base64
                if "choices" in data and len(data["choices"]) > 0:
                    audio_data_b64 = data["choices"][0]["message"]["audio"]["data"]
                    return base64.b64decode(audio_data_b64)
                else:
                    raise Exception("No audio content in response")

            except requests.exceptions.RequestException as e:
                # Determine detailed error message
                error_msg = str(e)
                if e.response is not None:
                   try:
                       error_msg = f"{e} - {e.response.json()}"
                   except:
                       error_msg = f"{e} - {e.response.text}"
                raise Exception(f"OpenAI Chat API error: {error_msg}")

        # Handle Standard TTS models (Audio Speech API)
        else:
            url = f"{self.base_url}/audio/speech"

            payload = {
                "model": model,
                "input": text,
                "voice": voice_id,
            }

            try:
                response = requests.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return response.content
            except requests.exceptions.RequestException as e:
                 # Determine detailed error message
                error_msg = str(e)
                if e.response is not None:
                   try:
                       error_msg = f"{e} - {e.response.json()}"
                   except:
                       error_msg = f"{e} - {e.response.text}"
                raise Exception(f"OpenAI TTS API error: {error_msg}")

    def get_available_voices(self):
        """Return available voice options"""
        return [
            "alloy",
            "echo",
            "fable",
            "onyx",
            "nova",
            "shimmer",
            "ash",
            "coral",
            "sage"
        ]
