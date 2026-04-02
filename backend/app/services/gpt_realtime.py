"""GPT Realtime API service for Premium tier voice agents."""

# ruff: noqa: RUF001 - Contains intentional non-ASCII characters for internationalization

import contextlib
import json
import types
import uuid
from typing import Any

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations import get_workspace_integrations
from app.api.settings import get_user_api_keys
from app.core.auth import user_id_to_uuid
from app.services.tools.registry import ToolRegistry

logger = structlog.get_logger()

# Language code to human-readable name mapping
LANGUAGE_NAMES: dict[str, str] = {
    "en-US": "English",
    "en-GB": "English (British)",
    "es-ES": "Spanish",
    "es-MX": "Spanish (Mexican)",
    "fr-FR": "French",
    "de-DE": "German",
    "it-IT": "Italian",
    "pt-BR": "Portuguese (Brazilian)",
    "pt-PT": "Portuguese",
    "nl-NL": "Dutch",
    "ja-JP": "Japanese",
    "ko-KR": "Korean",
    "zh-CN": "Chinese (Mandarin)",
    "zh-TW": "Chinese (Traditional)",
    "ru-RU": "Russian",
    "ar-SA": "Arabic",
    "hi-IN": "Hindi",
    "pl-PL": "Polish",
    "tr-TR": "Turkish",
    "vi-VN": "Vietnamese",
    "th-TH": "Thai",
    "id-ID": "Indonesian",
    "ms-MY": "Malay",
    "fil-PH": "Filipino",
    "sv-SE": "Swedish",
}

