import uuid

from django.db import models


class DailyUsage(models.Model):
    """Questions answered per day (UTC), for the site-wide daily limit."""

    date = models.DateField(primary_key=True)
    questions = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-date"]
        verbose_name_plural = "daily usage"

    def __str__(self) -> str:
        return f"{self.date}: {self.questions} questions"


class QuestionLog(models.Model):
    """One answered question: what was asked, what was found, what it cost, and
    how it was rated. The admin uses it for traces, costs and feedback."""

    class Rating(models.IntegerChoices):
        UP = 1, "Helpful"
        DOWN = -1, "Not helpful"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    question = models.TextField()
    history_turns = models.PositiveSmallIntegerField(default=0)
    history = models.JSONField(default=list, blank=True, help_text="Earlier turns (cut short).")
    build = models.CharField(max_length=300, blank=True, help_text="Attached build (cut short).")
    doc_types = models.JSONField(default=list, blank=True)
    model = models.CharField(max_length=100, blank=True)

    search_terms = models.CharField(max_length=300, blank=True)
    sources = models.JSONField(default=list, blank=True)
    tools = models.JSONField(default=list, blank=True, help_text="name, ok, ms, error")
    answer = models.TextField(blank=True)
    cited = models.JSONField(default=list, blank=True)
    numbers_checked = models.PositiveSmallIntegerField(
        default=0, help_text="Numbers in the answer looked up in the evidence."
    )
    numbers_unsupported = models.JSONField(
        default=list, blank=True, help_text="Numbers found in no source or tool result."
    )
    error = models.TextField(blank=True)
    completed = models.BooleanField(default=False, help_text="False: stopped or disconnected.")

    search_ms = models.PositiveIntegerField(null=True, blank=True)
    first_token_ms = models.PositiveIntegerField(null=True, blank=True)
    total_ms = models.PositiveIntegerField(null=True, blank=True)
    llm_calls = models.PositiveSmallIntegerField(default=0)
    prompt_tokens = models.PositiveIntegerField(default=0)
    cached_prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    web_searches = models.PositiveSmallIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    rating = models.SmallIntegerField(choices=Rating.choices, null=True, blank=True, db_index=True)
    feedback = models.TextField(blank=True)
    rated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.question[:80]


class GemRanking(models.Model):
    """A skill-gem ranking on the reference character, cached: the same arguments
    on the same Path of Building version always give the same numbers."""

    key = models.CharField(max_length=64, primary_key=True)
    arguments = models.JSONField()
    result = models.JSONField()
    pob_version = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.arguments} ({self.pob_version})"
