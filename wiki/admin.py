from django.contrib import admin

from .models import Document, Source


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
