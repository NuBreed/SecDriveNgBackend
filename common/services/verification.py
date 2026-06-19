"""Shared helpers for verification-request flows (documents + review audit)."""
from django.contrib.contenttypes.models import ContentType

from common.models import VerificationDocument


def attach_document(request_obj, owner, doc_type, file, document_number='', expiry_date=None):
    ct = ContentType.objects.get_for_model(request_obj)
    return VerificationDocument.objects.create(
        owner=owner,
        content_type=ct,
        object_id=str(request_obj.pk),
        doc_type=doc_type,
        file=file,
        document_number=document_number or '',
        expiry_date=expiry_date,
    )


def documents_for(request_obj):
    ct = ContentType.objects.get_for_model(request_obj)
    return VerificationDocument.objects.filter(content_type=ct, object_id=str(request_obj.pk))


def clear_documents(request_obj):
    documents_for(request_obj).delete()


def log_review(request_obj, actor, action, reason=''):
    # Imported lazily to avoid a hard dependency cycle with the kyc app.
    from kyc.models import ReviewEvent
    ct = ContentType.objects.get_for_model(request_obj)
    return ReviewEvent.objects.create(
        actor=actor, content_type=ct, object_id=str(request_obj.pk),
        action=action, reason=reason,
    )