# Best practices translated for each supported language
BEST_PRACTICES: dict[str, str] = {
    "en": """- Keep responses to 1-2 sentences — voice is a conversation, not a lecture
- Ask one question at a time, not multiple
- If you don't know something, say so honestly
- Before calling ANY tool, ALWAYS say a brief acknowledgment out loud first (e.g., "Let me check that for you", "One moment") — the caller must hear your voice before you invoke any tool
- For the categorize tool specifically: say "Let me note that down" or "One moment" BEFORE calling it — never call it silently
- NEVER go silent while processing — always speak before using a tool
- After a tool returns results, summarize them naturally — do NOT read raw data
- ONLY answer from your configured sources — NEVER make up or guess information
- Confirm details (date, time, phone number, etc.) with the caller BEFORE taking actions like booking or sending messages
- Search for existing contacts before creating new ones — never share other customers' information
- Only transfer or end a call when the caller explicitly requests it""",
    "sv": """- Håll svar till 1-2 meningar — röstsamtal är en konversation, inte en föreläsning
- Ställ en fråga i taget, inte flera
- Om du inte vet något, säg det ärligt
- Innan du anropar NÅGOT verktyg, säg ALLTID ett kort meddelande först (t.ex. "Låt mig kolla det åt dig")
- Bli ALDRIG tyst under bearbetning — tala alltid innan du använder ett verktyg
- Efter att ett verktyg returnerar resultat, sammanfatta dem naturligt — läs INTE rådata
- Svara BARA från dina konfigurerade källor — hitta ALDRIG på eller gissa information
- Bekräfta detaljer (datum, tid, telefonnummer etc.) med den som ringer INNAN du vidtar åtgärder som bokning eller meddelanden
- Sök efter befintliga kontakter innan du skapar nya — dela aldrig andra kunders information
- Koppla eller avsluta ett samtal bara när den som ringer uttryckligen begär det""",
    "es": """- Limita las respuestas a 1-2 oraciones — la voz es conversación, no monólogo
- Haz una pregunta a la vez, no varias
- Si no sabes algo, dilo honestamente
- Antes de llamar a CUALQUIER herramienta, SIEMPRE di un breve reconocimiento primero (ej., "Déjame buscar eso")
- NUNCA te quedes en silencio mientras procesas — siempre habla antes de usar una herramienta
- Después de que una herramienta devuelva resultados, resúmelos naturalmente — NO leas datos crudos
- SOLO responde desde tus fuentes configuradas — NUNCA inventes o adivines información
- Confirma detalles (fecha, hora, teléfono, etc.) con el llamante ANTES de tomar acciones como reservar o enviar mensajes
- Busca contactos existentes antes de crear nuevos — nunca compartas información de otros clientes
- Solo transfiere o termina una llamada cuando el llamante lo solicite explícitamente""",
    "fr": """- Limitez les réponses à 1-2 phrases — la voix est une conversation, pas un monologue
- Posez une question à la fois, pas plusieurs
- Si vous ne savez pas quelque chose, dites-le honnêtement
- Avant d'appeler UN outil, dites TOUJOURS un bref mot d'abord (ex., "Laissez-moi vérifier")
- Ne restez JAMAIS silencieux pendant le traitement — parlez toujours avant d'utiliser un outil
- Après qu'un outil retourne des résultats, résumez-les naturellement — ne lisez PAS les données brutes
- Répondez UNIQUEMENT depuis vos sources configurées — n'inventez JAMAIS d'information
- Confirmez les détails (date, heure, téléphone, etc.) avec l'appelant AVANT de réserver ou d'envoyer des messages
- Recherchez les contacts existants avant d'en créer — ne partagez jamais les infos d'autres clients
- Ne transférez ou terminez un appel que sur demande explicite de l'appelant""",
    "de": """- Halten Sie Antworten auf 1-2 Sätze — Sprache ist Gespräch, kein Vortrag
- Stellen Sie eine Frage auf einmal, nicht mehrere
- Wenn Sie etwas nicht wissen, sagen Sie es ehrlich
- Vor dem Aufruf EINES Werkzeugs sagen Sie IMMER kurz Bescheid (z.B. "Lassen Sie mich das nachschauen")
- Werden Sie NIEMALS still während der Verarbeitung — sprechen Sie immer bevor Sie ein Werkzeug verwenden
- Fassen Sie Ergebnisse natürlich zusammen — lesen Sie KEINE Rohdaten vor
- Antworten Sie NUR aus Ihren konfigurierten Quellen — erfinden Sie NIEMALS Informationen
- Bestätigen Sie Details (Datum, Uhrzeit, Telefonnummer etc.) mit dem Anrufer VOR Buchungen oder Nachrichten
- Suchen Sie bestehende Kontakte bevor Sie neue erstellen — teilen Sie nie Daten anderer Kunden
- Leiten Sie einen Anruf nur auf ausdrückliche Anfrage weiter oder beenden Sie ihn""",
    "it": """- Limita le risposte a 1-2 frasi — la voce è conversazione, non monologo
- Fai una domanda alla volta, non più di una
- Se non sai qualcosa, dillo onestamente
- Prima di chiamare QUALSIASI strumento, dì SEMPRE un breve riconoscimento (es., "Fammi controllare")
- Non restare MAI in silenzio durante l'elaborazione — parla sempre prima di usare uno strumento
- Riassumi i risultati naturalmente — NON leggere dati grezzi
- Rispondi SOLO dalle tue fonti configurate — non inventare MAI informazioni
- Conferma i dettagli (data, ora, telefono, ecc.) con il chiamante PRIMA di prenotare o inviare messaggi
- Cerca contatti esistenti prima di crearne nuovi — non condividere mai info di altri clienti
- Trasferisci o termina una chiamata solo su richiesta esplicita del chiamante""",
    "pt": """- Limite as respostas a 1-2 frases — voz é conversa, não monólogo
- Faça uma pergunta de cada vez, não várias
- Se não souber algo, diga honestamente
- Antes de chamar QUALQUER ferramenta, SEMPRE diga algo breve primeiro (ex., "Deixe-me verificar isso")
- NUNCA fique em silêncio durante o processamento — sempre fale antes de usar uma ferramenta
- Resuma os resultados naturalmente — NÃO leia dados brutos
- Responda APENAS a partir de suas fontes configuradas — NUNCA invente informações
- Confirme detalhes (data, hora, telefone, etc.) com o chamador ANTES de reservar ou enviar mensagens
- Procure contatos existentes antes de criar novos — nunca compartilhe informações de outros clientes
- Só transfira ou encerre uma chamada quando o chamador solicitar explicitamente""",
    "nl": """- Beperk antwoorden tot 1-2 zinnen — stem is gesprek, geen lezing
- Stel één vraag per keer, niet meerdere
- Als u iets niet weet, zeg het eerlijk
- Zeg ALTIJD kort iets voordat u een tool aanroept (bijv., "Laat me dat even opzoeken")
- Wees NOOIT stil tijdens verwerking — spreek altijd voordat u een tool gebruikt
- Vat resultaten natuurlijk samen — lees GEEN ruwe data voor
- Antwoord ALLEEN uit uw geconfigureerde bronnen — verzin NOOIT informatie
- Bevestig details (datum, tijd, telefoonnummer, etc.) met de beller VOOR het boeken of versturen van berichten
- Zoek bestaande contacten voordat u nieuwe aanmaakt — deel nooit informatie van andere klanten
- Schakel of beëindig een gesprek alleen op uitdrukkelijk verzoek van de beller""",
    "ja": """- 回答は1〜2文に収めてください — 音声は会話であり、独演会ではありません
- 質問は一度に一つだけにしてください
- わからないことは正直に伝えてください
- ツールを呼び出す前に、必ず短い確認の言葉を言ってください（例：「確認させてください」）
- 処理中に沈黙しないでください — ツール使用前に必ず話してください
- 結果を自然に要約してください — 生データを読み上げないでください
- 設定されたソースからのみ回答してください — 情報を作り出さないでください
- 予約やメッセージ送信の前に、日付・時間・電話番号等の詳細を発信者に確認してください
- 新規作成前に既存の連絡先を検索してください — 他の顧客の情報を共有しないでください
- 発信者が明示的に要求した場合のみ転送または終了してください""",
    "ko": """- 답변은 1-2문장으로 제한하세요 — 음성은 대화이지 독백이 아닙니다
- 한 번에 하나의 질문만 하세요
- 모르는 것이 있으면 솔직히 말하세요
- 도구를 호출하기 전에 항상 짧은 확인 메시지를 먼저 말하세요 (예: "확인해 보겠습니다")
- 처리 중에 절대 침묵하지 마세요 — 도구 사용 전에 항상 말하세요
- 결과를 자연스럽게 요약하세요 — 원시 데이터를 읽지 마세요
- 구성된 소스에서만 답변하세요 — 정보를 만들어내지 마세요
- 예약이나 메시지 전송 전에 날짜, 시간, 전화번호 등의 세부 사항을 발신자에게 확인하세요
- 새로 만들기 전에 기존 연락처를 검색하세요 — 다른 고객의 정보를 공유하지 마세요
- 발신자가 명시적으로 요청할 때만 전환하거나 종료하세요""",
    "zh": """- 回答控制在1-2句话以内 — 语音是对话，不是独白
- 一次只问一个问题
- 如果不知道某事，请诚实说明
- 调用任何工具之前，始终先说一句简短的话（如"让我查一下"）
- 处理过程中绝不要沉默 — 使用工具前始终先说话
- 自然地总结结果 — 不要读取原始数据
- 只从配置的来源回答 — 绝不编造或猜测信息
- 在预约或发送消息前，先与来电者确认日期、时间、电话号码等详情
- 创建新联系人前先搜索现有联系人 — 绝不分享其他客户的信息
- 只有在来电者明确要求时才转接或结束通话""",
    "ru": """- Ограничьте ответы 1-2 предложениями — голос — это разговор, а не монолог
- Задавайте по одному вопросу за раз
- Если вы чего-то не знаете, честно скажите об этом
- Перед вызовом ЛЮБОГО инструмента ВСЕГДА скажите краткое подтверждение (напр., "Позвольте мне проверить")
- НИКОГДА не молчите во время обработки — всегда говорите перед использованием инструмента
- Резюмируйте результаты естественно — НЕ читайте сырые данные
- Отвечайте ТОЛЬКО из настроенных источников — НИКОГДА не выдумывайте информацию
- Подтвердите детали (дата, время, номер телефона и т.д.) со звонящим ПЕРЕД бронированием или отправкой сообщений
- Ищите существующие контакты перед созданием новых — никогда не делитесь данными других клиентов
- Переводите или завершайте звонок только по явной просьбе звонящего""",
    "ar": """- اقصر إجاباتك على 1-2 جملة — الصوت محادثة وليس خطابًا
- اطرح سؤالًا واحدًا في كل مرة
- إذا كنت لا تعرف شيئًا، قل ذلك بصدق
- قبل استدعاء أي أداة، قل دائمًا عبارة قصيرة أولاً (مثل "دعني أتحقق من ذلك")
- لا تصمت أبدًا أثناء المعالجة — تحدث دائمًا قبل استخدام أداة
- لخص النتائج بشكل طبيعي — لا تقرأ البيانات الخام
- أجب فقط من مصادرك المُعدة — لا تختلق أبدًا معلومات
- تأكد من التفاصيل (التاريخ، الوقت، رقم الهاتف، إلخ) مع المتصل قبل الحجز أو إرسال الرسائل
- ابحث عن جهات الاتصال الموجودة قبل إنشاء جديدة — لا تشارك أبدًا معلومات عملاء آخرين
- حوّل أو أنهِ المكالمة فقط عندما يطلب المتصل ذلك صراحةً""",
    "hi": """- जवाब 1-2 वाक्यों तक सीमित रखें — आवाज़ बातचीत है, भाषण नहीं
- एक बार में एक ही प्रश्न पूछें
- अगर आप कुछ नहीं जानते, तो ईमानदारी से बताएं
- कोई भी उपकरण कॉल करने से पहले, हमेशा पहले एक संक्षिप्त पुष्टि कहें (जैसे "मुझे जांचने दीजिए")
- प्रोसेसिंग के दौरान कभी चुप न रहें — उपकरण उपयोग से पहले हमेशा बोलें
- परिणामों को स्वाभाविक रूप से सारांशित करें — कच्चा डेटा न पढ़ें
- केवल अपने कॉन्फ़िगर किए गए स्रोतों से उत्तर दें — कभी जानकारी न बनाएं
- बुकिंग या संदेश भेजने से पहले, कॉलर से तारीख, समय, फ़ोन नंबर आदि की पुष्टि करें
- नए बनाने से पहले मौजूदा संपर्कों की खोज करें — अन्य ग्राहकों की जानकारी साझा न करें
- कॉल तभी ट्रांसफ़र या समाप्त करें जब कॉलर स्पष्ट रूप से अनुरोध करे""",
    "pl": """- Ogranicz odpowiedzi do 1-2 zdań — głos to rozmowa, nie wykład
- Zadawaj jedno pytanie na raz
- Jeśli czegoś nie wiesz, powiedz to szczerze
- Przed wywołaniem DOWOLNEGO narzędzia ZAWSZE powiedz krótkie potwierdzenie (np. "Pozwól, że sprawdzę")
- NIGDY nie milcz podczas przetwarzania — zawsze mów przed użyciem narzędzia
- Podsumuj wyniki naturalnie — NIE czytaj surowych danych
- Odpowiadaj TYLKO ze skonfigurowanych źródeł — NIGDY nie wymyślaj informacji
- Potwierdź szczegóły (datę, godzinę, numer telefonu itp.) z dzwoniącym PRZED rezerwacją lub wysłaniem wiadomości
- Szukaj istniejących kontaktów przed tworzeniem nowych — nigdy nie udostępniaj danych innych klientów
- Przekieruj lub zakończ połączenie tylko na wyraźną prośbę dzwoniącego""",
    "tr": """- Yanıtları 1-2 cümleyle sınırlayın — ses konuşmadır, monolog değil
- Bir seferde tek soru sorun
- Bir şeyi bilmiyorsanız, dürüstçe söyleyin
- HERHANGİ bir aracı çağırmadan önce HER ZAMAN kısa bir onay söyleyin (örn., "Kontrol edeyim")
- İşlem sırasında ASLA sessiz kalmayın — araç kullanmadan önce her zaman konuşun
- Sonuçları doğal olarak özetleyin — ham veri okumayın
- YALNIZCA yapılandırılmış kaynaklarınızdan yanıt verin — ASLA bilgi uydurmayın
- Rezervasyon veya mesaj göndermeden önce tarih, saat, telefon numarası gibi detayları arayanla onaylayın
- Yeni oluşturmadan önce mevcut kişileri arayın — diğer müşterilerin bilgilerini asla paylaşmayın
- Çağrıyı yalnızca arayan açıkça talep ettiğinde aktarın veya sonlandırın""",
}


