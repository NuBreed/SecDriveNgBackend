"""Pluggable identity-verification providers.

The default ``NoOpProvider`` requires manual admin review. An external NIN or
face-match service can be wired later by pointing ``settings.KYC_IDENTITY_PROVIDER``
at a subclass.
"""
import abc

from django.conf import settings
from django.utils.module_loading import import_string


class ProviderResult:
    def __init__(self, verified, requires_manual_review=True, detail='', raw=None):
        self.verified = verified
        self.requires_manual_review = requires_manual_review
        self.detail = detail
        self.raw = raw or {}


class IdentityProvider(abc.ABC):
    @abc.abstractmethod
    def verify_document(self, doc_type, document_number, file=None):
        raise NotImplementedError

    @abc.abstractmethod
    def match_selfie(self, selfie_file, id_document_file):
        raise NotImplementedError


class NoOpProvider(IdentityProvider):
    """No external check — everything routes to manual admin review."""

    def verify_document(self, doc_type, document_number, file=None):
        return ProviderResult(verified=False, requires_manual_review=True,
                              detail='Manual review required.')

    def match_selfie(self, selfie_file, id_document_file):
        return ProviderResult(verified=False, requires_manual_review=True,
                              detail='Manual review required.')


def get_provider():
    return import_string(settings.KYC_IDENTITY_PROVIDER)()
