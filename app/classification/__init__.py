"""Public surface of the classification subsystem.

Submodules:
- _shared: internal text helpers shared by other submodules
- folder_rules: sync, filter and summarise folder rules
- normalize: turn raw AI output into a canonical groups.draft.json shape
- prompts: build the AI prompt and parse responses
- io_csv: read/write classification_review.csv and classification_memory.csv
"""

from .folder_rules import (
    FOLDER_RULES_VERSION,
    active_folder_rules_map,
    build_folder_rules_summary_lines,
    derive_suggested_keywords,
    filter_classification_folders,
    print_detailed_classification_guidance,
    sync_folder_rules,
)
from .io_csv import (
    CLASSIFICATION_MEMORY_COLUMNS,
    SKIP_REVIEW_STATUSES,
    build_categorization_from_memory_csv,
    build_categorization_from_review_csv,
    compute_chat_signature,
    export_classification_memory_csv,
    export_classification_review_csv,
)
from .normalize import (
    add_chat_assignment,
    build_summary_lines,
    compute_assigned_chat_ids,
    compute_unassigned_chats,
    create_manual_draft_template,
    merge_categorization_results,
    normalize_groups_data,
    validate_reference_integrity,
)
from .prompts import (
    DECISION_RUBRIC,
    FEWSHOT_EXAMPLES,
    SYSTEM_PROMPT,
    build_manual_prompt,
    build_prompts,
    parse_ai_response_to_groups,
)

__all__ = [
    "FOLDER_RULES_VERSION",
    "SKIP_REVIEW_STATUSES",
    "CLASSIFICATION_MEMORY_COLUMNS",
    "SYSTEM_PROMPT",
    "DECISION_RUBRIC",
    "FEWSHOT_EXAMPLES",
    "active_folder_rules_map",
    "add_chat_assignment",
    "build_categorization_from_memory_csv",
    "build_categorization_from_review_csv",
    "build_folder_rules_summary_lines",
    "build_manual_prompt",
    "build_prompts",
    "build_summary_lines",
    "compute_assigned_chat_ids",
    "compute_chat_signature",
    "compute_unassigned_chats",
    "create_manual_draft_template",
    "derive_suggested_keywords",
    "export_classification_memory_csv",
    "export_classification_review_csv",
    "filter_classification_folders",
    "merge_categorization_results",
    "normalize_groups_data",
    "parse_ai_response_to_groups",
    "print_detailed_classification_guidance",
    "sync_folder_rules",
    "validate_reference_integrity",
]