def build_instructions_with_language(  # noqa: PLR0912, PLR0915
    system_prompt: str,
    language: str,
    enabled_tools: list[str] | None = None,
    timezone: str | None = None,
    knowledge_base_info: dict[str, Any] | None = None,
    use_best_practices: bool = True,
    campaign_context: dict[str, Any] | None = None,
) -> str:
    """Build comprehensive voice agent instructions.

    Wraps the user's custom system prompt with voice-specific configuration
    including language requirements, conversation guidelines, and tool context.

    Args:
        system_prompt: The agent's custom system prompt (from frontend UI)
        language: Language code (e.g., "en-US", "es-ES")
        enabled_tools: List of enabled tool IDs (optional, for context)
        timezone: Workspace timezone (e.g., "America/New_York", "UTC")
        knowledge_base_info: Info about uploaded documents (optional)
            - document_count: Number of documents
            - document_names: List of document filenames
        use_best_practices: Whether to include language-specific best practices

    Returns:
        Complete instructions string optimized for voice conversations
    """
    language_name = LANGUAGE_NAMES.get(language, language)
    tz_name = timezone or "UTC"
    enabled_tools = enabled_tools or []

    # Get current date/time in the workspace timezone for context
    from datetime import datetime

    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        current_datetime = now.strftime("%A, %B %d, %Y at %I:%M %p")
    except Exception:
        # Fallback if timezone is invalid
        current_datetime = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")

    # Build information retrieval section with priority ordering
    info_retrieval_section = ""
    has_knowledge_base = knowledge_base_info and knowledge_base_info.get("document_count", 0) > 0
    has_site_search = "site_search" in enabled_tools

    if has_knowledge_base or has_site_search:
        info_retrieval_section = "\n[INFORMATION RETRIEVAL - PRIORITY ORDER]\n"

        if has_knowledge_base and knowledge_base_info:
            doc_count = knowledge_base_info["document_count"]
            doc_names = knowledge_base_info.get("document_names", [])

            # Format document list (limit for brevity)
            max_docs_to_show = 10
            if doc_names:
                doc_list = ", ".join(doc_names[:max_docs_to_show])
                if len(doc_names) > max_docs_to_show:
                    doc_list += f", and {len(doc_names) - max_docs_to_show} more"
            else:
                doc_list = f"{doc_count} documents"

            info_retrieval_section += f"""1. FIRST - Knowledge Base ({doc_count} documents: {doc_list}):
   - ALWAYS search knowledge_base FIRST for questions about products, services, pricing, policies, FAQs
   - Use search_knowledge_base("relevant search terms") before answering
   - Examples: pricing -> search_knowledge_base("pricing rates cost")

"""
            if has_site_search:
                info_retrieval_section += """2. SECOND - Site Search (only if knowledge base has no answer):
   - Use search_site ONLY when knowledge_base returns no relevant results
   - search_site will intelligently crawl the configured website to find information

"""
        elif has_site_search:
            info_retrieval_section += """1. Site Search:
   - Use search_site to find information on the configured website
   - Summarize findings concisely for voice

"""

        info_retrieval_section += """IMPORTANT: You MUST ONLY answer from the sources listed above. Do NOT use general knowledge or training data for topics covered by your configured sources. If nothing is found, say so — do NOT invent answers.
"""

    # Build best practices section (translated to agent's language)
    best_practices_section = ""
    if use_best_practices:
        # Get language code prefix (e.g., "en" from "en-US", "sv" from "sv-SE")
        lang_prefix = language.split("-")[0] if "-" in language else language
        practices = BEST_PRACTICES.get(lang_prefix, BEST_PRACTICES.get("en", ""))
        if practices:
            best_practices_section = f"\n[BEST PRACTICES]\n{practices}\n"

    # Build lookup guidance section when lookup is enabled
    lookup_section = ""
    if "lookup" in enabled_tools or any(t.startswith("lookup") for t in (enabled_tools or [])):
        lookup_section = """\n[LOOKUP RESULTS]
- As soon as the caller confirms their property or location name, call lookup_search immediately — before asking what they need help with. Do not skip or defer this step.
- If a lookup returns multiple records (e.g. several buildings at the same address), present the options to the caller and ask which one applies — do NOT say there is a technical problem.
- If a lookup returns no results, say clearly that you could not find the information and offer to help in another way.
- Never invent or guess property details that were not returned by the lookup tool.
- Never say a city, area, or street name that the caller did not explicitly mention. If the caller gives a city use it exactly; if they did not, do not invent one.
- Apartment/building unit codes are a letter followed by a digit (E1, E2, E3, E4). Copy them exactly as stated. Never convert a digit to a letter or vice versa (E2 is not EF, not EF2, not E-F).
"""

    # Build email tool section when Resend is enabled
    email_section = ""
    if "resend" in enabled_tools:
        email_section = """\n[EMAIL]
- You can send emails using the resend_send_email tool.
- Call resend_send_email with: to (recipient address), subject, and body (plain-text).
- Follow the instructions in [YOUR ROLE] for when to send, to whom, and what to include.
- If [YOUR ROLE] does not specify a recipient, ask the caller for their email address before sending.
"""

    # Build campaign context section if this is an outbound campaign call
    campaign_section = ""
    if campaign_context:
        campaign_section = (
            "\n\n[CAMPAIGN MISSION - THIS CALL]\n"
            "IMPORTANT: You are making an OUTBOUND campaign call. "
            "The campaign script/objective below is your PRIMARY task for this call. "
            "Follow it precisely. Your role guidelines above still apply for conversation style, "
            "but this campaign mission defines what you must accomplish.\n"
        )

        script = campaign_context.get("campaign_script")
        if script:
            campaign_section += f"\nCampaign script / objective:\n{script}\n"

        contact_name = campaign_context.get("contact_name")
        if contact_name:
            campaign_section += f"\nContact name: {contact_name}\n"
            campaign_section += "Always address the contact by name.\n"

        contact_company = campaign_context.get("contact_company")
        if contact_company:
            campaign_section += f"Company: {contact_company}\n"

        contact_email = campaign_context.get("contact_email")
        if contact_email:
            campaign_section += f"Email: {contact_email}\n"

        contact_tags = campaign_context.get("contact_tags")
        if contact_tags:
            campaign_section += f"Tags: {contact_tags}\n"

        contact_notes = campaign_context.get("contact_notes")
        if contact_notes:
            campaign_section += f"Notes: {contact_notes}\n"

        campaign_section += (
            "\nAfter the call ends, use set_call_disposition to record the outcome.\n"
        )

    # Build the complete voice agent instructions
    instructions = f"""[LANGUAGE — READ THIS FIRST]
Default: {language_name}. ALWAYS respond in the language the caller is currently speaking.
If the caller asks to switch language: switch IMMEDIATELY and NEVER revert — not even after a long pause.
The best-practices text below is written in {language_name} as a style guide; it does NOT override this rule.

[CONTEXT]
Language: {language_name}
Timezone: {tz_name}
Current: {current_datetime}

[RULES]
- Respond in the language the caller is speaking. If they switch, you switch permanently for the rest of the call.
- All times are in {tz_name} timezone
- For booking tools, use ISO format with timezone offset (e.g., 2024-12-01T14:00:00-05:00)
- Keep responses to 1-2 sentences maximum - voice is conversational, not a monologue
- Summarize tool results naturally
- When the caller spells out a name or code letter-by-letter, echo back the EXACT same letters in the EXACT same order. Never substitute, add, or remove any character — M and N are different letters, a digit (1, 2, 3) is never a letter (F, L, Z). Do not map spelled characters to a "known" word or name. Only move on when the caller explicitly confirms the sequence is correct.
- If the caller repeats or corrects the same thing twice without you understanding, stop building on your previous assumption. Ask: "I want to make sure I understand — could you describe the issue in a different way?" Do not ask follow-up questions based on what you thought you heard until the caller confirms you understood correctly.
{info_retrieval_section}{best_practices_section}{lookup_section}{email_section}
[YOUR ROLE]
{system_prompt}{campaign_section}"""

    return instructions


