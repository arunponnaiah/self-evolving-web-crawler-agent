from crawler_agent.extraction.prompts import render_feedback_section
from crawler_agent.feedback.store import FeedbackExample


def test_no_examples_produces_empty_section():
    assert render_feedback_section([]) == ""


def test_corrected_example_renders_before_after():
    examples = [
        FeedbackExample(
            original_summary="A rule about widgets.",
            corrected_summary="This rule requires safety labels on widgets sold after 2026.",
            comment="too vague",
            rating="down",
        )
    ]
    section = render_feedback_section(examples)
    assert "A rule about widgets." in section
    assert "This rule requires safety labels on widgets sold after 2026." in section
    assert "too vague" in section
    assert "Lessons from user feedback" in section


def test_down_rating_without_correction_still_renders():
    examples = [
        FeedbackExample(
            original_summary="A rule about widgets.",
            corrected_summary=None,
            comment="missed the key requirement",
            rating="down",
        )
    ]
    section = render_feedback_section(examples)
    assert "missed the key requirement" in section
    assert "A rule about widgets." in section


def test_feedback_section_is_spliced_into_extractor_system_prompt():
    from crawler_agent.extraction.llm_extractor import LlmExtractor

    examples = [
        FeedbackExample(
            original_summary="A rule about widgets.",
            corrected_summary="This rule requires safety labels on widgets.",
            comment="too vague",
            rating="down",
        )
    ]
    extractor = LlmExtractor(api_key="fake-key-not-used", feedback_examples=examples)
    assert "This rule requires safety labels on widgets." in extractor.system_prompt
    assert "too vague" in extractor.system_prompt


def test_no_feedback_leaves_system_prompt_unchanged():
    from crawler_agent.extraction.llm_extractor import LlmExtractor
    from crawler_agent.extraction.prompts import SYSTEM_PROMPT

    extractor = LlmExtractor(api_key="fake-key-not-used")
    assert extractor.system_prompt == SYSTEM_PROMPT
