from celery import shared_task

from accounts.services.sms import send_sms


@shared_task
def send_sms_task(to, message):
    result = send_sms(to, message)
    return {'success': result.success, 'detail': result.detail}
