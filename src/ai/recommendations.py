import os
import json
import time
from google import genai
from google.genai import errors


def generate_ai_recommendations(findings):
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return "API key not found. Check your .env file."

    if not findings:
        return "No findings to analyse."

    try:
        client = genai.Client(api_key=api_key)

        prompt = f"""
You are an AI-powered Power BI testing assistant.

Analyse these findings:
{json.dumps(findings, indent=2, default=str)}

For each finding:
1. Explain the issue simply.
2. Explain its possible impact.
3. Suggest a practical fix.
4. Do not invent facts.
5. Distinguish confirmed issues from possible risks.

Do not claim WARNING or NOT RUN checks passed.
Finish with the three highest-priority actions.
"""

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-3.5-flash",
                    contents=prompt
                )

                return response.text or "Gemini returned an empty response."

            except errors.APIError as exc:
                # Retry only temporary server errors.
                if getattr(exc, "code", None) not in (429, 500, 502, 503, 504):
                    return f"Gemini API error: {exc}"

                if attempt == 2:
                    return (
                        "Gemini is temporarily unavailable after "
                        f"3 attempts. Please try again later. Details: {exc}"
                    )

                time.sleep(2 ** (attempt + 1))

    except Exception as exc:
        return f"Gemini analysis failed: {exc}"
