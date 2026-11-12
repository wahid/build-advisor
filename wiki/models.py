from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import models
from pgvector.django import HnswIndex, VectorField


class DocumentType(models.TextChoices):
    GEM = "gem", "Gem"
    UNIQUE = "unique", "Unique item"
    ASCENDANCY = "ascendancy", "Ascendancy"
    MECHANIC = "mechanic", "Mechanic"
    PATCH = "patch", "Patch notes"


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
    chunked_hash = models.CharField(
        max_length=64, blank=True, help_text="content_hash at the time chunks were last built."
    )
    card = models.JSONField(
        null=True, blank=True, help_text="In-game style tooltip from the page's item box."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return f"{self.title} ({self.get_doc_type_display()}, {self.patch})"


class Chunk(models.Model):
    """A section-sized piece of a document with its embedding.

    Metadata (type, patch, URL) is copied from the document so retrieval
    can filter and cite without joins.
    """

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    position = models.PositiveIntegerField(help_text="Order of the chunk within the document.")
    section = models.CharField(max_length=255, blank=True)
    text = models.TextField(help_text="Chunk text, prefixed with page title and section.")
    text_hash = models.CharField(max_length=64, db_index=True)
    doc_type = models.CharField(max_length=20, choices=DocumentType.choices, db_index=True)
    patch = models.CharField(max_length=20, db_index=True)
    url = models.URLField(max_length=500)
    embedding = VectorField(dimensions=settings.EMBEDDING_DIMENSIONS, null=True, blank=True)
    embedding_model = models.CharField(max_length=100, blank=True)
    embedded_at = models.DateTimeField(null=True, blank=True)
    # Maintained by Postgres for keyword search (exact gem and item names).
    search_vector = models.GeneratedField(
        expression=SearchVector("text", config="english"),
        output_field=SearchVectorField(),
        db_persist=True,
    )

    class Meta:
        ordering = ["document", "position"]
        constraints = [
            models.UniqueConstraint(fields=["document", "position"], name="unique_chunk_position"),
        ]
        indexes = [
            HnswIndex(
                name="chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
            GinIndex(name="chunk_search_vector_gin", fields=["search_vector"]),
        ]

    def __str__(self) -> str:
        return f"{self.document.title} #{self.position} ({self.section or 'intro'})"
