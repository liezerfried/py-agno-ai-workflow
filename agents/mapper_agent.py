"""
Maps each anomalous job category to the closest canonical O*NET title.
Routing: rapidfuzz score determines whether the match is accepted automatically
(exact >= 0.90), sent to the LLM for semantic evaluation (0.70-0.89), or escalated
to the human review queue (< 0.70). The LLM is never called when rapidfuzz alone
is sufficient — this keeps token cost proportional to actual ambiguity.
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Literal

from pydantic import BaseModel, model_validator

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.workflow import OnError, Step, StepInput, StepOutput

from agents.mapping_pipeline import FuzzyResult, PipelineConfig, score, routing_band
from agents.translator_agent import translate, TranslationResult
from agents.validator_agent import ValidatorResult
from infrastructure.pipeline.contracts import CategoryValidation
from domain.onet import is_valid_onet_title
from infrastructure.llm.provider import get_model
from infrastructure.pipeline.session import PipelineSession
from infrastructure.pipeline.step_io import deserialize, fail, ok

logger = logging.getLogger(__name__)


class MappingDecision(BaseModel):
    raw: str
    preprocessed: str
    corrected: str | None          # None when needs_review=True; must be exact CSV value
    confidence: float
    method: Literal["exact", "fuzzy", "llm", "needs_review"]
    normalization_type: Literal["typo", "synonym", "language", "format", "abbreviation", "case", "unknown"]
    needs_review: bool
    review_reason: str | None = None

    # Pydantic model_validator enforces the invariant at construction time so no
    # caller can accidentally build an inconsistent MappingDecision at runtime.
    @model_validator(mode="after")
    def _review_fields_consistent(self) -> "MappingDecision":
        if self.needs_review and self.review_reason is None:
            raise ValueError("review_reason must be set when needs_review=True")
        if not self.needs_review and self.review_reason is not None:
            raise ValueError("review_reason must be None when needs_review=False")
        return self


class MappingResult(BaseModel):
    decisions: list[MappingDecision]


# Separate from MappingDecision intentionally: this is the LLM's raw output schema.
# Keeping it narrow limits what the model can say — it cannot return a confidence score
# or a review reason, which are computed by the pipeline, not the LLM.
class SemanticMatch(BaseModel):
    is_equivalent: bool
    canonical_title: str | None    # must be one of the top-3 candidates passed in prompt
    normalization_type: Literal["language", "synonym", "abbreviation", "unknown"]


# Lazy singleton — the Agent instantiation triggers model loading, which is
# expensive. Deferring it means import-time is fast and tests that inject a stub
# via set_agent() never pay the cost of creating a real agent.
_mapper_agent: Agent | None = None


# Shared SqliteDb pointing at the same file the tracer and AgentOS use, so the
# AgentSession this Agent creates lands in the same store as the workflow
# session and the os.agno.com UI can stitch them together. Without db= the
# Agent runs without a session record, and the UI shows the run as a sessionless
# orphan trace.
_AGENT_DB = SqliteDb(db_file="tmp/agentos.db")


def _get_agent() -> Agent:
    global _mapper_agent
    if _mapper_agent is None:
        _mapper_agent = Agent(
            name="MapperAgent",
            model=get_model(),
            db=_AGENT_DB,
            output_schema=SemanticMatch,
            instructions=[
                # Role and context
                "You are a job title normalization expert working with the O*NET occupational database (US Dept. of Labor).",
                "Your task: decide if a raw job title is semantically equivalent to one of the provided O*NET canonical titles.",
                # Core rule — is_equivalent
                "Set is_equivalent=true when the raw title and a candidate describe the SAME professional role, even if the candidate is more specific or uses more formal phrasing.",
                "O*NET titles are intentionally verbose and may add specificity the raw title lacks. Treat the following as VALID matches:",
                "  'Financial Analyst' -> 'Financial and Investment Analysts' (canonical adds 'Investment')",
                "  'QA Analyst' -> 'Software Quality Assurance Analysts and Testers' (canonical expands acronym + scope)",
                "  'Backend Developer' -> 'Software Developers' (canonical is broader job family)",
                "  'CPA' -> 'Accountants and Auditors' (canonical groups related roles)",
                "Set is_equivalent=false ONLY when the candidates describe a fundamentally different role (e.g. 'Dancers' for 'Financial Analyst'), or when the raw input is too vague to identify any profession.",
                # Core rule — canonical_title
                "When is_equivalent=true: copy one candidate verbatim into canonical_title. Do NOT rephrase, shorten, or translate.",
                "When is_equivalent=false: canonical_title MUST be null. Never invent a title outside the candidates list.",
                # normalization_type guide with examples
                "Set normalization_type based on WHY the raw title differs from its canonical form:",
                "  language   -> raw title is in a foreign language. Example: 'Desarrollador Backend' -> 'Backend Web Developers'",
                "  abbreviation -> raw title uses an acronym or shorthand. Example: 'RRHH' -> 'Human Resources Managers', 'QA' -> 'Software Quality Assurance Analysts and Testers'",
                "  synonym    -> gender inflection, alternate wording, or job-title variant for the same role. Example: 'Desarrolladora Frontend' -> 'Frontend Web Developers'",
                "  unknown    -> you cannot determine the reason with confidence.",
                # Hard guardrails
                "NEVER hallucinate: if is_equivalent=true, canonical_title must be exactly one of the candidate strings provided in the prompt.",
                "Pick the closest plausible candidate rather than refusing — the pipeline already escalates obviously bad matches via a separate hallucination guard.",
            ],
        )
    return _mapper_agent


def set_agent(agent: Agent | None) -> None:
    """Override the agent instance. Used by tests to inject a stub without LM Studio."""
    # Passing None resets the singleton so the real agent is rebuilt on the next LLM-band call.
    # Tests that stay in the exact/fuzzy band never call this — only tests covering the LLM
    # path need to inject a stub.
    global _mapper_agent
    _mapper_agent = agent


# Per-anomaly progress callback. Decoupled from any UI so tests, CLI, and Chainlit
# can each plug in their own observer. None means "no observer" — the executor
# runs silently as before.
ProgressCallback = Callable[[int, int], None]
_progress_callback: ProgressCallback | None = None


def set_progress_callback(callback: ProgressCallback | None) -> None:
    """
    Register an observer that receives (processed, total) updates while
    mapper_executor is running. Pass None to clear.

    The callback fires once with (0, total) before the first anomaly and
    again with (i, total) after each anomaly is decided, so the UI can show
    "starting", "in progress", and "done" states without polling.

    Exceptions raised inside the callback are caught and logged so a buggy
    observer cannot abort an in-flight pipeline run.
    """
    global _progress_callback
    _progress_callback = callback


def _emit_progress(processed: int, total: int) -> None:
    cb = _progress_callback
    if cb is None:
        return
    try:
        cb(processed, total)
    except Exception:
        # Never let a misbehaving observer break the pipeline. Log at debug because
        # callback errors are observer bugs, not pipeline bugs.
        logger.debug("progress callback raised", exc_info=True)


# Module-level config so thresholds and top-N candidates are shared across all
# _decide() calls without being re-instantiated per row.
_CONFIG = PipelineConfig()


# Default worker count for parallel anomaly mapping. Tuned from the 2026-05-08
# benchmark: 4 concurrent calls against LM Studio gave ~3.2x speedup (15.4s
# serial → 4.8s parallel) without saturating the local model. Set
# MAPPER_CONCURRENCY=1 to opt out (e.g. when rate-limited remote LLMs).
_DEFAULT_CONCURRENCY = 4


def _resolve_concurrency() -> int:
    raw = os.getenv("MAPPER_CONCURRENCY")
    if raw is None:
        return _DEFAULT_CONCURRENCY
    try:
        n = int(raw)
        # Negative or zero values are nonsensical for a worker count; clamp
        # to serial rather than crash so a typo cannot abort startup.
        return max(1, n)
    except ValueError:
        return _DEFAULT_CONCURRENCY


# Decision cache: skips re-deciding anomalies the mapper has already seen
# within the same process. Two sources of duplicate raws this catches:
#   - same anomaly appearing in two consecutive uploads of similar files
#   - repeated runs of the same file (debugging, reprocessing)
# Combined with temperature=0 in the model layer, cache hits return the exact
# same decision the LLM would have produced — no semantic drift.
#
# No lock: a benign race where two workers compute the same key simultaneously
# is fine. Both produce equivalent decisions (deterministic at temperature=0)
# and the later write just overwrites the earlier one. dict[str] = value is
# atomic in CPython, so we never observe a torn write.
_decision_cache: dict[str, MappingDecision] = {}


def clear_decision_cache() -> None:
    """Drop every cached decision. Used by tests and by callers that need to
    force a fresh evaluation (e.g. after changing the valid_categories list)."""
    _decision_cache.clear()


def _decide_cached(
    anomaly: CategoryValidation,
    valid_categories: list[str],
    valid_categories_set: set[str],
    session_id: str | None = None,
) -> MappingDecision:
    """Cache-aware wrapper around _decide(). The cache key is the raw input
    exactly as the user typed it — preprocessing happens inside _decide and is
    deterministic, so the raw is a sufficient key.

    session_id is intentionally not part of the cache key: it is metadata for
    tracing, not for the decision itself. Two runs with the same raw produce
    the same MappingDecision regardless of which workflow session they belong
    to. Forwarding it only affects cache misses, when we actually call the LLM.
    """
    cached = _decision_cache.get(anomaly.raw)
    if cached is not None:
        return cached
    decision = _decide(anomaly, valid_categories, valid_categories_set, session_id=session_id)
    _decision_cache[anomaly.raw] = decision
    return decision


# Centralised helper so every escalation path logs at the same level with the same
# fields — makes grepping the audit log for review cases reliable.
def _needs_review(anomaly: CategoryValidation, fuzzy: FuzzyResult, reason: str) -> MappingDecision:
    logger.info("needs_review: raw=%r reason=%s score=%.4f", anomaly.raw, reason, fuzzy.top_score)
    return MappingDecision(
        raw=anomaly.raw,
        preprocessed=fuzzy.preprocessed,
        corrected=None,
        confidence=fuzzy.top_score,
        method="needs_review",
        normalization_type="unknown",
        needs_review=True,
        review_reason=reason,
    )


def _handle_exact(anomaly: CategoryValidation, fuzzy: FuzzyResult) -> MappingDecision:
    logger.info("exact: raw=%r -> %r score=%.4f", anomaly.raw, fuzzy.top_match, fuzzy.top_score)
    return MappingDecision(
        raw=anomaly.raw,
        preprocessed=fuzzy.preprocessed,
        corrected=fuzzy.top_match,
        confidence=fuzzy.top_score,
        method="exact",
        normalization_type="format",
        needs_review=False,
    )


def _handle_fuzzy(anomaly: CategoryValidation, fuzzy: FuzzyResult, translation: TranslationResult) -> MappingDecision:
    # If a translation was attempted upstream and it lifted the score into the fuzzy band,
    # the normalization type comes from the translator. If no translation was needed,
    # the mismatch is a typo/format issue resolved by rapidfuzz alone.
    norm_type = translation.normalization_type if translation.was_translated else "typo"
    logger.info("fuzzy: raw=%r -> %r score=%.4f norm_type=%s", anomaly.raw, fuzzy.top_match, fuzzy.top_score, norm_type)
    return MappingDecision(
        raw=anomaly.raw,
        preprocessed=fuzzy.preprocessed,
        corrected=fuzzy.top_match,
        confidence=fuzzy.top_score,
        method="fuzzy",
        normalization_type=norm_type,
        needs_review=False,
    )


def _handle_llm(
    anomaly: CategoryValidation,
    fuzzy: FuzzyResult,
    valid_categories_set: set[str],
    session_id: str | None = None,
) -> MappingDecision:
    logger.info("llm: raw=%r score=%.4f candidates=%s", anomaly.raw, fuzzy.top_score, [t for t, _ in fuzzy.candidates])
    candidates_text = "\n".join(
        f"  {i+1}. {title} (score: {s:.2f})"
        for i, (title, s) in enumerate(fuzzy.candidates)
    )
    prompt = (
        f'Job title to normalize: "{anomaly.raw}"\n'
        f'Preprocessed form: "{fuzzy.preprocessed}"\n'
        f"Candidate canonical titles (ranked by similarity):\n{candidates_text}\n\n"
        "Select the best match if semantically equivalent, or return null if none fit."
    )

    try:
        # session_id (optional) ties this MapperAgent.run() to the parent
        # workflow session in the AgentOS UI. Without it, each agent.run()
        # creates its own session and the UI shows N orphan sessions instead
        # of one cohesive workflow session grouping every inner call.
        run_kwargs = {"session_id": session_id} if session_id is not None else {}
        run_result = _get_agent().run(prompt, **run_kwargs)
        if not isinstance(run_result.content, SemanticMatch):
            raise TypeError(f"LLM returned unexpected content type: {type(run_result.content).__name__}")
        semantic: SemanticMatch = run_result.content

        # Build a set of the exact strings the LLM was shown so we can verify its answer
        # is one of them — not a rephrasing or an invented title.
        candidate_titles = {title for title, _ in fuzzy.candidates}

        if semantic.is_equivalent:
            # Double guard: check both the global O*NET set and the candidates we sent.
            # The LLM may return a valid O*NET title that was NOT in the prompt candidates
            # (a hallucination that happens to exist in the DB); both checks are required.
            if not is_valid_onet_title(semantic.canonical_title, valid_categories_set) or semantic.canonical_title not in candidate_titles:
                logger.warning("LLM hallucination for %r: returned %r", anomaly.raw, semantic.canonical_title)
                return _needs_review(anomaly, fuzzy, "llm_hallucination")
            logger.info("llm accepted: raw=%r -> %r norm_type=%s", anomaly.raw, semantic.canonical_title, semantic.normalization_type)
            return MappingDecision(
                raw=anomaly.raw,
                preprocessed=fuzzy.preprocessed,
                corrected=semantic.canonical_title,
                confidence=fuzzy.top_score,
                method="llm",
                normalization_type=semantic.normalization_type,
                needs_review=False,
            )

        # LLM said not equivalent — legitimate no-match, not a hallucination
        return _needs_review(anomaly, fuzzy, "llm_no_match")

    except Exception as exc:
        logger.warning("LLM call failed for %r: %s", anomaly.raw, exc)
        return _needs_review(anomaly, fuzzy, "llm_error")


def _decide(
    anomaly: CategoryValidation,
    valid_categories: list[str],
    valid_categories_set: set[str],
    session_id: str | None = None,
) -> MappingDecision:
    """
    Produce a MappingDecision for a single anomalous category.

    Routing logic:
      1. Run rapidfuzz to get a top score and candidate list.
      2. If score >= 0.90 (exact band)  -> accept automatically, no LLM call.
      3. If score 0.70-0.89 (fuzzy band) -> accept automatically (high-confidence fuzzy).
      4. If score < 0.70 (review band)  -> try translation first; if that lifts the
         score into a higher band, re-route. Otherwise escalate to human review.
      5. If still in review band after translation -> needs_review=True, no correction written.
      6. If routed to LLM -> call the agent; validate its output; accept or reject.

    session_id (optional): forwarded to translate() and _handle_llm() so the
    inner TranslatorAgent.run() / MapperAgent.run() calls join the parent
    workflow session in the AgentOS UI instead of spawning orphan sessions.
    """
    fuzzy = score(anomaly.raw, valid_categories, _CONFIG)
    band = routing_band(fuzzy.top_score, _CONFIG)
    translation = TranslationResult(english_title=anomaly.raw, was_translated=False, normalization_type="unknown")

    if fuzzy.top_match is None:
        return _needs_review(anomaly, fuzzy, "no_candidates")

    if band == "review":
        # Before giving up, try translating the raw title to English — a Spanish title
        # that scores < 0.70 against O*NET (all English) may score much higher after
        # translation (e.g. "Desarrollador Backend" -> "Backend Developer" -> 0.91).
        translation = translate(anomaly.raw, session_id=session_id)
        # Two reasons to retry the fuzzy with the translated form:
        #   - was_translated=True: Spanish → English, the canonical case
        #   - english_title != raw: the translator expanded an English abbreviation
        #     (e.g. "Back-End Dev" -> "Backend Developer") and reports
        #     was_translated=False because the input was already English. The 2026-05-09
        #     audit found ~9 needs_review cases lost to this flag mismatch alone.
        title_changed = translation.english_title.strip().lower() != anomaly.raw.strip().lower()
        if translation.was_translated or title_changed:
            fuzzy_t = score(translation.english_title, valid_categories, _CONFIG)
            band_t = routing_band(fuzzy_t.top_score, _CONFIG)
            if band_t != "review":
                # Translation lifted the score into a workable band — use the new results.
                fuzzy = fuzzy_t
                band = band_t
        if band == "review":
            return _needs_review(anomaly, fuzzy, "low_confidence")

    if band == "exact":
        return _handle_exact(anomaly, fuzzy)
    if band == "fuzzy":
        return _handle_fuzzy(anomaly, fuzzy, translation)
    return _handle_llm(anomaly, fuzzy, valid_categories_set, session_id=session_id)


def mapper_executor(step_input: StepInput, session_state: dict) -> StepOutput:
    """
    Agno Step executor: runs _decide() for every anomaly produced by ValidatorAgent.

    Pipeline order: IngestAgent -> ValidatorAgent -> MapperAgent (this step) -> AuditWriter

    Only the anomalies list is processed here — categories already validated as exact
    O*NET titles are passed through unchanged by AuditWriter without touching this step.
    """
    try:
        # session_state is the shared dict Agno passes between Steps; from_dict reconstructs
        # the typed PipelineSession so we get the pre-loaded valid_categories list/set.
        session = PipelineSession.from_dict(session_state)
        # previous_step_content is raw JSON from ValidatorAgent's StepOutput; deserialize
        # parses it back into a typed ValidatorResult so _decide() receives structured data.
        validator_result = deserialize(step_input.previous_step_content, ValidatorResult)

        # Optional: workflow_session_id is injected by agent_os.py so every
        # inner TranslatorAgent.run / MapperAgent.run call attaches to the
        # parent workflow session in the AgentOS UI. Absent (e.g. Chainlit
        # path) means each agent run gets its own session.
        workflow_session_id = session_state.get("workflow_session_id")

        anomalies = validator_result.anomalies
        total = len(anomalies)
        # Announce the workload before any LLM call so a UI bound to the callback can
        # show "0/N" the moment the step begins, not five seconds later when the first
        # anomaly finishes — that delay was the entire reason the UI looked frozen.
        _emit_progress(0, total)

        concurrency = _resolve_concurrency()

        if concurrency <= 1 or total <= 1:
            # Serial fast path: avoids ThreadPoolExecutor overhead when the
            # workload is trivially small or concurrency is explicitly disabled.
            decisions: list[MappingDecision] = []
            for i, anomaly in enumerate(anomalies, 1):
                decisions.append(_decide_cached(
                    anomaly, session.valid_categories, session.valid_categories_set,
                    session_id=workflow_session_id,
                ))
                _emit_progress(i, total)
        else:
            # Parallel path: each anomaly is a self-contained _decide() call
            # (LLM-bound, releases the GIL during HTTP I/O). Output ordering
            # is restored by writing each completion to its original index so
            # downstream code can rely on positional consistency.
            decisions = [None] * total  # type: ignore[list-item]
            with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="mapper") as ex:
                future_to_index = {
                    ex.submit(
                        _decide_cached,
                        anomaly,
                        session.valid_categories,
                        session.valid_categories_set,
                        workflow_session_id,
                    ): i
                    for i, anomaly in enumerate(anomalies)
                }
                completed = 0
                for future in as_completed(future_to_index):
                    idx = future_to_index[future]
                    decisions[idx] = future.result()
                    completed += 1
                    # The callback fires from this main thread (as_completed
                    # blocks here) so no extra locking is needed for the counter.
                    _emit_progress(completed, total)

        result = MappingResult(decisions=decisions)
        # ok() serialises result to JSON and wraps it in a successful StepOutput so
        # AuditWriter can deserialize it from step_input.previous_step_content.
        return ok(result)
    except Exception as e:
        # fail() marks the StepOutput as failed; on_error=OnError.fail on the Step
        # stops the workflow and surfaces the error to the caller.
        return fail(e)


mapper_step = Step(
    name="map",
    description="Decide a corrected O*NET title for every anomaly via rapidfuzz pre-filter and conditional LLM routing (exact / fuzzy / llm / needs_review bands), parallelised across MAPPER_CONCURRENCY workers.",
    executor=mapper_executor,
    on_error=OnError.fail,
)