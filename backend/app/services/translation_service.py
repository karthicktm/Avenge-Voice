"""Translation service for cross-lingual knowledge base support."""

import structlog
from openai import AsyncOpenAI

logger = structlog.get_logger()

# Sample size for language detection (chars)
LANGUAGE_DETECTION_SAMPLE_SIZE = 1000


class TranslationService:
    """Translates text to English using OpenAI GPT models.

    Used during document ingestion to enable cross-lingual search:
    - Detects source language
    - Translates non-English content to English
    - English translations are embedded for semantic search
    - Original content is preserved and returned in search results
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        """Initialize translation service.

        Args:
            api_key: OpenAI API key
            model: Model to use for translation (gpt-4o-mini recommended for cost)
        """
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.logger = logger.bind(component="translation_service", model=model)

    async def detect_language(self, text: str) -> str:
        """Detect the language of text.

        Uses the langdetect library for fast, offline detection.

        Args:
            text: Text to detect language of

        Returns:
            ISO 639-1 language code (e.g., "en", "sv", "de")
        """
        try:
            from langdetect import detect  # type: ignore[import-not-found]

            # Sample first N chars for efficiency
            sample = (
                text[:LANGUAGE_DETECTION_SAMPLE_SIZE]
                if len(text) > LANGUAGE_DETECTION_SAMPLE_SIZE
                else text
            )
            lang: str = detect(sample)
            self.logger.debug("language_detected", language=lang, sample_length=len(sample))
            return lang
        except Exception as e:
            self.logger.warning("language_detection_failed", error=str(e))
            return "en"  # Default to English on failure

    async def translate_to_english(self, text: str, source_lang: str) -> tuple[str, bool]:
        """Translate text to English.

        Args:
            text: Text to translate
            source_lang: Source language code

        Returns:
            Tuple of (translated_text, success)
            On failure, returns original text with success=False
        """
        # Skip if already English
        if source_lang == "en":
            return text, True

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a precise translator. Translate the following text "
                            "to English. Maintain the original meaning, structure, and tone. "
                            "Preserve any technical terms, proper nouns, and formatting. "
                            "Only output the translation, nothing else."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                temperature=0.1,  # Low temperature for consistency
                max_tokens=len(text) * 2,  # Allow for expansion
            )

            translated = response.choices[0].message.content or text
            self.logger.debug(
                "translation_completed",
                source_lang=source_lang,
                original_length=len(text),
                translated_length=len(translated),
            )
            return translated, True

        except Exception as e:
            self.logger.warning(
                "translation_failed",
                source_lang=source_lang,
                text_length=len(text),
                error=str(e),
            )
            return text, False  # Return original on failure

    async def translate_chunks(self, chunks: list[str], source_lang: str) -> tuple[list[str], str]:
        """Translate a list of text chunks to English.

        Args:
            chunks: List of text chunks to translate
            source_lang: Source language code

        Returns:
            Tuple of (translated_chunks, status)
            Status is "completed", "partial", or "failed"
        """
        if source_lang == "en":
            return chunks, "not_needed"

        translated_chunks: list[str] = []
        success_count = 0

        for chunk in chunks:
            translated, success = await self.translate_to_english(chunk, source_lang)
            translated_chunks.append(translated)
            if success:
                success_count += 1

        # Determine overall status
        if success_count == len(chunks):
            status = "completed"
        elif success_count > 0:
            status = "partial"
        else:
            status = "failed"

        self.logger.info(
            "batch_translation_completed",
            source_lang=source_lang,
            total_chunks=len(chunks),
            success_count=success_count,
            status=status,
        )

        return translated_chunks, status
