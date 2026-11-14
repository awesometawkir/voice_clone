from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('api/status/', views.status),
    path('api/voices/', views.voices),
    path('api/voices/<int:pk>/', views.voice_detail),
    path('api/projects/', views.projects),
    path('api/projects/<int:pk>/', views.project_detail),
    path('api/projects/<int:pk>/render/', views.project_render),
    path('api/projects/<int:pk>/captions.<str:fmt>', views.captions),
    path('api/segments/<int:pk>/', views.segment_action),
    path('api/jobs/<int:pk>/', views.job_detail),
    path('api/transcripts/', views.transcripts),
    path('api/transcripts/<int:pk>/', views.transcript_detail),
    path('api/clean/', views.clean),
    path('api/ai/', views.ai),
    path('api/settings/', views.settings_view),
    path('api/pronunciations/', views.pronunciations),
    path('api/pronunciations/<int:pk>/', views.pronunciation_detail),
]
