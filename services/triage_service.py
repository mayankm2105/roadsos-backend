from __future__ import annotations
import json
import re
from typing import Optional
from utils.logger import get_logger
from config import settings
import google.generativeai as genai

logger = get_logger(__name__)


# ── Prompts ──────────────────────────────────────────────────

TRIAGE_QUESTION_GENERATOR_PROMPT = """
You are a medical triage assistant for road accident victims in India.
Based on the injury description, generate EXACTLY 5 targeted medical
assessment questions.

Rules:
1. Questions must be directly relevant to the described injury
2. Ask about: consciousness, pain level, bleeding, mobility, breathing
3. Each question must be answerable with YES/NO or a short phrase
4. Questions must escalate in severity (start mild, end critical)
5. Respond ONLY with a valid JSON array. No other text. No markdown.
6. Generate questions in {lang} language

Output format (exactly this JSON structure):
[
  {{"question": "...", "weight": 1.0}},
  {{"question": "...", "weight": 1.5}},
  {{"question": "...", "weight": 2.0}},
  {{"question": "...", "weight": 2.5}},
  {{"question": "...", "weight": 3.0}}
]

Weight represents how much this question contributes to severity score
(higher weight = more critical symptom).
Weights must range from 1.0 to 3.0. Total max score = sum of all weights
(used to normalize to 0-10 scale).

Injury description: {description}
"""

TRIAGE_ANSWER_SCORER_PROMPT = """
You are evaluating a medical triage answer for a road accident victim.

Question asked: {question}
Patient's answer: {answer}
Question weight: {weight}

Evaluate how concerning this answer is medically.
Score the answer from 0.0 to {weight}:
  0.0 = No concern (e.g. "no", "feeling fine", "no pain")
  {half_weight} = Moderate concern (e.g. "a little", "mild pain", "some discomfort")
  {weight} = Full concern (e.g. "yes", "severe pain", "cannot move", "bleeding heavily")

Respond ONLY with a JSON object. No other text. No markdown. No explanation.
Format: {{"score": 1.5, "reasoning": "one sentence explanation"}}
"""


