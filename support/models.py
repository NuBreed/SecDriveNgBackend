from django.db import models


class HelpArticle(models.Model):
    """A single FAQ / help article shown in the SecDrive app."""

    CATEGORY_CHOICES = [
        ('getting_started', 'Getting Started'),
        ('rides',           'Rides & Safety'),
        ('contacts',        'Trusted Contacts'),
        ('account',         'Account & Profile'),
        ('technical',       'Technical Issues'),
        ('other',           'Other'),
    ]

    question   = models.CharField(max_length=300)
    answer     = models.TextField()
    category   = models.CharField(
        max_length=30, choices=CATEGORY_CHOICES, default='other')
    order      = models.PositiveSmallIntegerField(default=0,
        help_text='Lower numbers appear first within a category.')
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'order', 'created_at']

    def __str__(self):
        return self.question[:80]
