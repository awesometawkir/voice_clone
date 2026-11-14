from django.db import models


class VoiceSample(models.Model):
    """A voice you own: the original recording plus a cleaned reference clip."""
    name = models.CharField(max_length=200)
    audio_file = models.FileField(upload_to='uploads/voice_samples/')
    reference_file = models.FileField(upload_to='voices/', blank=True)
    transcript = models.TextField(blank=True)
    language = models.CharField(max_length=10, default='en')
    quality = models.JSONField(default=dict, blank=True)
    consent = models.BooleanField(default=False)  # "this is my voice / I have permission"
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return self.name


class Project(models.Model):
    """One narration: a script rendered segment by segment in a voice."""
    STATUS = [(s, s) for s in ('draft', 'queued', 'rendering', 'done', 'error')]

    title = models.CharField(max_length=200)
    script = models.TextField(blank=True)
    voice = models.ForeignKey(VoiceSample, null=True, blank=True, on_delete=models.SET_NULL)
    engine = models.CharField(max_length=40, default='chatterbox')
    stock_voice = models.CharField(max_length=80, blank=True)  # for engines without cloning
    language = models.CharField(max_length=10, default='en')
    settings = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='draft')
    output_wav = models.CharField(max_length=300, blank=True)
    output_mp3 = models.CharField(max_length=300, blank=True)
    srt = models.TextField(blank=True)
    vtt = models.TextField(blank=True)
    stats = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.title


class Segment(models.Model):
    """A sentence-sized piece of a project with its own take."""
    project = models.ForeignKey(Project, related_name='segments', on_delete=models.CASCADE)
    index = models.IntegerField()
    text = models.TextField()          # as written (shown in captions)
    spoken = models.TextField()        # normalised text sent to the model
    pause_ms = models.IntegerField(default=280)
    audio = models.CharField(max_length=300, blank=True)
    duration = models.FloatField(default=0)
    status = models.CharField(max_length=20, default='pending')  # pending|done|flagged|error
    score = models.FloatField(null=True, blank=True)  # 0..1 match between script and what was said
    heard = models.TextField(blank=True)
    attempts = models.IntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ['index']


class Job(models.Model):
    """Background work. One job runs at a time so the GPU is never shared."""
    kind = models.CharField(max_length=40)
    status = models.CharField(max_length=20, default='queued')  # queued|running|done|error|cancelled
    progress = models.FloatField(default=0)
    message = models.CharField(max_length=300, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']


class Transcript(models.Model):
    """Speech-to-text result for any audio or video file."""
    title = models.CharField(max_length=200)
    source = models.CharField(max_length=300)
    language = models.CharField(max_length=10, blank=True)
    text = models.TextField(blank=True)
    srt = models.TextField(blank=True)
    vtt = models.TextField(blank=True)
    duration = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Pronunciation(models.Model):
    """Say `written` as `spoken` (names, acronyms, brand words)."""
    written = models.CharField(max_length=100, unique=True)
    spoken = models.CharField(max_length=200)

    class Meta:
        ordering = ['written']


class Setting(models.Model):
    key = models.CharField(max_length=60, primary_key=True)
    value = models.JSONField(default=dict)

    @classmethod
    def get(cls, key, default=None):
        row = cls.objects.filter(pk=key).first()
        return row.value if row else default

    @classmethod
    def put(cls, key, value):
        cls.objects.update_or_create(pk=key, defaults={'value': value})
