"""Plain-language explanations for platform errors, shown on the Bots page next to the failure."""
from __future__ import annotations

# (platform, code) -> (what happened, what to do)
_EXPLANATIONS: dict[tuple[str, str], tuple[str, str]] = {
    ("whatsapp", "131047"): (
        "This customer last wrote more than 24 hours ago, so WhatsApp only allows an approved template message.",
        "Wait for the customer to message again, or contact them another way.",
    ),
    ("whatsapp", "131026"): (
        "WhatsApp couldn't deliver the message to this number.",
        "The number may not use WhatsApp, may have blocked the business, or uses an outdated app.",
    ),
    ("whatsapp", "131030"): (
        "This number isn't on your test number's allowed recipients list.",
        "In Meta's WhatsApp > API Setup page, add the number under 'To', or switch to your real business number.",
    ),
    ("whatsapp", "190"): (
        "The access token has expired or was revoked.",
        "Create a permanent System User token in Meta Business Settings and paste it in this bot's settings.",
    ),
    ("whatsapp", "10"): (
        "The access token doesn't have permission for this phone number.",
        "Give the System User access to the WhatsApp account and include whatsapp_business_messaging.",
    ),
    ("whatsapp", "200"): (
        "The access token doesn't have permission for this phone number.",
        "Give the System User access to the WhatsApp account and include whatsapp_business_messaging.",
    ),
    ("whatsapp", "100"): (
        "WhatsApp rejected the request as invalid (often a wrong phone number ID).",
        "Check the phone number ID in this bot's settings matches Meta's API Setup page.",
    ),
    ("whatsapp", "133010"): (
        "The phone number isn't registered with the WhatsApp Cloud API yet.",
        "Finish registering the number in Meta's WhatsApp Manager.",
    ),
    ("whatsapp", "131031"): (
        "Meta has locked or restricted this WhatsApp Business account.",
        "Check WhatsApp Manager for a policy notice.",
    ),
    ("whatsapp", "368"): (
        "Meta temporarily blocked this account for a policy violation.",
        "Check WhatsApp Manager for details; sending resumes when the block ends.",
    ),
    ("whatsapp", "130429"): (
        "WhatsApp's sending rate limit was reached.",
        "Messages will go through again shortly.",
    ),
    ("whatsapp", "131056"): (
        "Too many messages were sent to this person in a short time.",
        "Wait a little before replying again.",
    ),
    ("whatsapp", "131051"): (
        "This message type isn't supported yet.",
        "The bot handles text messages and button replies.",
    ),
    ("telegram", "401"): (
        "Telegram rejected the bot token.",
        "Get a new token from @BotFather (/token) and paste it in this bot's settings.",
    ),
    ("telegram", "403"): (
        "This person blocked the bot or deleted the chat.",
        "Nothing to do; the bot can answer again if they restart the chat.",
    ),
    ("telegram", "429"): (
        "Telegram's rate limit was reached.",
        "Messages will go through again shortly.",
    ),
}

# Our own codes for problems that aren't platform errors.
_OWN: dict[str, tuple[str, str]] = {
    "ai_key": (
        "The AI provider rejected the key, or no AI provider is set up for the person this bot runs as.",
        "Open Settings > AI provider for that person and check the key.",
    ),
    "daily_cap": (
        "The bot reached its daily message limit, so it stopped replying for today.",
        "Raise the limit in this bot's settings if this was expected traffic.",
    ),
    "rate_limited": (
        "This person sent many messages in a short time, so the bot paused replying to them briefly.",
        "Nothing to do unless this keeps happening.",
    ),
    "not_linked": (
        "Someone who isn't linked to a team member messaged this team bot.",
        "Team members link their account from the Bots page. Use a customer bot for the public.",
    ),
    "agent_error": (
        "The assistant failed while working on this message.",
        "Open the details to see the step that failed; try again or check the connected integration.",
    ),
}


def explain(platform: str, code: str | None) -> dict | None:
    if not code:
        return None
    found = _OWN.get(code) or _EXPLANATIONS.get((platform, str(code)))
    if not found:
        return None
    return {"what": found[0], "fix": found[1]}
