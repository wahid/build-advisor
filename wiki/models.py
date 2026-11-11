from django.db import models


class DocumentType(models.TextChoices):
    GEM = "gem", "Gem"
    UNIQUE = "unique", "Unique item"
    ASCENDANCY = "ascendancy", "Ascendancy"
    MECHANIC = "mechanic", "Mechanic"


class Source(models.Model):
    """A single page fetched from an external wiki."""

    wiki = models.CharField(max_length=50, default="poewiki")
    page_title = models.CharField(max_length=255)
    url = models.URLField(max_length=500, unique=True)
    page_id = models.PositiveIntegerField(null=True, blank=True)
    revision_id = models.PositiveIntegerField(null=True, blank=True)
    fetched_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["wiki", "page_title"], name="unique_wiki_page"),
        ]
        ordering = ["page_title"]

    def __str__(self) -> str:
        return f"{self.wiki}: {self.page_title}"


class Document(models.Model):
    """Plain-text content of a source page, ready for chunking."""

    source = models.OneToOneField(Source, on_delete=models.CASCADE, related_name="document")
    title = models.CharField(max_length=255)
    doc_type = models.CharField(max_length=20, choices=DocumentType.choices, db_index=True)
    raw_text = models.TextField()
    patch = models.CharField(max_length=20, help_text="Game version the text applies to.")
    content_hash = models.CharField(max_length=64, help_text="SHA-256 of raw_text.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return f"{self.title} ({self.get_doc_type_display()}, {self.patch})"
