from django.contrib import admin
from .models import HelpArticle


@admin.register(HelpArticle)
class HelpArticleAdmin(admin.ModelAdmin):
    list_display  = ('question', 'category', 'order', 'is_active', 'updated_at')
    list_filter   = ('category', 'is_active')
    list_editable = ('order', 'is_active')
    search_fields = ('question', 'answer')
    ordering      = ('category', 'order')
