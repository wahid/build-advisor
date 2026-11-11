from django.contrib import admin

from .models import Chunk, Document, Source


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("page_title", "wiki", "revision_id", "fetched_at")
    search_fields = ("page_title", "url")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "doc_type", "patch", "updated_at")
    list_filter = ("doc_type", "patch")
    search_fields = ("title", "raw_text")
    readonly_fields = ("content_hash", "created_at", "updated_at")


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("__str__", "doc_type", "patch", "embedding_model", "embedded_at")
    list_filter = ("doc_type", "patch", "embedding_model")
    search_fields = ("text", "document__title")
    raw_id_fields = ("document",)
    exclude = ("embedding",)
    readonly_fields = ("text_hash", "embedded_at")
