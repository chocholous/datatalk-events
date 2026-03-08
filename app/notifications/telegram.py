import json
import logging
import random

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.models import Event

SARCASTIC_INTROS = [
    # Klasická šťáva
    "Zase někdo organizuje meetup, jako by nestačilo dost utrpení na světě.",
    "Další příležitost předstírat, že rozumíte tomu, o čem se mluví.",
    "Protože Netflix se nedívá sám od sebe... aha, vlastně jo. Tak pojďte radši sem.",
    "Vaše pohovka bude smutná, ale váš LinkedIn profil nadšený.",
    "Připomínáme akci, které se určitě zúčastníte a ne jen lajknete.",
    "Sociální interakce s lidmi, kteří taky googlí error messages. Co víc chtít.",
    "Za 2 hodiny začíná event. Ještě máte čas vymyslet výmluvu, proč nepřijdete.",
    "Další šance potkat lidi, co si myslí, že AI nahradí jejich práci. Plot twist: možná jo.",
    # České filmy a legendy
    "Kdo chvíli stál, už stojí opodál. Tak nepostávejte a pojďte na meetup.",
    "Nechte to být, řekl Jansen. Ale vy to nenecháte, protože jste vývojáři.",
    "Trhni si nohou, řekla pohovka. A máme tu event.",
    "Mazej do meetupu, nebo tě Hujer přetáhne nudlí.",
    "Říkali, že to bude sranda. Říkali taky, že Python je jednoduchý.",
    "Dneska vám nedám napít, ale dám vám přednášku. To je horší.",
    "Kdo šetří, má za tři. Kdo chodí na meetupy, má za... no, aspoň network.",
    "A von si myslí, že vemu rohožku! A vy si myslíte, že nepřijdete.",
    "Neber to osobně, ale tvůj kód by potřeboval víc meetupů.",
    "Marečku, podejte mi ten deployment. A pojďte na event.",
    "To je pořádnej bigbít! řekl by Kodet. A to ještě neviděl naši agendu.",
    "Černí baroni by se divili, co všechno se dá automatizovat.",
    "Pelíšky jsou teplý, ale meetup je teplejší. Hlavně ta diskuze.",
    "Já su z Brna, pane. A i tam chodíme na meetupy.",
    "Jáchyme, hoď ho do stroje! Ale nejdřív pojď na přednášku.",
    "Kdo neskáče, není Čech. Kdo nechodí na meetupy, není dev.",
    "Vesničko má středisková, i ty máš internet a můžeš se připojit.",
    "Dobrý den, Koňáku. Dneska máme event, ne výslech.",
    "Smrt mu sluší, ale meetup mu sluší víc.",
    "S čerty nejsou žerty. S deploymenty taky ne. Pojďte se poradit.",
    # Pop kultura a memy
    "One does not simply walk into a meetup. Ale dneska to zkuste.",
    "I used to be a developer like you, then I took a meetup to the knee.",
    "This is fine. Všechno hoří, ale meetup bude.",
    "It's not a bug, it's a feature. A tenhle event taky.",
    "Sudo make me go to this meetup.",
    "First rule of meetup club: mluvte o meetup clubu. Fakt. Potřebujeme lidi.",
    "I'm not saying it's aliens, but... kdo jiný by organizoval tyhle eventy?",
    "Perfectly balanced, as all things should be. Kromě vašeho work-life balance.",
    "I am Groot. I am also going to this meetup.",
    "Winter is coming. Ale dřív přijde tenhle event.",
    "You shall not pass... kolem tohohle eventu bez registrace.",
    "It's a trap! Ale s dobrými přednáškami a občerstvením.",
    "Luke, I am your meetup organizer.",
    "Houston, we have a meetup.",
    "In case of fire: git commit, git push, go to meetup.",
    "Za chvíli to začne. Resistance is futile.",
    "May the source be with you. A taky ten meetup.",
    "I'll be back. A vy taky, na dalším meetupu.",
    "Hasta la vista, baby. Ale nejdřív ten event.",
    "To infinity and beyond! Ale nejdřív zastávka: meetup.",
    # IT humor a self-deprecation
    "Konečně šance mluvit s lidmi, co taky nevychází z domu.",
    "Opusťte svůj terminal a přijďte mezi lidi. Bude to bolet, ale krátce.",
    "Meetup: místo, kde se Stack Overflow materializuje v reálném světě.",
    "Přijďte, bude to lepší než code review v pondělí ráno.",
    "Jestli vás baví číst dokumentaci, tohle je live verze.",
    "Přednáška je vlastně jen Stack Overflow answer s mikrofonem.",
    "Vaše IDE vám tohle neřekne. Člověk na podiu možná jo.",
    "Ctrl+Z na tohle nejde. Registrace je závazná. Asi. Možná.",
    "Kdo dneska nepřijde, tomu se zítra rozbije prod.",
    "git commit -m 'finally going outside'",
    "Přijďte networking, odejdete s pěti recruiter requesty na LinkedIn.",
    "Je to zadarmo. Jako Linux. A víme, jak to s Linuxem dopadlo. Skvěle.",
    "Alternativa k mass-scrollování Twitteru. Možná horší, možná lepší.",
    "Dnes se naučíte něco nového. Nebo aspoň dostanete pivo.",
    "Váš rubber duck si zaslouží pauzu. Pojďte debugovat s lidmi.",
    "Meetup: protože mass-DM na Slacku by byl creepy.",
    "README.md říká, že máte přijít. A README se neporušuje.",
    "Přijďte. Nebo nepřijďte. Ale pak si nestěžujte, že jste se to dozvěděli z blogpostu.",
    "Dnešní agenda má víc bodů než váš backlog. A možná se i splní.",
]

