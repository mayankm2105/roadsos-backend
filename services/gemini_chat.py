import google.generativeai as genai
from typing import Optional
from config import settings
from utils.logger import get_logger

ROADSOS_SYSTEM_PROMPT = """
You are RoadSoS, an AI emergency assistant for road accident victims in
Haryana and Delhi, India. You help people find ambulances, hospitals,
police stations, towing services, and mechanics during road emergencies.

CRITICAL RULES:
1. Always respond with EMPATHY first. The user may be injured or in shock.
2. Keep responses SHORT — 2-4 sentences max. People in emergencies cannot
   read long text.
3. Respond in the SAME LANGUAGE the user writes in. If they write in Hindi,
   respond in Hindi. If English, respond in English.
4. Always end your response with the most critical action the user should
   take RIGHT NOW.
5. Never make up phone numbers, addresses, or service details. You will be
   given real service data to include.
6. If someone seems critically injured, always recommend calling 108
   immediately.

INTENT DETECTION:
At the END of every response, on a new line, output exactly:
INTENT: <intent_code>

Where intent_code is ONE of:
- find_ambulance       (user needs ambulance)
- find_police          (user needs police)
- find_hospital        (user needs hospital / medical help)
- find_towing          (user needs towing / vehicle recovery)
- find_mechanic        (user needs puncture / breakdown help)
- find_ambulance_police (user needs both ambulance AND police)
- start_triage         (user describes injury symptoms, needs health assessment)
- sos_share            (user wants to share location with family)
- general_help         (general question, advice needed)
- none                 (greeting, thanks, unclear, non-emergency)

EXAMPLES:
User: "I had an accident, someone is bleeding"
Response: "I'm so sorry to hear that. Please stay calm and call 108
immediately for an ambulance. I'm finding the nearest medical help for you
right now."
INTENT: find_ambulance

User: "मेरी गाड़ी NH44 पर खराब हो गई"
Response: "चिंता न करें, मैं आपके पास के टोइंग सर्विस और मैकेनिक खोज रहा हूं।
कृपया गाड़ी सड़क किनारे करें और हैज़र्ड लाइट चालू करें।"
INTENT: find_towing

User: "my head is hurting and I feel dizzy"
Response: "Those symptoms need immediate medical attention. Please don't
drive. I'm starting a quick health check to assess your condition."
INTENT: start_triage

COVERAGE AREA: Haryana (HR) and Delhi (DL), India only.
EMERGENCY NUMBERS: Ambulance 108, Police 100, Fire 101.
"""

class GeminiChatService:

    def __init__(self):
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not configured in .env")
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model_name = settings.GEMINI_MODEL  # "gemini-1.5-flash"
        self.logger = get_logger(__name__)

    def _build_gemini_history(self, messages: list[dict]) -> list[dict]:
        """
        Convert stored DB message records to Gemini API history format.
        Gemini expects: [{"role": "user"|"model", "parts": ["text"]}]
        Our DB stores: [{"role": "user"|"assistant", "content": "..."}]
        Map "assistant" → "model" for Gemini format.
        Only include last 20 messages to stay within context limits.
        """
        history = []
        for msg in messages[-20:]:
            gemini_role = "model" if msg["role"] == "assistant" else "user"
            # Strip the "INTENT: xxx" line from assistant messages
            # before sending back to Gemini (keep context clean)
            content = msg["content"]
            if gemini_role == "model" and "\nINTENT:" in content:
                content = content.split("\nINTENT:")[0].strip()
            history.append({
                "role": gemini_role,
                "parts": [content]
            })
        return history

    def send_message(
        self,
        message: str,
        history: list[dict],
        lang: str = "en"
    ) -> str:
        """
        Send a message to Gemini with full conversation history.
        Returns the raw Gemini response text (includes INTENT: line).
        """
        try:
            # Build the model with system instruction
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=ROADSOS_SYSTEM_PROMPT
            )

            # Start chat with existing history
            gemini_history = self._build_gemini_history(history)
            chat = model.start_chat(history=gemini_history)

            # Add language hint to message if not English
            enhanced_message = message
            if lang == "hi":
                enhanced_message = f"{message}\n[Please respond in Hindi]"
            elif lang == "pa":
                enhanced_message = f"{message}\n[Please respond in Punjabi]"

            # Send message and get response
            response = chat.send_message(enhanced_message)
            return response.text

        except Exception as e:
            self.logger.error(f"Gemini API error: {e}")
            raise Exception(f"AI service unavailable: {str(e)}")

    def extract_intent(self, gemini_response: str) -> tuple[str, str]:
        """
        Parse the INTENT: line from Gemini's response.
        Returns (clean_reply_text, intent_code)

        Algorithm:
        1. Split response on "\nINTENT:" 
        2. If found: clean_text = parts[0].strip()
                     intent_raw = parts[1].strip().lower()
                     intent = intent_raw if intent_raw in INTENT_SERVICE_MAP
                              else "none"
        3. If not found: clean_text = full response, intent = "none"
        """
        from schemas.chat import INTENT_SERVICE_MAP

        if "\nINTENT:" in gemini_response:
            parts = gemini_response.split("\nINTENT:")
            clean_text = parts[0].strip()
            intent_raw = parts[1].strip().lower().split("\n")[0].strip()
            intent = intent_raw if intent_raw in INTENT_SERVICE_MAP else "none"
        else:
            clean_text = gemini_response.strip()
            intent = "none"

        return clean_text, intent

    def detect_language(self, text: str) -> str:
        """
        Simple heuristic language detection (no external library needed).
        Check for Hindi/Devanagari Unicode range: U+0900 to U+097F.
        Check for Punjabi/Gurmukhi Unicode range: U+0A00 to U+0A7F.
        Otherwise default to "en".
        """
        for char in text:
            if '\u0900' <= char <= '\u097F':
                return "hi"
            if '\u0A00' <= char <= '\u0A7F':
                return "pa"
        return "en"

# Module-level singleton (instantiated lazily)
_gemini_service: Optional[GeminiChatService] = None

def get_gemini_service() -> GeminiChatService:
    global _gemini_service
    if _gemini_service is None:
        _gemini_service = GeminiChatService()
    return _gemini_service