class TriageService:

    def __init__(self):
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not configured")
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL
        )
        self.logger = get_logger(__name__)

    def _lang_to_name(self, lang: str) -> str:
        """Convert lang code to full language name for Gemini prompts."""
        return {
            "en": "English",
            "hi": "Hindi",
            "pa": "Punjabi",
            "hw": "Haryanvi (similar to Hindi)"
        }.get(lang, "English")

    def generate_questions(
        self,
        description: str,
        lang: str = "en"
    ) -> list[dict]:
        """
        Ask Gemini to generate 5 contextual triage questions.
        Returns list of {"question": str, "weight": float} dicts.

        This is SYNCHRONOUS — call via asyncio.to_thread() from endpoints.

        Error handling:
        - If Gemini returns invalid JSON: fall back to DEFAULT_QUESTIONS
        - If Gemini API fails entirely: fall back to DEFAULT_QUESTIONS
        - Never raise — triage must always produce questions
        """
        prompt = TRIAGE_QUESTION_GENERATOR_PROMPT.format(
            description=description,
            lang=self._lang_to_name(lang)
        )

        try:
            response = self.model.generate_content(prompt)
            text = response.text.strip()

            # Strip markdown code fences if present
            text = re.sub(r"```(?:json)?", "", text).strip()

            questions = json.loads(text)

            # Validate structure
            if not isinstance(questions, list) or len(questions) == 0:
                raise ValueError("Invalid questions format")

            # Ensure each has required fields
            validated = []
            for q in questions[:5]:  # max 5 questions
                if "question" in q and "weight" in q:
                    validated.append({
                        "question": str(q["question"]),
                        "weight": float(q["weight"])
                    })

            if len(validated) < 3:
                raise ValueError("Too few valid questions")

            self.logger.info(
                f"Generated {len(validated)} triage questions "
                f"for: '{description[:60]}'"
            )
            return validated

        except Exception as e:
            self.logger.warning(
                f"Gemini question generation failed ({e}), "
                f"using fallback questions"
            )
            return self._get_fallback_questions(lang)

    def _get_fallback_questions(self, lang: str) -> list[dict]:
        """
        Hardcoded fallback questions used when Gemini fails.
        Covers the 5 most critical trauma assessment indicators.
        """
        if lang == "hi":
            return [
                {"question": "क्या आप पूरी तरह से होश में हैं?", "weight": 2.5},
                {"question": "क्या आपको तेज दर्द हो रहा है (1-10 में)?", "weight": 2.0},
                {"question": "क्या कहीं से खून बह रहा है?", "weight": 2.5},
                {"question": "क्या आप अपने हाथ-पैर हिला सकते हैं?", "weight": 1.5},
                {"question": "क्या आपको सांस लेने में तकलीफ है?", "weight": 3.0},
            ]
        else:
            return [
                {"question": "Are you fully conscious and aware?", "weight": 2.5},
                {"question": "Rate your pain level from 1 to 10.", "weight": 2.0},
                {"question": "Is there any visible bleeding?", "weight": 2.5},
                {"question": "Can you move your arms and legs?", "weight": 1.5},
                {"question": "Are you having any difficulty breathing?", "weight": 3.0},
            ]

    def score_answer(
        self,
        question: str,
        answer: str,
        weight: float
    ) -> float:
        """
        Ask Gemini to score a single answer from 0.0 to weight.
        Returns the score as float.

        This is SYNCHRONOUS — call via asyncio.to_thread().

        Error handling:
        - If Gemini fails: use keyword heuristic fallback
        - Never raise — always return a score
        """
        prompt = TRIAGE_ANSWER_SCORER_PROMPT.format(
            question=question,
            answer=answer,
            weight=weight,
            half_weight=round(weight / 2, 1)
        )

        try:
            response = self.model.generate_content(prompt)
            text = response.text.strip()
            text = re.sub(r"```(?:json)?", "", text).strip()

            result = json.loads(text)
            score = float(result["score"])

            # Clamp to valid range
            score = max(0.0, min(score, weight))
            self.logger.debug(
                f"Answer scored: {score}/{weight} — "
                f"{result.get('reasoning', '')}"
            )
            return score

        except Exception as e:
            self.logger.warning(
                f"Gemini answer scoring failed ({e}), using heuristic"
            )
            return self._heuristic_score(answer, weight)

    def _heuristic_score(self, answer: str, weight: float) -> float:
        """
        Keyword-based fallback scorer when Gemini is unavailable.
        Conservative — errs on the side of higher scores (safer).
        """
        answer_lower = answer.lower().strip()

        # Positive/concerning indicators → high score
        high_indicators = [
            "yes", "हाँ", "ha", "bleeding", "खून", "severe", "गंभीर",
            "cannot", "नहीं कर सकता", "unconscious", "बेहोश",
            "10", "9", "8", "heavy", "बहुत", "worse"
        ]
        # Negative/safe indicators → low score
        low_indicators = [
            "no", "नहीं", "nahi", "fine", "okay", "ok", "ठीक",
            "mild", "slight", "थोड़ा", "1", "2", "3", "minor", "nothing"
        ]

        for word in high_indicators:
            if word in answer_lower:
                return round(weight * 0.85, 1)

        for word in low_indicators:
            if word in answer_lower:
                return round(weight * 0.15, 1)

        # Neutral → moderate score
        return round(weight * 0.5, 1)

    def compute_severity_score(
        self,
        questions: list[dict],
        answers: list[dict]
    ) -> float:
        """
        Compute overall severity score normalized to 0-10 scale.

        Formula:
          total_weight = sum of all question weights
          earned_score = sum of all answer score_contributions
          normalized = (earned_score / total_weight) * 10

        Rounds to 1 decimal place.
        """
        if not questions or not answers:
            return 0.0

        total_weight = sum(q.get("weight", 1.0) for q in questions)
        earned = sum(
            a.get("score_contribution", 0.0) for a in answers
        )

        if total_weight == 0:
            return 0.0

        normalized = (earned / total_weight) * 10.0
        return round(min(normalized, 10.0), 1)


# Module-level singleton
_triage_service: Optional[TriageService] = None

def get_triage_service() -> TriageService:
    global _triage_service
    if _triage_service is None:
        _triage_service = TriageService()
    return _triage_service