PHOTO_CAPTION_LIMIT = 1024

log = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramNotifier:
    def _bot_url(self, method: str) -> str:
        settings = get_settings()
        return f"{TELEGRAM_API_BASE}/bot{settings.telegram_bot_token}/{method}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def send_to_channel(self, text: str, photo_url: str | None = None) -> bool:
        settings = get_settings()
        if not settings.telegram_bot_token or not settings.telegram_channel_id:
            log.warning("Telegram bot token or channel ID not set, skipping")
            return False
        async with httpx.AsyncClient() as client:
            if photo_url:
                await client.post(
                    self._bot_url("sendPhoto"),
                    json={
                        "chat_id": settings.telegram_channel_id,
                        "photo": photo_url,
                    },
                )
            resp = await client.post(
                self._bot_url("sendMessage"),
                json={
                    "chat_id": settings.telegram_channel_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
            return resp.status_code == 200


def _format_agenda_item(item: dict) -> str:
    line = ""
    if item.get("time"):
        line += f"{item['time']}  "
    line += item.get("title", "")
    speaker = item.get("speaker")
    speakers = item.get("speakers")
    if speaker:
        line += f" – {speaker}"
    elif speakers:
        line += f" – {', '.join(speakers)}"
    return line


def format_event_reminder(events: list[Event], max_len: int = 0) -> str:
    intro = f"_{random.choice(SARCASTIC_INTROS)}_"
    parts = [intro]
    for e in events:
        lines = [f"*{e.title}*"]
        if e.date:
            lines.append(f"🕐 {e.date.strftime('%H:%M')}")
        if e.location:
            lines.append(f"📍 {e.location}")
        agenda = json.loads(e.agenda) if e.agenda else []
        speakers_list = json.loads(e.speakers) if e.speakers else []
        if agenda:
            agenda_lines = [_format_agenda_item(item) for item in agenda]
            lines.append("📋 Program:\n" + "\n".join(f"  • {l}" for l in agenda_lines))
        elif speakers_list:
            lines.append(f"🎤 {', '.join(speakers_list)}")
        if e.organizer:
            lines.append(f"🏢 {e.organizer}")
        topics = json.loads(e.topics) if e.topics else []
        if topics:
            lines.append(f"🏷️ {', '.join(topics)}")
        if e.description:
            lines.append(f"\n{e.description}")
        lines.append(f"\n[👉 Více info]({e.url})")
        parts.append("\n".join(lines))
    text = "\n\n".join(parts)
    if max_len and len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text
