from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'voice-samples', views.VoiceSampleViewSet)
router.register(r'voice-clones', views.VoiceCloneViewSet)
router.register(r'speech-to-text', views.SpeechToTextViewSet)

urlpatterns = [
    path('', views.home, name='home'),
    path('api/', include(router.urls)),
    path('api/available-voices/', views.get_available_voices, name='available-voices'),
]
