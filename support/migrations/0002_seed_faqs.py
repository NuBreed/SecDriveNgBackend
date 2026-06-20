from django.db import migrations

FAQS = [
    # Getting Started
    ('getting_started', 0, 'How do I scan a driver\'s QR code?',
     'Open SecDrive and tap "Scan Driver QR Code" on the home screen. Point your camera at the QR code on the driver\'s ID card or app. The driver\'s verified details will appear instantly.'),
    ('getting_started', 1, 'What happens when I start a ride?',
     'Your location is shared with your trusted contacts every 10 seconds for the duration of your ride. If you trigger SOS, the nearest responders are also notified automatically.'),
    ('getting_started', 2, 'What if the driver is not verified?',
     'Do not enter the vehicle. You can still scan the code to log the attempt, and report the driver directly through the app. Your safety comes first.'),

    # Rides & Safety
    ('rides', 0, 'How does SOS work?',
     'Tap the red SOS button from the dashboard or during a live ride. This immediately alerts all your trusted contacts with your location. Stay calm and move to a safe place if possible.'),
    ('rides', 1, 'Can I share my ride with someone not on the app?',
     'Yes. Your trusted contacts receive real-time SMS or WhatsApp location updates — they do not need the SecDrive app installed to follow your ride.'),
    ('rides', 2, 'What is route safety check?',
     'Before you travel, enter your destination in Route Safety to get a safety score for that route. The app checks live incident data, threat zones, and alerts along the way and may suggest safer alternatives.'),

    # Trusted Contacts
    ('contacts', 0, 'How do I add trusted contacts?',
     'Go to Profile → Trusted Contacts and tap "Add Contact". You can add family, friends, or emergency contacts. They will be notified whenever you start a ride or trigger SOS.'),
    ('contacts', 1, 'Can I import my iSafePass family as trusted contacts?',
     'Yes. On the Trusted Contacts screen tap the shield icon in the top bar, select the family members you want to import, and tap Import. Contacts already in your list are automatically excluded.'),
    ('contacts', 2, 'How many trusted contacts can I add?',
     'There is no hard limit. However, we recommend keeping your list focused — 3 to 5 contacts ensures faster, more personal alerts.'),

    # Account & Profile
    ('account', 0, 'How do I link my iSafePass account?',
     'Go to Profile → Security and tap "Link iSafePass Account". Enter your iSafePass login credentials. Once linked, your family contacts and safety profile are available in SecDrive.'),
    ('account', 1, 'How do I become a verified driver?',
     'Go to Profile → Driver Verification and submit your driving licence, national ID, and a passport photo. Our team reviews submissions within 24–48 hours.'),
    ('account', 2, 'How do I change my phone number or email?',
     'Go to Profile → Edit Profile to update your contact details. Phone number changes require OTP verification on the new number.'),

    # Technical Issues
    ('technical', 0, 'My location is not updating during a ride. What should I do?',
     'Ensure location permissions are set to "Always Allow". On Android go to Settings → Apps → SecDrive → Permissions → Location → Allow all the time. Also check that Battery Optimisation is off for SecDrive.'),
    ('technical', 1, 'The app says I am offline. What can I do?',
     'SecDrive works best with mobile data. If you lose connection, SOS messages are stored and forwarded once you are back online. Check your data connection or switch to Wi-Fi.'),
    ('technical', 2, 'How do I report a bug or problem?',
     'Go to Profile → Help & Support and tap "Contact Support", or email support@secdrive.ng. Please include a description of the issue and your device model so we can help you quickly.'),
]


def seed(apps, schema_editor):
    HelpArticle = apps.get_model('support', 'HelpArticle')
    for (category, order, question, answer) in FAQS:
        HelpArticle.objects.get_or_create(
            question=question,
            defaults={
                'answer':    answer,
                'category':  category,
                'order':     order,
                'is_active': True,
            },
        )


def unseed(apps, schema_editor):
    apps.get_model('support', 'HelpArticle').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('support', '0001_initial'),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
