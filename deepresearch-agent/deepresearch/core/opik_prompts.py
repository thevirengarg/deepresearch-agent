from deepresearch.core import prompts as _prompts

_PROMPT_REGISTRY = {
    "clarify_with_user_instructions": _prompts.CLARIFY_WITH_USER_INSTRUCTIONS,
    "transform_messages_into_research_topic_prompt": _prompts.TRANSFORM_MESSAGES_INTO_RESEARCH_TOPIC_PROMPT,
    "research_agent_prompt": _prompts.RESEARCH_AGENT_PROMPT,
    "summarize_webpage_prompt": _prompts.SUMMARIZE_WEBPAGE_PROMPT,
    "lead_researcher_prompt": _prompts.LEAD_RESEARCHER_PROMPT,
    "compress_research_system_prompt": _prompts.COMPRESS_RESEACH_SYSTEM_PROMPT,
    "compress_research_human_message": _prompts.COMPRESS_RESEACH_HUMAN_MESSAGE,
    "final_report_generation_prompt": _prompts.FINAL_REPORT_GENERTATION_PROMPT,
}


class Opik_prompts:
    @classmethod
    def get_prompt(cls, prompt_name) -> str:
        key = prompt_name.value if hasattr(prompt_name, "value") else str(prompt_name)
        if key not in _PROMPT_REGISTRY:
            raise KeyError(f"Prompt '{key}' not found in local registry")
        return _PROMPT_REGISTRY[key]
