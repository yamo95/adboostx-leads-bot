from leadengine.models import Contact
from leadengine.telegram import reconcile_previews

def contact(value, purpose='contact', verification='published_not_verified'):
    c = Contact('telegram', value, 'https://publisher.example/contact', 'Contact', 'explicit_telegram', purpose)
    c.verification = verification
    return c

def test_known_channel_propagates_to_case_duplicate():
    a = contact('https://t.me/ChannelName', 'community', 'public_channel_or_group_page_observed')
    b = contact('https://t.me/channelname')
    assert reconcile_previews([a,b])[1].purpose == 'community'

def test_legal_purpose_is_preserved():
    a = contact('https://t.me/ChannelName', 'community', 'public_channel_or_group_page_observed')
    b = contact('https://t.me/channelname', 'legal_only')
    assert reconcile_previews([a,b])[1].purpose == 'legal_only'

def test_other_endpoint_is_not_changed():
    a = contact('https://t.me/ChannelName', 'community', 'public_channel_or_group_page_observed')
    b = contact('https://t.me/BusinessManager')
    assert reconcile_previews([a,b])[1].purpose == 'contact'

def test_bot_type_is_propagated():
    a = contact('https://t.me/HelperName', 'bot', 'public_bot_page_observed')
    b = contact('https://t.me/helpername')
    assert reconcile_previews([a,b])[1].purpose == 'bot'