class TranscriptEntry:
    """Single transcript entry representing one turn in the conversation."""

    def __init__(self, role: str, content: str, timestamp: str | None = None) -> None:
        from datetime import UTC, datetime

        self.role = role  # "user" or "assistant"
        self.content = content
        self.timestamp = timestamp or datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}


class GPTRealtimeSession:
    """Manages a GPT Realtime API session for a voice call.

    Handles:
    - WebSocket connection to OpenAI Realtime API
    - Internal tool integration
    - Audio streaming
    - Tool call routing to internal tool handlers
    - Transcript accumulation
    """

    def __init__(
        self,
        db: AsyncSession,
        user_id: int,
        agent_config: dict[str, Any],
        session_id: str | None = None,
        workspace_id: uuid.UUID | None = None,
    ) -> None:
        """Initialize GPT Realtime session.

        Args:
            db: Database session
            user_id: User ID (int, from users.id)
            agent_config: Agent configuration (system prompt, enabled integrations, etc.)
            session_id: Optional session ID
            workspace_id: Workspace UUID (required for API key isolation)
        """
        self.db = db
        self.user_id = user_id  # int for ToolRegistry (Contact queries)
        self.user_id_uuid = user_id_to_uuid(user_id)  # UUID for UserSettings queries
        self.workspace_id = workspace_id  # For workspace-isolated API key lookup
        self.agent_config = agent_config
        self.session_id = session_id or str(uuid.uuid4())
        self.connection: Any = None
        self.tool_registry: ToolRegistry | None = None
        self.client: AsyncOpenAI | None = None
        # Transcript accumulation
        self._transcript_entries: list[TranscriptEntry] = []
        self._current_assistant_text: str = ""
        # Initial greeting (triggered after event loop starts to avoid race condition)
        self._pending_initial_greeting: str | None = None
        self._greeting_triggered: bool = False
        # Audio gate: True while a tool call is executing. send_audio() drops
        # frames when set so VAD cannot fire and generate spurious "I'm still
        # looking…" responses that corrupt the function_call_output cycle.
        self._audio_paused: bool = False
        self.logger = logger.bind(
            component="gpt_realtime",
            session_id=self.session_id,
            user_id=str(user_id),
            workspace_id=str(workspace_id) if workspace_id else None,
        )

    async def initialize(self) -> None:
        """Initialize the Realtime session with internal tools."""
        self.logger.info("gpt_realtime_session_initializing")

        # Get user's API keys from settings (uses UUID)
        # Workspace isolation: only use workspace-specific API keys, no fallback
        user_settings = await get_user_api_keys(
            self.user_id_uuid, self.db, workspace_id=self.workspace_id
        )

        # Strictly use workspace API key - no fallback to global key for billing isolation
        if not user_settings or not user_settings.openai_api_key:
            self.logger.warning("workspace_missing_openai_key", workspace_id=str(self.workspace_id))
            raise ValueError(
                "OpenAI API key not configured for this workspace. Please add it in Settings > Workspace API Keys."
            )
        api_key = user_settings.openai_api_key
        self.logger.info("using_workspace_openai_key")

        # Initialize OpenAI client with user's or global API key
        self.client = AsyncOpenAI(api_key=api_key)

        # Get integration credentials for the workspace
        integrations: dict[str, Any] = {}
        if self.workspace_id:
            integrations = await get_workspace_integrations(
                self.user_id_uuid, self.workspace_id, self.db
            )

        # Get agent's tool_configs (per-tool settings like web_search domain restriction)
        tool_configs = self.agent_config.get("tool_configs", {})

        # Get agent_id from config if available
        agent_id_str = self.agent_config.get("agent_id")
        agent_id = uuid.UUID(agent_id_str) if agent_id_str else None

        # Get Redis for tool result caching
        from app.db.redis import get_redis as _get_redis

        try:
            _redis = await _get_redis()
        except Exception:
            _redis = None

        # Initialize tool registry with enabled tools and workspace context
        # Pass OpenAI API key for RAG embeddings fallback
        campaign_context = self.agent_config.get("campaign_context")
        self.tool_registry = ToolRegistry(
            self.db,
            self.user_id,
            integrations=integrations,
            workspace_id=self.workspace_id,
            agent_id=agent_id,
            openai_api_key=api_key,
            tool_configs=tool_configs,
            campaign_context=campaign_context,
            redis=_redis,
        )

        # Pre-warm tool data while WebSocket connection establishes
        enabled_tools = self.agent_config.get("enabled_tools", [])
        if "lookup" in enabled_tools:
            try:
                await self.tool_registry.prewarm_collections()
                self.logger.info("lookup_collections_prewarmed")
            except Exception:
                self.logger.warning("lookup_prewarm_failed_continuing")

        if "categorization" in enabled_tools or "category_tree" in enabled_tools:
            try:
                await self.tool_registry.prewarm_category_trees()
                self.logger.info("category_trees_prewarmed")
            except Exception:
                self.logger.warning("category_trees_prewarm_failed_continuing")

        # Connect to OpenAI Realtime API
        await self._connect_realtime_api()

        self.logger.info("gpt_realtime_session_initialized")

    async def _connect_realtime_api(self) -> None:
        """Establish connection to OpenAI Realtime API using official SDK."""
        if not self.client:
            raise ValueError("OpenAI client not initialized")

        model = self.agent_config.get("llm_model", "gpt-realtime-1.5")
        self.logger.warning("connecting_to_openai_realtime", model=model)

        try:
            # Use official SDK's realtime.connect() method
            self.connection = await self.client.beta.realtime.connect(model=model).__aenter__()

            self.logger.info("realtime_connection_established")

            # Configure session with internal tools
            await self._configure_session()

            self.logger.info("connected_to_openai_realtime")

        except Exception as e:
            self.logger.exception(
                "realtime_connection_failed", error=str(e), error_type=type(e).__name__
            )
            raise

    async def _configure_session(self) -> None:  # noqa: PLR0915
        """Configure Realtime API session with agent settings and internal tools."""
        if not self.connection or not self.tool_registry:
            self.logger.warning(
                "session_config_skipped",
                has_connection=bool(self.connection),
                has_registry=bool(self.tool_registry),
            )
            return

        # Get tool definitions from registry
        enabled_tools = self.agent_config.get("enabled_tools", [])
        enabled_tool_ids = self.agent_config.get("enabled_tool_ids", {})
        tools = self.tool_registry.get_all_tool_definitions(enabled_tools, enabled_tool_ids)

        # Get workspace timezone if available
        workspace_timezone = "UTC"
        if self.workspace_id:
            from app.models.workspace import Workspace

            result = await self.db.execute(
                select(Workspace).where(Workspace.id == self.workspace_id)
            )
            workspace = result.scalar_one_or_none()
            if workspace and workspace.settings:
                workspace_timezone = workspace.settings.get("timezone", "UTC")

        # Get knowledge base info if agent has documents
        knowledge_base_info: dict[str, Any] | None = None
        agent_id_str = self.agent_config.get("agent_id")
        if agent_id_str and "knowledge_base" in enabled_tools:
            from app.models.document import Document

            agent_uuid = uuid.UUID(agent_id_str)
            # Query ready documents for this agent
            result = await self.db.execute(
                select(Document.filename)
                .where(Document.agent_id == agent_uuid)
                .where(Document.status == "ready")
            )
            doc_names = [row[0] for row in result.fetchall()]
            if doc_names:
                knowledge_base_info = {
                    "document_count": len(doc_names),
                    "document_names": doc_names,
                }
                self.logger.info(
                    "knowledge_base_context_loaded",
                    document_count=len(doc_names),
                )

        # Build instructions with language directive and timezone
        system_prompt = self.agent_config.get("system_prompt", "You are a helpful voice assistant.")
        language = self.agent_config.get("language", "en-US")
        use_best_practices = self.agent_config.get("use_best_practices", True)
        # Default to marin for natural conversational tone
        voice = self.agent_config.get("voice", "marin")
        temperature = self.agent_config.get("temperature", 0.6)
        campaign_context = self.agent_config.get("campaign_context")
        instructions = build_instructions_with_language(
            system_prompt,
            language,
            enabled_tools=enabled_tools,
            timezone=workspace_timezone,
            knowledge_base_info=knowledge_base_info,
            use_best_practices=use_best_practices,
            campaign_context=campaign_context,
        )

        # Store instructions so trigger_initial_greeting() can inject them
        # directly into the conversation history (the reliable path).
        self._session_instructions = instructions

        # Use agent's VAD settings (from DB) instead of hardcoded values
        vad_prefix_padding_ms = self.agent_config.get("turn_detection_prefix_padding_ms", 300)
        vad_silence_duration_ms = self.agent_config.get("turn_detection_silence_duration_ms", 500)

        # Build turn detection config based on agent mode
        turn_detection_mode = self.agent_config.get("turn_detection_mode", "normal")
        if turn_detection_mode == "disabled":
            turn_detection: dict[str, Any] | None = None
        elif turn_detection_mode == "semantic":
            turn_detection = {
                "type": "semantic_vad",
                "eagerness": "medium",
            }
        else:
            turn_detection = {
                "type": "server_vad",
                "prefix_padding_ms": vad_prefix_padding_ms,
                "silence_duration_ms": vad_silence_duration_ms,
            }

        session_config: dict[str, Any] = {
            "modalities": ["text", "audio"],
            "instructions": instructions,
            "voice": voice,
            "speed": 1.0,  # Natural pace for telephony (1.1 sounds rushed over mulaw)
            "temperature": temperature,  # Lower for consistent, natural delivery
            # Both input and output use pcm16 (OpenAI native 24kHz format).
            # Conversion between mulaw 8kHz (Twilio) and PCM16 24kHz (OpenAI)
            # happens in the telephony WebSocket handler using audioop.
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {
                "model": self.agent_config.get("transcription_model", "gpt-4o-transcribe")
            },
            "tools": tools,
            "tool_choice": "auto",
        }
        if turn_detection is not None:
            session_config["turn_detection"] = turn_detection

        self.logger.warning(
            "configuring_session",
            tool_count=len(tools),
            enabled_tools=enabled_tools,
            instructions_len=len(instructions),
            instructions_preview=instructions[:150],
        )

        try:
            # Single session.update() with all fields — split updates risk the
            # second call resetting fields not included in it on some model variants.
            await self.connection.session.update(session=session_config)

            self.logger.warning(
                "session_configured",
                tool_count=len(tools),
                instructions_applied=True,
                session_keys=list(session_config.keys()),
            )

            # Store initial greeting for later - triggered after event loop starts
            # to avoid race condition where audio events arrive before listener is ready
            initial_greeting = self.agent_config.get("initial_greeting")
            if initial_greeting:
                self._pending_initial_greeting = initial_greeting
                self.logger.info(
                    "initial_greeting_pending",
                    greeting=initial_greeting[:50],
                )
        except Exception as e:
            self.logger.exception(
                "session_config_failed", error=str(e), error_type=type(e).__name__
            )
            raise

    async def handle_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        """Handle tool call from GPT Realtime by routing to internal tools.

        Args:
            tool_call: Tool call from GPT Realtime

        Returns:
            Tool result
        """
        if not self.tool_registry:
            return {"success": False, "error": "Tool registry not initialized"}

        tool_name = tool_call.get("name", "")
        arguments = tool_call.get("arguments", {})

        self.logger.info(
            "handling_tool_call",
            tool_name=tool_name,
            arguments=arguments,
        )

        # Execute tool via internal tool registry
        result = await self.tool_registry.execute_tool(tool_name, arguments)

        return result

    async def process_realtime_events(self) -> None:
        """Process events from OpenAI Realtime API using official SDK.

        This is the main event loop that:
        1. Receives events from OpenAI
        2. Handles tool calls by routing to internal tool handlers
        3. Sends responses back to OpenAI
        """
        if not self.connection:
            raise RuntimeError("Realtime connection not established")

        try:
            async for event in self.connection:
                try:
                    event_type = event.type

                    self.logger.debug("realtime_event_received", event_type=event_type)

                    # Handle function/tool calls
                    if event_type == "response.function_call_arguments.done":
                        await self.handle_function_call_event(event)

                    # Handle audio output
                    elif event_type == "response.audio.delta":
                        # Audio data available in event.delta
                        pass

                    # Handle transcription
                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        # Transcription available in event.transcript
                        pass

                    # Handle errors
                    elif event_type == "error":
                        self.logger.error("realtime_api_error", error=event.error)

                except Exception as e:
                    self.logger.exception("event_processing_error", error=str(e))

        except Exception as e:
            self.logger.exception("realtime_event_loop_error", error=str(e))
            raise

    async def handle_function_call_event(self, event: Any) -> dict[str, Any]:
        """Handle function call from GPT Realtime.

        Args:
            event: Function call event from SDK

        Returns:
            Tool execution result with optional 'action' field for call control
        """
        call_id = event.call_id
        name = event.name

        # Parse arguments safely - GPT may send incomplete/malformed JSON
        try:
            arguments = (
                json.loads(event.arguments) if isinstance(event.arguments, str) else event.arguments
            )
        except json.JSONDecodeError as e:
            self.logger.warning(
                "function_call_json_parse_error",
                call_id=call_id,
                tool_name=name,
                raw_arguments=str(event.arguments)[:200],
                error=str(e),
            )
            # Return error to GPT so it can retry
            if self.connection:
                await self.connection.conversation.item.create(
                    item={
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({"success": False, "error": "Invalid JSON arguments"}),
                    }
                )
            return {"success": False, "error": "Invalid JSON arguments"}

        # Pause audio input for the duration of the tool call so Telnyx/Twilio
        # frames don't trigger VAD and cause OpenAI to auto-generate spurious
        # "I'm still looking…" responses that corrupt the function_call_output cycle.
        self._audio_paused = True
        try:
            result = await self.handle_tool_call({"name": name, "arguments": arguments})
        finally:
            self._audio_paused = False

        # Send result back using SDK
        if self.connection:
            # Cancel any VAD-triggered "I'm still looking…" response that the model
            # may have auto-generated while waiting for the tool result. If left
            # active it corrupts the conversation state and the function_call_output
            # is silently ignored.
            with contextlib.suppress(Exception):
                await self.connection.response.cancel()

            # Clear any audio that arrived before the gate closed.
            with contextlib.suppress(Exception):
                await self.connection.input_audio_buffer.clear()

            await self.connection.conversation.item.create(
                item={
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result),
                }
            )
            # Trigger GPT to generate a response after the function call
            await self.connection.response.create()

        self.logger.info(
            "function_call_completed",
            call_id=call_id,
            tool_name=name,
            success=result.get("success"),
            action=result.get("action"),
        )

        return result

    async def trigger_initial_greeting(self) -> bool:
        """Inject instructions into the conversation and optionally speak a greeting.

        Called after the event loop starts to avoid race conditions. Always injects
        the full instructions as a conversation message so gpt-realtime-2025-08-28
        reliably follows the system prompt — session.update() instructions alone are
        not consistently honoured by this telephony model variant across turns.

        Returns:
            True if setup was performed, False if already done or no connection.
        """
        if self._greeting_triggered:
            return False

        if not self.connection:
            self.logger.warning("cannot_trigger_greeting_no_connection")
            return False

        self._greeting_triggered = True
        greeting = self._pending_initial_greeting
        instructions = getattr(self, "_session_instructions", "")

        self.logger.info(
            "triggering_initial_greeting",
            has_greeting=bool(greeting),
            instructions_len=len(instructions),
        )

        try:
            # Clear any buffered input audio to prevent line noise from
            # triggering VAD and cancelling the greeting response.
            await self.connection.input_audio_buffer.clear()

            if greeting:
                # Inject instructions + greeting command as a single user message.
                context_text = (
                    f'{instructions}\n\nNow begin the call by saying exactly: "{greeting}"'
                ).strip()
                await self.connection.conversation.item.create(
                    item={
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": context_text}],
                    }
                )
                await self.connection.response.create()
            else:
                # No greeting — still inject instructions as a synthetic exchange so
                # the model has them in conversation context, not just session settings.
                await self.connection.conversation.item.create(
                    item={
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": instructions}],
                    }
                )
                await self.connection.conversation.item.create(
                    item={
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Understood. I'm ready."}],
                    }
                )

            return True
        except Exception as e:
            self.logger.exception("initial_greeting_failed", error=str(e))
            return False

    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio input to GPT Realtime using SDK.

        Args:
            audio_data: PCM16 audio data (raw bytes)
        """
        if self._audio_paused:
            # Drop frames while a tool call is executing to prevent VAD
            # from triggering spurious responses before function_call_output
            # is submitted.
            return

        if not self.connection:
            return

        try:
            import base64

            # Convert raw bytes to base64 string as required by OpenAI Realtime API
            audio_base64 = base64.b64encode(audio_data).decode("utf-8")

            # Use SDK's input_audio_buffer.append method
            await self.connection.input_audio_buffer.append(audio=audio_base64)
            self.logger.debug(
                "audio_sent_to_realtime",
                size_bytes=len(audio_data),
                base64_length=len(audio_base64),
            )
        except Exception as e:
            # Log at debug level — connection closes naturally at call end and
            # telnyx_to_realtime may send a few more frames before it notices.
            err_str = str(e)
            if "ConnectionClosed" in type(e).__name__ or "close" in err_str.lower():
                self.logger.debug("send_audio_skipped_connection_closed")
                self.connection = None  # stop future attempts immediately
            else:
                self.logger.warning("send_audio_error", error=err_str, error_type=type(e).__name__)

    def add_user_transcript(self, text: str) -> None:
        """Add a user transcript entry.

        Args:
            text: Transcribed user speech
        """
        if text.strip():
            self._transcript_entries.append(TranscriptEntry(role="user", content=text.strip()))
            self.logger.debug("user_transcript_added", text_length=len(text))

    def add_assistant_transcript(self, text: str) -> None:
        """Add an assistant transcript entry.

        Args:
            text: Assistant response text
        """
        if text.strip():
            self._transcript_entries.append(TranscriptEntry(role="assistant", content=text.strip()))
            self.logger.debug("assistant_transcript_added", text_length=len(text))

    def accumulate_assistant_text(self, delta: str) -> None:
        """Accumulate assistant text delta for transcript.

        Args:
            delta: Text delta from response.text.delta event
        """
        self._current_assistant_text += delta

    def flush_assistant_text(self) -> None:
        """Flush accumulated assistant text to transcript."""
        if self._current_assistant_text.strip():
            self.add_assistant_transcript(self._current_assistant_text)
        self._current_assistant_text = ""

    def get_transcript(self) -> str:
        """Get the full transcript as formatted text.

        Returns:
            Formatted transcript string
        """
        lines = []
        for entry in self._transcript_entries:
            role_label = "User" if entry.role == "user" else "Assistant"
            lines.append(f"[{role_label}]: {entry.content}")
        return "\n\n".join(lines)

    def get_transcript_entries(self) -> list[dict[str, str]]:
        """Get transcript entries as list of dicts.

        Returns:
            List of transcript entry dictionaries
        """
        return [entry.to_dict() for entry in self._transcript_entries]

    async def save_campaign_disposition(self, disposition: str, notes: str | None = None) -> None:
        """Save call disposition to the campaign contact record.

        Args:
            disposition: Disposition code (e.g., 'interested', 'not_interested')
            notes: Optional notes about the disposition
        """
        campaign_context = self.agent_config.get("campaign_context")
        if not campaign_context:
            self.logger.warning("save_disposition_no_campaign_context")
            return

        campaign_contact_id = campaign_context.get("campaign_contact_id")
        if not campaign_contact_id:
            self.logger.warning("save_disposition_no_campaign_contact_id")
            return

        try:
            from app.models.campaign import CampaignContact

            cc_uuid = uuid.UUID(campaign_contact_id)
            result = await self.db.execute(
                select(CampaignContact).where(CampaignContact.id == cc_uuid)
            )
            campaign_contact = result.scalar_one_or_none()

            if campaign_contact:
                campaign_contact.disposition = disposition
                campaign_contact.disposition_notes = notes
                await self.db.commit()
                self.logger.info(
                    "campaign_disposition_saved",
                    campaign_contact_id=campaign_contact_id,
                    disposition=disposition,
                )
            else:
                self.logger.warning(
                    "campaign_contact_not_found_for_disposition",
                    campaign_contact_id=campaign_contact_id,
                )
        except Exception as e:
            self.logger.exception("save_disposition_error", error=str(e))

    async def cleanup(self) -> None:
        """Cleanup resources."""
        self.logger.info("gpt_realtime_session_cleanup_started")

        # Flush any remaining assistant text
        self.flush_assistant_text()

        # Close Realtime connection
        if self.connection:
            try:
                # Try close() method first (if available)
                if hasattr(self.connection, "close"):
                    await self.connection.close()
                # Otherwise try aclose() for async generators
                elif hasattr(self.connection, "aclose"):
                    await self.connection.aclose()
                self.logger.info("realtime_connection_closed")
            except Exception as e:
                self.logger.warning("connection_close_failed", error=str(e))

        # Cleanup tool registry
        if self.tool_registry:
            # No cleanup needed for internal tools
            pass

        self.logger.info(
            "gpt_realtime_session_cleanup_completed",
            transcript_entries=len(self._transcript_entries),
        )

    async def __aenter__(self) -> "GPTRealtimeSession":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.cleanup()
