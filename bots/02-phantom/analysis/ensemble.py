import asyncio
import statistics
import structlog
import anthropic
import openai
from google import genai
from dataclasses import dataclass
from polybot.analysis.prompts import (
    build_analysis_prompt, build_challenge_prompt, parse_llm_response,
)

log = structlog.get_logger()
CONFIDENCE_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.2}


@dataclass
class ModelEstimate:
    model: str
    probability: float
    confidence: str
    reasoning: str


@dataclass
class EnsembleResult:
    estimates: list[ModelEstimate]
    ensemble_probability: float
    stdev: float


def shrink_toward_market(ensemble_prob: float, market_price: float,
                         shrinkage: float = 0.30) -> float:
    """
    Apply Bayesian shrinkage toward the market price.

    The market has real money behind it and is usually more calibrated than
    LLMs on extreme-priced markets. LLMs exhibit central tendency bias:
    they rarely output probabilities below 0.15 or above 0.85, so they
    systematically overestimate edge on extreme-priced markets.

    shrinkage=0.30 means: move 30% of the way from the raw ensemble
    estimate toward the market price. This reduces a 43% raw edge to ~30%.
    The calibration correction system will tune this over time.
    """
    return ensemble_prob * (1 - shrinkage) + market_price * shrinkage


def aggregate_estimates(estimates: list[ModelEstimate], trust_weights: dict[str, float]) -> EnsembleResult:
    if not estimates:
        return EnsembleResult(estimates=[], ensemble_probability=0.5, stdev=1.0)
    if len(estimates) == 1:
        return EnsembleResult(estimates=estimates, ensemble_probability=estimates[0].probability, stdev=0.0)
    weighted_sum = 0.0
    weight_total = 0.0
    for est in estimates:
        tw = trust_weights.get(est.model, 0.333)
        cw = CONFIDENCE_WEIGHTS.get(est.confidence, 0.7)
        combined = tw * cw
        weighted_sum += est.probability * combined
        weight_total += combined
    ensemble_prob = weighted_sum / weight_total if weight_total > 0 else 0.5
    stdev = statistics.pstdev([e.probability for e in estimates])
    return EnsembleResult(estimates=estimates, ensemble_probability=ensemble_prob, stdev=stdev)


class EnsembleAnalyzer:
    _MODEL_NAMES = ["claude", "openai", "gemini"]

    def __init__(self, anthropic_key: str, openai_key: str, google_key: str):
        self._anthropic = anthropic.AsyncAnthropic(api_key=anthropic_key)
        self._openai = openai.AsyncOpenAI(api_key=openai_key)
        self._google = genai.Client(api_key=google_key)
        self._consecutive_failures: dict[str, int] = {n: 0 for n in self._MODEL_NAMES}

    async def analyze(self, question: str, research_context: str, trust_weights: dict[str, float]) -> EnsembleResult:
        prompt = build_analysis_prompt(question, research_context)
        results = await asyncio.gather(
            self._call_claude(prompt),
            self._call_openai(prompt),
            self._call_gemini(prompt),
            return_exceptions=True,
        )
        estimates = [r for r in results if isinstance(r, ModelEstimate)]

        for name, result in zip(self._MODEL_NAMES, results):
            if isinstance(result, Exception):
                log.error("llm_call_failed", error=str(result))
                self._consecutive_failures[name] = self._consecutive_failures.get(name, 0) + 1
                if self._consecutive_failures[name] >= 5:
                    log.error("model_persistent_failure", model=name,
                              consecutive=self._consecutive_failures[name])
            else:
                self._consecutive_failures[name] = 0

        if len(estimates) < 3:
            log.warning("ensemble_degraded", responding=len(estimates), total=3)

        return aggregate_estimates(estimates, trust_weights)

    async def _call_claude(self, prompt: str) -> ModelEstimate:
        response = await self._anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = parse_llm_response(response.content[0].text)
        if not parsed:
            raise ValueError("Claude Haiku returned unparseable response")
        return ModelEstimate(
            model="claude-haiku-4.5",
            probability=parsed["probability"],
            confidence=parsed["confidence"],
            reasoning=parsed["reasoning"],
        )

    async def _call_openai(self, prompt: str) -> ModelEstimate:
        response = await self._openai.chat.completions.create(
            model="gpt-5.4-mini",
            max_completion_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = parse_llm_response(response.choices[0].message.content)
        if not parsed:
            raise ValueError("GPT-5.4-mini returned unparseable response")
        return ModelEstimate(
            model="gpt-5.4-mini",
            probability=parsed["probability"],
            confidence=parsed["confidence"],
            reasoning=parsed["reasoning"],
        )

    async def _call_gemini(self, prompt: str) -> ModelEstimate:
        response = await self._google.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        parsed = parse_llm_response(response.text)
        if not parsed:
            raise ValueError("Gemini returned unparseable response")
        return ModelEstimate(
            model="gemini-2.5-flash",
            probability=parsed["probability"],
            confidence=parsed["confidence"],
            reasoning=parsed["reasoning"],
        )

    async def challenge_estimate(self, question: str, initial_prob: float,
                                  market_price: float, reasoning: str) -> float | None:
        """
        Second-pass: reveal market price to Gemini Flash and ask it to revise.
        Returns revised probability or None on failure.

        Only triggered when the initial ensemble disagrees with the market
        by more than 15%. This is the cheapest LLM call (~$0.001) and acts
        as a sanity check against LLM central tendency bias.
        """
        prompt = build_challenge_prompt(question, initial_prob, market_price, reasoning)
        try:
            response = await self._google.aio.models.generate_content(
                model="gemini-2.5-flash", contents=prompt)
            parsed = parse_llm_response(response.text)
            if parsed:
                log.info("challenge_revised", initial=initial_prob,
                         revised=parsed["probability"], market=market_price,
                         reasoning=parsed["reasoning"][:100])
                return parsed["probability"]
        except Exception as e:
            log.error("challenge_failed", error=str(e))
        return None

    async def quick_screen(self, question: str, price: float, resolution_time: str) -> float | None:
        """
        Fast single-LLM quick screening using Gemini Flash.
        Returns probability estimate or None on failure.
        """
        from polybot.analysis.prompts import build_quick_screen_prompt, parse_llm_response
        prompt = build_quick_screen_prompt(question, price, resolution_time)
        try:
            response = await self._google.aio.models.generate_content(
                model="gemini-2.5-flash", contents=prompt)
            parsed = parse_llm_response(response.text)
            if parsed:
                return parsed["probability"]
        except Exception as e:
            log.error("quick_screen_failed", error=str(e))
        return None
